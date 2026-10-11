import pytest

from tesearch.archive import Archive, Suite, front_hv
from tesearch.grid import build
from tesearch.ucb import SizeUCB


def S(uid, size, cov, mut):
    return Suite(uid=uid, src="", size=size, cov=cov, mut=mut, pass_rate=1.0,
                 green_size=size, loc=size)


def test_front_hv_staircase():
    assert front_hv([S(0, 5, 1.0, 0.5), S(1, 5, 0.5, 1.0)]) == pytest.approx(0.75)
    assert front_hv([S(0, 5, 0.8, 0.9)]) == pytest.approx(0.72)
    assert front_hv([]) == 0.0


def test_filing_rewards_and_dominance():
    a = Archive()
    a.grid = build(s_min=2, s_bar=20.0, sigma=0.10, gamma=4)
    j, d = a.file(S(0, 20, 0.5, 0.5))
    assert d == pytest.approx(0.25)
    j2, d2 = a.file(S(1, 20, 0.4, 0.4))          # dominated
    assert (j2, d2) == (j, 0.0)
    j3, d3 = a.file(S(2, 20, 0.6, 0.5))          # dominates the first
    assert d3 == pytest.approx(0.05)
    assert [s.uid for s in a.fronts[j]] == [2]
    a.file(S(3, 200, 0.1, 0.1))                  # another niche
    assert a.moqd() == pytest.approx(0.30 + 0.01)


def test_regrid_files_provisional_seeds():
    a = Archive()
    a.file(S(0, 20, 0.5, 0.5))
    a.file(S(1, 20, 0.4, 0.4))
    assert a.grid is None and len(a.provisional) == 2
    out = a.regrid(build(s_min=2, s_bar=20.0, sigma=0.10, gamma=4))
    assert [d for _, _, d in out] == [pytest.approx(0.25), 0.0]
    assert len(a.members()) == 1


def test_lambda_gate():
    g = build(s_min=2, s_bar=20.0, sigma=0.10, gamma=4)
    u = SizeUCB(g, alpha_q=0.3, c_e=0.5, H=0.85)
    u.observe_hv(0.80)
    assert u.lam() == 0.0
    u.observe_hv(0.95)
    assert u.lam() == pytest.approx(0.10)
    u.observe_hv(0.90)                           # running maximum
    assert u.lam() == pytest.approx(0.10)


def test_q_hat_and_counts():
    g = build(s_min=2, s_bar=20.0, sigma=0.10, gamma=4)
    u = SizeUCB(g, alpha_q=0.5, c_e=0.5, H=0.85)
    assert u.q_hat(3) == 0.0
    u.credit(3, 0.4)
    assert u.q_hat(3) == pytest.approx(0.2)
    assert u.q_hat(5) == pytest.approx(0.2)      # unseen: mean of observed
    u.charge(4)
    u.charge(4)
    assert u.m[4] == 2


def test_select_prefers_value_and_penalises_size_under_pressure():
    g = build(s_min=2, s_bar=20.0, sigma=0.10, gamma=4)
    u = SizeUCB(g, alpha_q=1.0, c_e=0.0, H=0.5)
    small, large = 3, g.K - 1
    one_hot = lambda j: [1.0 if i == j else 0.0 for i in range(1, g.K + 1)]
    u.credit(small, 0.1)
    u.credit(large, 0.1)
    k, _ = u.select({small: one_hot(small), large: one_hot(large)})
    assert k == small                            # tie -> smaller niche
    u.observe_hv(0.9)                            # λ = 0.4 > 0
    u.credit(large, 0.3)
    k, _ = u.select({small: one_hot(small), large: one_hot(large)})
    assert k == small                            # 0.3 − 0.4·z_large < 0.1 − 0.4·z_small
