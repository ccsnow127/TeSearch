"""Offline doubles: an LLM that writes n·e^{δ*+ε} tests when asked for n, and a
measurer whose quality grows with suite size and saturates."""
import math
import random
import re

import pytest

from tesearch.data import ModuleTask
from tesearch.harness.measure import Measurement
from tesearch.harness.suite_ast import count_tests

MODULE_SRC = '''\
def add(a, b):
    return a + b


def sub(a, b):
    return a - b


class Box:
    def get(self):
        return 1

    def _hidden(self):
        return 2
'''


def make_suite(n: int) -> str:
    return "\n".join(f"def test_{i}():\n    assert {i} == {i}\n" for i in range(n))


class FakeLLM:
    def __init__(self, bias: float = 0.1, noise: float = 0.08, seed_size: int = 20, seed: int = 0):
        self.bias, self.noise, self.seed_size = bias, noise, seed_size
        self.rng = random.Random(seed)
        self.calls = []

    def complete(self, system, user, tag=""):
        self.calls.append((system, user, tag))
        m = re.search(r"exactly (\d+) test functions", user)
        n = int(m.group(1)) if m else self.seed_size
        s = max(1, round(n * math.exp(self.bias + self.rng.gauss(0.0, self.noise))))
        return make_suite(s)


class FakeMeasurer:
    """cov and mut rise with size and saturate, so larger suites win on hv until
    the curve flattens; the eval fold is slightly harder than the search fold."""

    def measure(self, src, fold="search"):
        n = count_tests(src)
        if n == 0:
            return None
        scale = 1.0 if fold == "search" else 0.95
        cov = round(min(1.0, 1 - math.exp(-n / 12)), 3)
        mut = round(scale * min(1.0, 1 - math.exp(-n / 18)), 3)
        return Measurement(size=n, pass_rate=1.0, green_size=n, cov=cov, mut=mut,
                           green_src=src, uncovered=[1] if cov < 1 else [],
                           survivors=[{"id": "m1", "line": 2, "operator": "core/NumberReplacer"}])


@pytest.fixture
def task():
    return ModuleTask(repo="pallets/flask", version="2.3", instance_id="pallets__flask-1",
                      row_id="pallets__flask-1-0", base_commit="", patch="",
                      code_file="src/flask/toy.py", code_src=MODULE_SRC,
                      test_file="tests/test_toy.py")
