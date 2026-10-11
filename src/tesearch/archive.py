"""The collection of suites found so far, split by size.

Each niche keeps its own Pareto front over coverage and mutation score, so a
small suite never has to compete against a large one: size decides which front a
suite joins, coverage and mutation decide whether it stays on that front.

The score of the whole archive is the total area its fronts dominate, summed
over niches. A call is rewarded by how much it raises that total, which covers
both improving a niche that already had suites and filling an empty one.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .grid import Grid


@dataclass
class Suite:
    """One measured suite.

    ``size`` is what the model wrote -- the number of test functions -- and is
    what decides the niche. ``cov`` and ``mut`` are measured on the tests that
    pass, whose source is kept in ``green_src``.
    """

    uid: int
    src: str
    size: int
    cov: float
    mut: float
    pass_rate: float
    green_size: int
    loc: int
    green_src: str = ""
    failing: dict = field(default_factory=dict)     # {test name: exception}
    uncovered: list = field(default_factory=list)   # module lines no passing test runs
    survivors: list = field(default_factory=list)   # [{"id", "line", "operator"}]
    call: int = 0                                   # the call that produced it

    @property
    def hv(self) -> float:
        """Combined quality: high only when coverage and mutation are both high."""
        return self.cov * self.mut

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Suite":
        return cls(**d)


def dominates(a: Suite, b: Suite) -> bool:
    """True when ``a`` is at least as good on coverage and on mutation."""
    return a.cov >= b.cov and a.mut >= b.mut


def front_hv(front: list[Suite]) -> float:
    """Area covered by a front, sweeping it as a staircase.

    Each suite contributes the strip of area that no better-covering suite
    already claims, so redundant suites add nothing.
    """
    area, best_mut = 0.0, 0.0
    for s in sorted(front, key=lambda t: (-t.cov, -t.mut)):
        if s.mut > best_mut:
            area += s.cov * (s.mut - best_mut)
            best_mut = s.mut
    return area


class Archive:
    """Fronts per niche, plus the suites filed before the grid existed.

    During the opening generations there is no grid yet, so seeds are parked
    without competing; :meth:`regrid` files them once the grid is known.
    """

    def __init__(self) -> None:
        self.grid: Grid | None = None
        self.fronts: dict[int, list[Suite]] = {}
        self.provisional: list[Suite] = []

    # ------------------------------------------------------------------ filing
    def file(self, suite: Suite) -> tuple[int | None, float]:
        """File a suite by its written size; return its niche and its reward.

        Only the niche a suite lands in can change, so the reward is that niche's
        gain in dominated area. A suite that is matched or beaten on both axes by
        a suite already there is dropped and earns nothing.
        """
        if self.grid is None:
            self.provisional.append(suite)
            return None, 0.0
        j = self.grid.niche_of(suite.size)
        front = self.fronts.setdefault(j, [])
        if any(dominates(t, suite) for t in front):
            return j, 0.0
        before = front_hv(front)
        front[:] = [t for t in front if not dominates(suite, t)] + [suite]
        delta = front_hv(front) - before
        return j, min(1.0, max(0.0, delta))

    def regrid(self, grid: Grid) -> list[tuple[Suite, int, float]]:
        """Install the grid and file the parked seeds, in the order they arrived.

        Returns each seed's niche and reward so the caller can start its value
        estimates from what the seeds already showed.
        """
        self.grid = grid
        self.fronts = {}
        pending, self.provisional = self.provisional, []
        out = []
        for suite in pending:
            j, delta = self.file(suite)
            out.append((suite, j, delta))
        return out

    # ----------------------------------------------------------------- queries
    def moqd(self) -> float:
        """Total area dominated across all niches."""
        return sum(front_hv(f) for f in self.fronts.values())

    def members(self) -> list[Suite]:
        """Every front member, in niche order: the pool parents are drawn from."""
        if self.grid is None:
            return list(self.provisional)
        return [s for j in sorted(self.fronts) for s in self.fronts[j]]

    def __len__(self) -> int:
        return len(self.members())

    def to_dict(self) -> dict:
        return {
            "grid": self.grid.to_dict() if self.grid else None,
            "fronts": {str(j): [s.uid for s in f] for j, f in self.fronts.items()},
            "provisional": [s.uid for s in self.provisional],
        }

    @classmethod
    def from_dict(cls, d: dict, suites: dict[int, Suite]) -> "Archive":
        a = cls()
        a.grid = Grid.from_dict(d["grid"]) if d.get("grid") else None
        a.fronts = {int(j): [suites[u] for u in uids] for j, uids in d["fronts"].items()}
        a.provisional = [suites[u] for u in d.get("provisional", [])]
        return a
