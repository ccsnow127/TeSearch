import math

import pytest

from tesearch.grid import anchor, build
from tesearch.kernel import aim, landing_probs, update_bias


def test_anchor_is_geometric_mean():
    assert anchor([10, 40]) == pytest.approx(20.0)


def test_grid_range_and_ratio():
    g = build(s_min=5, s_bar=20.0, sigma=0.10, gamma=4)
    assert g.bounds[0] == 5
    assert g.bounds[-1] == math.ceil(20.0 * math.exp(0.2) ** 4)
    assert list(g.bounds) == sorted(set(g.bounds))
    # interior boundaries are the lattice s̄·ρ^{i+1/2}, rounded up to sizes
    for i in (-1, 0, 1, 2):
        assert math.ceil(20.0 * math.exp(0.2) ** (i + 0.5)) in g.bounds

def test_grid_centres_anchor():
    g = build(s_min=2, s_bar=50.0, sigma=0.10, gamma=4)
    k = g.niche_of(50)
    assert g.center(k) == pytest.approx(50.0, rel=0.1)
    assert k in g.arms


def test_overflow_niches():
    g = build(s_min=5, s_bar=20.0, sigma=0.10, gamma=4)
    assert g.niche_of(0) == 1 and g.niche_of(4) == 1
    assert g.niche_of(5) == 2
    assert g.niche_of(10_000) == g.K
    assert 1 not in g.arms and g.K not in g.arms
    with pytest.raises(ValueError):
        g.center(1)


def test_grid_nonempty_when_smin_above_anchor():
    g = build(s_min=91, s_bar=30.0, sigma=0.10, gamma=4)
    assert len(list(g.arms)) >= 3


def test_landing_probs_sum_to_one():
    g = build(s_min=3, s_bar=30.0, sigma=0.10, gamma=4)
    for a in (1, 3, 17, 30, 200):
        p = landing_probs(a, 0.05, 0.10, g)
        assert len(p) == g.K
        assert sum(p) == pytest.approx(1.0)
        assert all(x >= 0 for x in p)


def test_aim_inverts_bias():
    assert aim(20.0, 0.0, 2.5) == 20
    assert aim(20.0, math.log(2), 2.5) == 10
    assert aim(20.0, 5.0, 2.5) == 8          # clamped at τ/κ_a


def test_aimed_draw_mostly_lands_on_target():
    g = build(s_min=3, s_bar=30.0, sigma=0.10, gamma=4)
    k = g.niche_of(30)
    p = landing_probs(aim(g.center(k), 0.0, 2.5), 0.0, 0.10, g)
    assert p[k - 1] == max(p)


def test_lms_bias_converges():
    delta = 0.0
    for _ in range(60):
        a = 20
        s = a * math.exp(0.1)
        delta = update_bias(delta, s, a, 0.2)
    assert delta == pytest.approx(0.1, abs=1e-4)
