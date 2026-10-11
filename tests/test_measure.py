from tesearch.harness.measure import exception_of, measure
from tesearch.harness.suite_ast import count_tests, drop_failing_tests

SUITE = """\
import pytest

def test_ok():
    assert 1

def test_bad():
    assert 0

class TestC:
    def test_m(self):
        assert 1
"""


class FakeExecutor:
    def __init__(self, verdicts, mutation=0.5, total=10):
        self.verdicts, self.mutation, self.total = verdicts, mutation, total
        self.probed, self.mutated = [], []
        self.mutants = {"m1": {"line": 4, "operator": "core/AddNot"}}

    def probe(self, src):
        self.probed.append(src)
        names = [n for n in self.verdicts if f"def {n}(" in src]
        tests = [{"name": f"tests/test_x.py::{n}", "verdict": self.verdicts[n],
                  "traceback": "E   AssertionError: assert 0" if self.verdicts[n] != "PASSED" else ""}
                 for n in names]
        cov = 0.9 if len(self.probed) == 1 else 0.7
        return {"tests": tests, "coverage": cov, "uncovered": [3]}

    def mutate(self, src, fold):
        self.mutated.append((src, fold))
        return {"mutation": self.mutation, "total": self.total, "green": True,
                "survivors": [{"id": "m1"}]}


def test_count_tests_counts_functions_and_methods():
    assert count_tests(SUITE) == 3
    assert count_tests("not python (") == 0


def test_drop_failing_tests():
    out = drop_failing_tests(SUITE, {"test_bad"})
    assert "test_bad" not in out and "test_ok" in out and "test_m" in out


def test_all_green_measures_once():
    ex = FakeExecutor({"test_ok": "PASSED", "test_bad": "PASSED", "test_m": "PASSED"})
    m = measure(ex, SUITE)
    assert (m.size, m.green_size, m.pass_rate, m.cov, m.mut) == (3, 3, 1.0, 0.9, 0.5)
    assert len(ex.probed) == 1
    assert m.survivors == [{"id": "m1", "line": 4, "operator": "core/AddNot"}]


def test_failing_tests_are_pruned_and_green_reprobed():
    ex = FakeExecutor({"test_ok": "PASSED", "test_bad": "FAILED", "test_m": "PASSED"})
    m = measure(ex, SUITE)
    assert m.size == 3 and m.green_size == 2
    assert m.cov == 0.7                        # from the green re-probe
    assert "test_bad" not in ex.mutated[0][0]
    assert m.failing == {"test_bad": "AssertionError: assert 0"}


def test_nothing_passes_is_not_measured():
    ex = FakeExecutor({"test_ok": "FAILED", "test_bad": "FAILED", "test_m": "ERROR"})
    assert measure(ex, SUITE) is None
    assert measure(ex, "x = 1\n") is None


def test_exception_of():
    tb = "    def test_x():\n>       assert f() == 2\nE       assert 1 == 2\nE   KeyError: 'a'\n"
    assert exception_of(tb) == "KeyError: 'a'"
    assert exception_of("") == "failed"


def test_exception_of_assertion_with_diff():
    tb = "t.py:25: in test_x\n    assert 1 == 2\nE   assert 1 == 2\nE     -1\nE     +2\n"
    assert exception_of(tb) == "assert 1 == 2"
