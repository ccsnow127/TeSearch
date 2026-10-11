import json
import math

import pytest

from tesearch.config import Config
from tesearch.search import TeSearch

from conftest import FakeLLM, FakeMeasurer


def test_full_run_follows_algorithm_1(task, tmp_path):
    llm = FakeLLM(bias=0.1, noise=0.08)
    s = TeSearch(task, FakeMeasurer(), llm, Config(), tmp_path)
    delivered = s.run()

    assert s.calls == 50 and len(llm.calls) == 50
    events = [json.loads(l) for l in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert [e["kind"] for e in events[:4]] == ["seed", "seed", "seed", "grid"]
    breeds = [e for e in events if e["kind"] == "breed"]
    assert len(breeds) == 47
    grid = s.archive.grid
    assert all(e["arm"] in grid.arms for e in breeds)
    assert grid.bounds[0] == task.s_min
    # δ tracks the realized log ratio ln(s/a) (integer rounding included)
    tail = [math.log(e["size"] / e["ask"]) for e in breeds[-20:] if e["measured"]]
    assert s.delta == pytest.approx(sum(tail) / len(tail), abs=0.05)
    assert 0.0 < s.delta < 0.3
    assert sum(s.ucb.m.values()) == 47

    # delivery picks the smallest suite among those tying for the best quality
    hv_max = max(x.hv for x in s.suites.values())
    ties = [x for x in s.suites.values() if x.hv == hv_max]
    assert delivered.suite.hv == hv_max
    assert delivered.suite.size == min(x.size for x in ties)
    assert delivered.eval_mut is not None
    result = json.loads((tmp_path / "result.json").read_text())
    assert result["delivered"]["size"] == delivered.suite.size


def test_first_breed_is_a_bred_prompt_with_size_ask(task, tmp_path):
    llm = FakeLLM()
    TeSearch(task, FakeMeasurer(), llm, Config(budget=4), tmp_path).run()
    system, user, tag = llm.calls[3]
    assert tag.startswith("call004:breed:")
    assert "HARD REQUIREMENT" in user and "[test_suite_v0" in user
    assert "[TARGET SIZE]" not in llm.calls[0][1]           # seeds are unhinted


def test_unmeasurable_calls_are_charged(task, tmp_path):
    class Flaky(FakeMeasurer):
        def __init__(self):
            self.n = 0

        def measure(self, src, fold="search"):
            self.n += 1
            return None if (fold == "search" and self.n % 2 == 0 and self.n > 4) else super().measure(src, fold)

    s = TeSearch(task, Flaky(), FakeLLM(), Config(budget=20), tmp_path)
    s.run()
    assert s.calls == 20
    assert sum(s.ucb.m.values()) == 20 - 3


def test_resume(task, tmp_path):
    s1 = TeSearch(task, FakeMeasurer(), FakeLLM(), Config(budget=10), tmp_path)
    s1.run()
    s2 = TeSearch(task, FakeMeasurer(), FakeLLM(), Config(budget=15), tmp_path)
    assert s2.resume() and s2.calls == 10
    assert s2.archive.grid == s1.archive.grid
    assert s2.ucb.m == s1.ucb.m and s2.delta == s1.delta
    s2.run()
    assert s2.calls == 15


def test_size_pressure_shrinks_delivery(task, tmp_path):
    """With quality saturating, the gate opens and later calls aim at smaller niches."""
    s = TeSearch(task, FakeMeasurer(), FakeLLM(noise=0.05), Config(), tmp_path)
    s.run()
    breeds = [json.loads(l) for l in (tmp_path / "events.jsonl").read_text().splitlines()
              if '"breed"' in l]
    assert any(e["lambda"] > 0 for e in breeds)
