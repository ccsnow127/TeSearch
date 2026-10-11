"""The size niches suites are filed into.

Suite sizes are compared multiplicatively: writing 5 tests instead of 4 is a
bigger step than writing 51 instead of 50. Niches are therefore spaced by a
constant ratio rho, so each one covers the same relative width.

The grid is centred on an anchor s_bar, the size the backbone writes at when no
size is requested, and covers sizes from s_min up to gamma niches above the
anchor. Anything outside that range falls into one of the two open niches at the
ends, which the search never aims at.

Niches are numbered j = 1..K. Niche j holds the sizes in [b[j-1], b[j]), with
b[0] = 0 and b[K] = infinity.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


def anchor(seed_sizes) -> float:
    """Geometric mean of the seed sizes: the centre the grid is built around."""
    sizes = [s for s in seed_sizes if s > 0]
    if not sizes:
        raise ValueError("anchor needs at least one positive seed size")
    return math.exp(sum(math.log(s) for s in sizes) / len(sizes))


@dataclass(frozen=True)
class Grid:
    bounds: tuple  # the interior boundaries b[1] < … < b[K-1], as whole test counts

    @property
    def K(self) -> int:
        return len(self.bounds) + 1

    def lower(self, j: int) -> float:
        return 0.0 if j == 1 else float(self.bounds[j - 2])

    def upper(self, j: int) -> float:
        return math.inf if j == self.K else float(self.bounds[j - 1])

    def niche_of(self, size: float) -> int:
        """The niche a suite of this size belongs to."""
        j = 1
        for b in self.bounds:
            if size >= b:
                j += 1
            else:
                break
        return j

    @property
    def arms(self) -> range:
        """The niches the search may aim at: everything but the two open ends."""
        return range(2, self.K)

    def center(self, k: int) -> float:
        """Geometric midpoint of a niche, the size a call aimed there targets."""
        if k not in self.arms:
            raise ValueError(f"niche {k} is an open end niche and has no centre")
        return math.sqrt(self.lower(k) * self.upper(k))

    def z(self, j: int) -> float:
        """Where a niche sits on the size axis, from 0 (smallest) to 1 (largest)."""
        return (j - 1) / (self.K - 1)

    def to_dict(self) -> dict:
        return {"bounds": list(self.bounds)}

    @classmethod
    def from_dict(cls, d: dict) -> "Grid":
        return cls(tuple(d["bounds"]))


def build(s_min: int, s_bar: float, sigma: float, gamma: int) -> Grid:
    """Lay out the boundaries over [s_min, s_bar * rho**gamma].

    Boundaries sit on the lattice s_bar * rho**(i + 1/2), which puts the anchor in
    the middle of a niche rather than on an edge. Sizes are whole numbers, so each
    boundary is rounded up and duplicates are dropped; at small sizes that leaves
    some niches only one test wide.

    When s_min is above the anchor -- a module with a large public API whose seed
    suites came out small -- the top of the range is measured from s_min instead,
    so the range never collapses.
    """
    rho = math.exp(2.0 * sigma)
    lo = max(1, int(s_min))
    hi = max(math.ceil(max(s_bar, lo) * rho ** gamma), lo + 2)
    bounds = {lo, hi}
    i_lo = math.floor(math.log(lo / s_bar) / math.log(rho) - 0.5)
    i_hi = math.ceil(math.log(hi / s_bar) / math.log(rho) - 0.5)
    for i in range(i_lo, i_hi + 1):
        b = s_bar * rho ** (i + 0.5)
        if lo < b < hi:
            bounds.add(math.ceil(b))
    return Grid(tuple(sorted(bounds)))
