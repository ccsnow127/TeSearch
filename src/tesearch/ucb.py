"""Choosing which niche spends the next call.

Each niche is one arm of a bandit. Its score adds up three things:

  * what generations landing there have been worth so far,
  * a penalty that grows with niche size, switched on only once the module has
    reached decent quality,
  * a bonus for arms that have been aimed at few times.

Because a call aimed at one niche often lands in a neighbour, the first two terms
are averaged over the niches the call might actually reach.
"""
from __future__ import annotations

import math

from .grid import Grid


class SizeUCB:
    def __init__(self, grid: Grid, alpha_q: float, c_e: float, H: float) -> None:
        self.grid = grid
        self.alpha_q = alpha_q
        self.c_e = c_e
        self.H = H
        self.q: dict[int, float] = {}   # value estimate per niche that has been reached
        self.m: dict[int, int] = {}     # how many generations were aimed at each niche
        self.hv_best = 0.0

    # ------------------------------------------------------------- estimates
    def lam(self) -> float:
        """Strength of the size penalty: zero until quality passes the gate."""
        return max(0.0, self.hv_best - self.H)

    def q_hat(self, j: int) -> float:
        """Value of a niche; one never reached takes the average of the others."""
        if j in self.q:
            return self.q[j]
        return sum(self.q.values()) / len(self.q) if self.q else 0.0

    def score(self, k: int, probs: list[float]) -> float:
        lam = self.lam()
        exploit = sum(p * (self.q_hat(j) - lam * self.grid.z(j))
                      for j, p in enumerate(probs, start=1))
        return exploit + self.c_e / math.sqrt(self.m.get(k, 0) + 1)

    def select(self, probs_by_arm: dict[int, list[float]]) -> tuple[int, dict[int, float]]:
        """Pick the best-scoring arm; a tie goes to the smaller niche."""
        scores = {k: self.score(k, p) for k, p in probs_by_arm.items()}
        best = max(scores, key=lambda k: (scores[k], -k))
        return best, scores

    # --------------------------------------------------------------- updates
    def charge(self, k: int) -> None:
        """Count one generation against an arm, measured or not."""
        self.m[k] = self.m.get(k, 0) + 1

    def credit(self, j: int, reward: float) -> None:
        """Fold a reward into the niche the suite landed in, not the one aimed at."""
        q = self.q_hat(j)
        self.q[j] = q + self.alpha_q * (reward - q)

    def observe_hv(self, hv: float) -> None:
        """Track the best quality seen; this is what opens the size penalty."""
        self.hv_best = max(self.hv_best, hv)

    # ----------------------------------------------------------- persistence
    def to_dict(self) -> dict:
        return {"q": {str(j): v for j, v in self.q.items()},
                "m": {str(k): v for k, v in self.m.items()},
                "hv_best": self.hv_best}

    def load(self, d: dict) -> None:
        self.q = {int(j): v for j, v in d["q"].items()}
        self.m = {int(k): v for k, v in d["m"].items()}
        self.hv_best = d["hv_best"]
