"""Picking the two suites shown as examples in a generation prompt, and how they
are ordered and labelled."""
from __future__ import annotations

import math

from .archive import Suite

COMPRESS = "compress"
EXPAND = "expand"


def _distance(s: Suite, tau: float) -> float:
    return abs(math.log(s.size) - math.log(tau))


def _nearest(pool: list[Suite], tau: float, n: int) -> list[Suite]:
    """The n suites closest to the target size; better quality breaks a tie."""
    return sorted(pool, key=lambda s: (_distance(s, tau), -s.hv, s.size, s.uid))[:n]


def select_parents(pool: list[Suite], tau: float) -> list[Suite]:
    """One parent from below the target size and one from above it.

    The pool is every front member in the archive rather than only the target
    niche, because the niche being aimed at is often still empty and would
    otherwise have nothing to breed from. When one side is empty, both parents
    come from the other side.
    """
    below = [s for s in pool if s.size < tau]
    above = [s for s in pool if s.size >= tau]
    if below and above:
        return _nearest(below, tau, 1) + _nearest(above, tau, 1)
    return _nearest(below or above, tau, 2)


def order(parents: list[Suite]) -> list[Suite]:
    """Weakest first, so the strongest example sits last in the prompt.

    Ranked by quality, and by smaller size when quality is equal.
    """
    return sorted(parents, key=lambda s: (s.hv, -s.size, s.uid))


def mode(last: Suite, tau: float) -> str:
    """Whether the call has to shrink the strongest example or grow it."""
    return COMPRESS if tau < last.size else EXPAND


def comparison_note(prev: Suite, curr: Suite) -> str:
    """One line telling the model how the second example compares to the first.

    Both changes are stated with their measured numbers, so the note is never a
    claim the numbers do not support. A version that is no worse in quality and
    smaller is called out as the stronger kind of improvement.
    """
    if curr.hv > prev.hv:
        hv_part = f"hypervolume grow {prev.hv:.3f}->{curr.hv:.3f}"
    elif curr.hv == prev.hv:
        hv_part = f"hypervolume hold {curr.hv:.3f}"
    else:
        hv_part = f"hypervolume decline {prev.hv:.3f}->{curr.hv:.3f}"
    if curr.size < prev.size:
        size_part = f"size decline {prev.size}->{curr.size}"
    elif curr.size > prev.size:
        size_part = f"size grow {prev.size}->{curr.size}"
    else:
        size_part = f"size hold {curr.size}"
    perfect = curr.hv >= prev.hv and curr.size < prev.size
    head = "perfect improved version of prev" if perfect else "improved version of prev"
    return f"{head} ({hv_part}, {size_part})"


def annotations(ordered: list[Suite]) -> list[str | None]:
    """No note on the first example; every later one is compared to its predecessor."""
    return [None] + [comparison_note(a, b) for a, b in zip(ordered, ordered[1:])]
