"""Numerical checks of the e-process primitives.

1. The closed-form Gaussian regression Bayes factors equal brute-force
   integration over (intercept, slope, scale).
2. Under their nulls, the detectors respect Ville's inequality
   P(sup E >= 1/alpha) <= alpha (small Monte Carlo, loose bound).
3. The detectors respond to the changes they are built for.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy import integrate
from scipy import stats as sps

from qnp.sequential import (
    BinomialChangeDetector,
    BinomialThresholdDetector,
    GaussianChangeDetector,
    GaussianThresholdDetector,
    GaussianTrendDetector,
    gaussian_regression_evalue,
    geometric_log_prior,
)


def _brute_force_bf(y, x, w, g, sign):
    xb = np.sum(w * x) / np.sum(w)
    sxx = np.sum(w * (x - xb) ** 2)

    def loglik(a, b, s2):
        return np.sum(-0.5 * np.log(2 * np.pi * s2 / w) - 0.5 * w * (y - a - b * x) ** 2 / s2)

    def inner_b(a, s2, model):
        if model == 0:
            return np.exp(loglik(a, 0.0, s2))
        lo, hi = {0: (-5, 5), 1: (0, 5), -1: (-5, 0)}[sign]
        f = lambda b: np.exp(loglik(a, b, s2)) * sps.norm.pdf(b, 0, np.sqrt(g * s2 / sxx)) * (2.0 if sign else 1.0)
        return integrate.quad(f, lo, hi, limit=100)[0]

    def marg(model):
        inner_a = lambda s2: integrate.quad(lambda a: inner_b(a, s2, model), -10, 10, limit=100)[0]
        return integrate.quad(lambda ls2: inner_a(np.exp(ls2)), np.log(0.02), np.log(50), limit=100)[0]

    return marg(1) / marg(0)


@pytest.mark.parametrize("sign", [0, 1, -1])
def test_regression_evalue_matches_brute_force_integration(sign):
    rng = np.random.default_rng(0)
    n = 7
    x = np.arange(n, dtype=float)
    w = rng.uniform(0.5, 2, n)
    y = 0.3 + 0.15 * x + rng.normal(0, 1, n) / np.sqrt(w)
    closed = np.exp(gaussian_regression_evalue(y, x, w, 1.3, True, sign).log_e)
    brute = _brute_force_bf(y, x, w, 1.3, sign)
    assert closed == pytest.approx(brute, rel=1e-4)


def test_regression_evalue_rejects_bad_input():
    with pytest.raises(ValueError):
        gaussian_regression_evalue([1, 2, np.nan], [0, 1, 2], [1, 1, 1])
    with pytest.raises(ValueError):
        gaussian_regression_evalue([1, 2, 3], [0, 1, 2], [1, 0, 1])
    ev = gaussian_regression_evalue([1.0, 2.0], [0.0, 1.0], [1.0, 1.0])
    assert ev.log_e == 0.0  # too few points: no evidence either way


def test_geometric_prior_sums_to_one():
    logp, tail = geometric_log_prior(10, 0.1)
    assert np.exp(logp).sum() + np.exp(tail) == pytest.approx(1.0)


def _sup_rate(make, gen, reps, thr):
    hits = 0
    for r in range(reps):
        d = make()
        m = -np.inf
        for row in gen(np.random.default_rng(5000 + r)):
            m = max(m, d.update(*row))
            if m >= np.log(thr):
                hits += 1
                break
    return hits / reps


@pytest.mark.parametrize("p", [0.005, 0.02, 0.1])
def test_binomial_change_detector_rarely_exceeds_under_null(p):
    rate = _sup_rate(
        lambda: BinomialChangeDetector(), lambda g: [(int(g.binomial(2000, p)), 2000) for _ in range(40)], 60, 20.0
    )
    assert rate <= 0.10  # nominal 0.05; loose bound for 60 reps


def test_binomial_threshold_detector_is_valid_at_the_boundary():
    rate = _sup_rate(
        lambda: BinomialThresholdDetector(0.05),
        lambda g: [(int(g.binomial(2000, 0.05)), 2000) for _ in range(40)],
        60,
        20.0,
    )
    assert rate <= 0.10


def test_gaussian_trend_detector_valid_under_null_and_improving_trend():
    assert (
        _sup_rate(lambda: GaussianTrendDetector(), lambda g: [(i, g.normal(), 1.0) for i in range(40)], 80, 20.0)
        <= 0.10
    )
    assert (
        _sup_rate(
            lambda: GaussianTrendDetector(), lambda g: [(i, g.normal(-0.1 * i), 1.0) for i in range(40)], 40, 20.0
        )
        == 0.0
    )


def test_gaussian_change_detector_valid_under_null():
    assert (
        _sup_rate(lambda: GaussianChangeDetector(), lambda g: [(g.normal(), 1.0) for _ in range(30)], 60, 20.0) <= 0.10
    )


def test_gaussian_threshold_detector_valid_on_safe_side():
    assert (
        _sup_rate(
            lambda: GaussianThresholdDetector(0.0, +1), lambda g: [(g.normal(-0.2), 1.0) for _ in range(40)], 60, 20.0
        )
        <= 0.10
    )


def test_binomial_change_detector_detects_a_step():
    rng = np.random.default_rng(1)
    d = BinomialChangeDetector()
    for k in rng.binomial(2000, 0.02, 24):
        d.update(int(k), 2000)
    assert max(d.log_e) < np.log(20)
    for k in rng.binomial(2000, 0.03, 6):
        d.update(int(k), 2000)
    assert d.log_e[-1] >= np.log(20)
    assert d.last["change_time_map"] in range(23, 28)
    assert d.last["delta_posterior_median"] > 0.2


def test_binomial_threshold_detector_detects_exceedance():
    rng = np.random.default_rng(2)
    d = BinomialThresholdDetector(0.05)
    for k in rng.binomial(2000, 0.07, 10):
        d.update(int(k), 2000)
    assert d.log_e[-1] >= np.log(20)


def test_gaussian_trend_detector_detects_worsening_trend():
    rng = np.random.default_rng(3)
    d = GaussianTrendDetector(sign=+1)
    for i in range(20):
        d.update(i, 0.1 * i + rng.normal(0, 0.5), 4.0)
    assert d.log_e[-1] >= np.log(20)


def test_gaussian_change_detector_detects_drop():
    rng = np.random.default_rng(4)
    d = GaussianChangeDetector(sign=-1)
    for v in list(rng.normal(0, 0.03, 10)) + list(rng.normal(-0.3, 0.03, 4)):
        d.update(v, 1.0)
    assert d.log_e[-1] >= np.log(20)
    assert d.last["change_time_map"] == 11


def test_detectors_reject_impossible_counts():
    with pytest.raises(ValueError):
        BinomialChangeDetector().update(5, 3)
    with pytest.raises(ValueError):
        BinomialThresholdDetector(0.05).update(-1, 10)
    with pytest.raises(ValueError):
        BinomialThresholdDetector(1.5)


def test_shared_change_log_terms_shape():
    d = BinomialChangeDetector(min_baseline_batches=2)
    for k in (40, 38, 41, 60, 65):
        d.update(k, 2000)
    s, terms = d.log_terms()
    assert list(s) == [3, 4, 5] and terms.shape == (3, d.n_delta)
