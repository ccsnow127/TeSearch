"""Scoring one suite.

One measurement produces two snapshots of the same suite:
  * raw   — as the model wrote it: its written size (the niche descriptor) and
            its pass rate;
  * green — its passing subset, on which coverage and mutation score are computed.
A failing test trivially "kills" every mutant, so mutation is scored on the green
subset only, and coverage is re-probed on it because a failing test executes part
of the module before it raises.

A suite with no tests, or none that pass, yields no measurement: it has no niche
to occupy and no fitness to defend.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .suite_ast import canon, count_tests, drop_failing_tests


@dataclass
class Measurement:
    size: int                 # written size s(T)
    pass_rate: float
    green_size: int
    cov: float                # c(T), green subset
    mut: float                # m(T), green subset, on the requested fold
    green_src: str
    failing: dict = field(default_factory=dict)    # {test name: exception}
    uncovered: list = field(default_factory=list)  # module lines the green subset misses
    survivors: list = field(default_factory=list)  # [{"id", "line", "operator"}]


class MeasurementError(RuntimeError):
    """The harness failed to score a suite (not the same as scoring zero)."""


_EXC = re.compile(r"^E\s+([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Warning|Failed)\b[^\n]*)",
                  re.MULTILINE)


def exception_of(traceback: str) -> str:
    """Short exception text for the ``# <-- FAILING: <exception>`` mark."""
    found = _EXC.findall(traceback or "")
    if found:
        return found[-1].strip()[:120]
    e_lines = [l[1:].strip() for l in (traceback or "").splitlines() if l.startswith("E ")]
    if e_lines:
        return e_lines[0][:120]          # the failing assertion, before any diff detail
    lines = [l.strip() for l in (traceback or "").splitlines() if l.strip()]
    return lines[-1][:120] if lines else "failed"


def _verdicts(probe: dict) -> tuple[set, dict]:
    passing, failing = set(), {}
    for t in probe.get("tests", []):
        name = canon(t.get("name", ""))
        if not name:
            continue
        if str(t.get("verdict", "")).upper() in ("PASSED", "XFAIL", "XPASS"):
            passing.add(name)
        else:
            failing[name] = exception_of(t.get("traceback", ""))
    passing -= set(failing)    # a parametrized test fails if any case fails
    return passing, failing


def measure(executor, suite_src: str, fold: str = "search") -> Measurement | None:
    size = count_tests(suite_src)
    if size == 0:
        return None
    probe = executor.probe(suite_src)
    passing, failing = _verdicts(probe)
    if not passing:
        return None
    n_run = len(passing) + len(failing)

    if failing:
        green_src = drop_failing_tests(suite_src, set(failing))
        if green_src.strip() == suite_src.strip():
            return None
        green_probe = executor.probe(green_src)
        cov, uncovered = float(green_probe.get("coverage", 0.0)), green_probe.get("uncovered", [])
    else:
        green_src = suite_src
        cov, uncovered = float(probe.get("coverage", 0.0)), probe.get("uncovered", [])

    mut = executor.mutate(green_src, fold)
    if not mut.get("green", True):
        return None                     # flaky: the green subset did not pass again
    if int(mut.get("total") or 0) == 0:
        mut = executor.mutate(green_src, fold)
        if int(mut.get("total") or 0) == 0:
            raise MeasurementError("mutation run scored no mutants")

    survivors = []
    for s in mut.get("survivors", []):
        spec = getattr(executor, "mutants", {}).get(s.get("id"), {})
        survivors.append({"id": s.get("id"), "line": s.get("line") or spec.get("line"),
                          "operator": s.get("operator") or spec.get("operator", "")})
    return Measurement(
        size=size, pass_rate=round(len(passing) / n_run, 4), green_size=len(passing),
        cov=cov, mut=float(mut.get("mutation", 0.0)), green_src=green_src,
        failing=failing, uncovered=[int(n) for n in uncovered], survivors=survivors)
