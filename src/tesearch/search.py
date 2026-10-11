"""Running the search on one module.

It opens with a few generations that name no size, measures them, and builds the
niche grid from the sizes that came back. After that every call: works out the
request for each niche and where it would likely land, picks a niche, breeds from
the two archived suites nearest that size, files the result in the niche it
actually landed in, and updates the size bias and the niche values.

What is delivered at the end is the smallest suite among those of the best
quality found -- the passing subset of it, scored once against the held-out
mutants.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from . import prompts
from .archive import Archive, Suite
from .config import Config
from .data import ModuleTask
from .grid import anchor, build
from .harness.measure import Measurement, MeasurementError
from .harness.suite_ast import count_tests
from .kernel import aim, landing_probs, update_bias
from .parents import annotations, mode, order, select_parents
from .ucb import SizeUCB

log = logging.getLogger(__name__)


class Measurer(Protocol):
    def measure(self, src: str, fold: str = "search") -> Measurement | None: ...


class Generator(Protocol):
    def complete(self, system: str, user: str, tag: str = ""): ...


@dataclass
class Delivered:
    suite: Suite
    eval_cov: float | None = None
    eval_mut: float | None = None

    def to_dict(self) -> dict:
        s = self.suite
        out = {"uid": s.uid, "call": s.call, "size": s.size, "green_size": s.green_size,
               "cov": s.cov, "mut": s.mut, "hv": s.hv, "loc": s.loc}
        if self.eval_mut is not None:
            out.update(eval_cov=self.eval_cov, eval_mut=self.eval_mut,
                       eval_hv=self.eval_cov * self.eval_mut)
        return out


class TeSearch:
    def __init__(self, task: ModuleTask, measurer: Measurer, llm: Generator,
                 cfg: Config = Config(), out_dir: str | Path | None = None) -> None:
        self.task = task
        self.measurer = measurer
        self.llm = llm
        self.cfg = cfg
        self.out = Path(out_dir) if out_dir else None
        self.archive = Archive()
        self.ucb: SizeUCB | None = None
        self.delta = 0.0
        self.calls = 0
        self.suites: dict[int, Suite] = {}      # every measured suite, not just archived ones
        self.s_bar: float | None = None
        self.tokens = {"prompt": 0, "completion": 0}
        self._last: dict = {}                   # per-call record merged into the event
        self._harness_errors = 0
        if self.out:
            self.out.mkdir(parents=True, exist_ok=True)

    # =============================================================== driver
    def run(self) -> Delivered | None:
        while self.calls < self.cfg.budget:
            if self.archive.grid is None:
                self._unhinted_call()
                if self.calls >= self.cfg.n_seed and self.archive.provisional:
                    self._build_grid()
            else:
                self._breed_call()
            self.save()
        return self.deliver()

    # ============================================================ seed phase
    def _unhinted_call(self) -> None:
        """An opening generation, or a retry while the archive is still empty.

        No size is named, so there is nothing to aim at and no arm to charge.
        """
        user = prompts.seed_user(self.task.dotted, self.task.code_src)
        suite = self._generate(prompts.SEED_SYS, user, tag="seed")
        if suite is not None:
            self.archive.file(suite)
        self._event({"kind": "seed", **self._suite_fields(suite)})

    def _build_grid(self) -> None:
        """Lay out the niches from the seed sizes and file the seeds into them."""
        seeds = self.archive.provisional
        self.s_bar = anchor([s.size for s in seeds])
        grid = build(self.task.s_min, self.s_bar, self.cfg.sigma, self.cfg.gamma)
        self.ucb = SizeUCB(grid, self.cfg.alpha_q, self.cfg.c_e, self.cfg.H)
        self.delta = 0.0
        for suite, j, reward in self.archive.regrid(grid):
            self.ucb.credit(j, reward)
            self.ucb.observe_hv(suite.hv)
        self._event({"kind": "grid", "s_bar": self.s_bar, "s_min": self.task.s_min,
                     "bounds": list(grid.bounds), "K": grid.K})

    # =========================================================== search step
    def _breed_call(self) -> None:
        grid, cfg = self.archive.grid, self.cfg
        asks, probs = {}, {}
        for k in grid.arms:                       # what to request per niche, and where it lands
            tau = grid.center(k)
            asks[k] = (tau, aim(tau, self.delta, cfg.kappa_a))
            probs[k] = landing_probs(asks[k][1], self.delta, cfg.sigma, grid)
        k, scores = self.ucb.select(probs)
        tau, a = asks[k]

        parents = order(select_parents(self.archive.members(), tau))
        if parents:
            m = mode(parents[-1], tau)           # shrink the strongest example, or grow it
            system = prompts.breed_system(m)
            user = prompts.breed_user(self.task.dotted, self.task.code_src, a,
                                      parents, annotations(parents))
        else:
            m, system = "seed", prompts.SEED_SYS
            user = prompts.seed_user(self.task.dotted, self.task.code_src, a)

        lam = self.ucb.lam()
        suite = self._generate(system, user, tag=f"breed:{m}")
        self.ucb.charge(k)                       # the request is charged, measured or not
        landed, reward = None, 0.0
        if suite is not None:
            landed, reward = self.archive.file(suite)
            self.delta = update_bias(self.delta, suite.size, a, cfg.eta)
            self.ucb.credit(landed, reward)
            self.ucb.observe_hv(suite.hv)
        self._event({"kind": "breed", "arm": k, "tau": tau, "ask": a, "mode": m,
                     "parents": [p.uid for p in parents], "landed": landed,
                     "reward": reward, "delta": self.delta, "lambda": lam,
                     "p_on_target": probs[k][k - 1], "ucb": scores[k],
                     "moqd": self.archive.moqd(), **self._suite_fields(suite)})

    # ============================================================ generation
    def _generate(self, system: str, user: str, tag: str) -> Suite | None:
        self.calls += 1
        t0 = time.time()
        completion = self.llm.complete(system, user, tag=f"call{self.calls:03d}:{tag}")
        t1 = time.time()
        src = prompts.extract_code(getattr(completion, "text", completion))
        usage = getattr(completion, "usage", None) or {}
        for k in ("prompt", "completion"):
            self.tokens[k] += int(usage.get(f"{k}_tokens") or 0)
        error = None
        try:
            meas = self.measurer.measure(src, fold="search")
            self._harness_errors = 0
        except Exception as exc:  # noqa: BLE001 — a harness hiccup costs one call, not the run
            log.warning("%s call %d: measurement failed: %s", self.task.instance_id, self.calls, exc)
            meas, error = None, f"{type(exc).__name__}: {exc}"[:2000]
            self._harness_errors += 1
            if self._harness_errors >= 3:
                self._save_suite(src, None, error)
                raise MeasurementError(f"harness failed on 3 consecutive calls: {error}") from exc
        self._last = {"prompt_tokens": usage.get("prompt_tokens"),
                      "completion_tokens": usage.get("completion_tokens"),
                      "llm_s": round(t1 - t0, 1), "measure_s": round(time.time() - t1, 1),
                      "written": count_tests(src)}
        self._save_suite(src, meas, error)
        if meas is None:
            return None
        suite = Suite(uid=len(self.suites), src=src, size=meas.size, cov=meas.cov,
                      mut=meas.mut, pass_rate=meas.pass_rate, green_size=meas.green_size,
                      loc=len(src.splitlines()), green_src=meas.green_src,
                      failing=meas.failing, uncovered=meas.uncovered,
                      survivors=meas.survivors, call=self.calls)
        self.suites[suite.uid] = suite
        return suite

    def _save_suite(self, src: str, meas: Measurement | None, error: str | None) -> None:
        """Write one call's suite, its passing subset and its measurement to disk."""
        if not self.out:
            return
        d = self.out / "suites"
        d.mkdir(exist_ok=True)
        stem = f"call_{self.calls:03d}"
        (d / f"{stem}.py").write_text(src, encoding="utf-8")
        record = {"call": self.calls, "measured": meas is not None, "error": error}
        if meas is not None:
            (d / f"{stem}.green.py").write_text(meas.green_src, encoding="utf-8")
            record.update({k: v for k, v in vars(meas).items() if k != "green_src"})
        (d / f"{stem}.json").write_text(json.dumps(record, indent=1), encoding="utf-8")

    # ============================================================== delivery
    def deliver(self) -> Delivered | None:
        """Pick what to hand back: of the suites tying for best quality, the one the
        model wrote fewest tests for. Its passing subset is what ships, and it is
        scored once against the held-out mutants it was never optimised on."""
        if not self.suites:
            return None
        hv_max = max(s.hv for s in self.suites.values())
        best = min((s for s in self.suites.values() if s.hv == hv_max),
                   key=lambda s: (s.size, s.loc, s.uid))
        result = Delivered(best)
        try:
            ev = self.measurer.measure(best.green_src, fold="eval")
        except MeasurementError as exc:
            log.warning("eval-fold measurement failed: %s", exc)
            ev = None
        if ev is not None:
            result.eval_cov, result.eval_mut = ev.cov, ev.mut
        if self.out:
            (self.out / "delivered_suite.py").write_text(best.green_src, encoding="utf-8")
            summary = {"module": self.task.module_id, "instance_id": self.task.instance_id,
                       "model": self.cfg.model, "calls": self.calls,
                       "measured": len(self.suites), "tokens": dict(self.tokens),
                       "moqd": self.archive.moqd(),
                       "grid": self.archive.grid.to_dict() if self.archive.grid else None,
                       "delta": self.delta,
                       "delivered": result.to_dict(), "config": self.cfg.to_dict()}
            (self.out / "result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return result

    # ============================================================ bookkeeping
    @staticmethod
    def _suite_fields(suite: Suite | None) -> dict:
        if suite is None:
            return {"measured": False}
        return {"measured": True, "uid": suite.uid, "size": suite.size, "cov": suite.cov,
                "mut": suite.mut, "hv": suite.hv, "pass_rate": suite.pass_rate}

    def _event(self, record: dict) -> None:
        if not self.out:
            return
        record = {"call": self.calls, "ts": round(time.time(), 3), **record}
        if record.get("kind") in ("seed", "breed"):
            record.update(self._last)
        with (self.out / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def save(self) -> None:
        if not self.out:
            return
        state = {"calls": self.calls, "delta": self.delta, "s_bar": self.s_bar,
                 "tokens": self.tokens,
                 "suites": [s.to_dict() for s in self.suites.values()],
                 "archive": self.archive.to_dict(),
                 "ucb": self.ucb.to_dict() if self.ucb else None}
        tmp = self.out / "state.json.tmp"
        tmp.write_text(json.dumps(state), encoding="utf-8")
        tmp.replace(self.out / "state.json")

    def resume(self) -> bool:
        """Pick a run back up from ``state.json``, if one was written."""
        path = self.out / "state.json" if self.out else None
        if not path or not path.exists():
            return False
        state = json.loads(path.read_text(encoding="utf-8"))
        self.calls, self.delta, self.s_bar = state["calls"], state["delta"], state["s_bar"]
        self.tokens = state.get("tokens", self.tokens)
        self.suites = {d["uid"]: Suite.from_dict(d) for d in state["suites"]}
        self.archive = Archive.from_dict(state["archive"], self.suites)
        if self.archive.grid is not None:
            self.ucb = SizeUCB(self.archive.grid, self.cfg.alpha_q, self.cfg.c_e, self.cfg.H)
            self.ucb.load(state["ucb"])
        return True
