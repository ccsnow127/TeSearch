"""Predicting what size the model will actually write.

Asking for a suite of exactly n tests does not reliably produce n tests, and the
error scales with the request rather than being a fixed number of tests. The
realized size is therefore modelled in log space as

    ln(realized) = ln(requested) + delta + noise,   noise ~ N(0, sigma**2)

delta is a per-module offset learned during the run; sigma is a fixed constant.
Two things are built on this: the request to send so that the result lands where
we want it, and the spread of niches a call might land in.
"""
from __future__ import annotations

import math

from .grid import Grid


def _phi(x: float) -> float:
    """Standard normal CDF."""
    if x == math.inf:
        return 1.0
    if x == -math.inf:
        return 0.0
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def aim(tau: float, delta: float, kappa_a: float) -> int:
    """The size to request so the result is expected to land on tau.

    The current bias is taken out of the request, which is then held within a
    factor of kappa_a of the target so a large bias estimate cannot send the
    request somewhere absurd, and rounded to a whole number of tests.
    """
    a = math.exp(math.log(tau) - delta)
    a = min(max(a, tau / kappa_a), tau * kappa_a)
    return max(1, round(a))


def landing_probs(a: float, delta: float, sigma: float, grid: Grid) -> list[float]:
    """Probability of landing in each niche when requesting size ``a``.

    Returned in niche order, so index j-1 holds niche j. The outer niches are
    open at 0 and infinity, so the probabilities always sum to one.
    """
    mu = math.log(a) + delta

    def cdf(b: float) -> float:
        if b <= 0:
            return 0.0
        if b == math.inf:
            return 1.0
        return _phi((math.log(b) - mu) / sigma)

    return [cdf(grid.upper(j)) - cdf(grid.lower(j)) for j in range(1, grid.K + 1)]


def update_bias(delta: float, s: int, a: int, eta: float) -> float:
    """Fold one observation into the bias estimate, decaying older ones."""
    return (1.0 - eta) * delta + eta * (math.log(s) - math.log(a))
