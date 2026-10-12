"""Misspecification diagnostics of the decay fits (Phase 4).

The estimator must (a) keep reporting calibrated intervals for data that
follow a single exponential, (b) refuse to report a T1 when the data
contradict that model, and (c) distinguish that case from delays that
simply do not resolve the decay.
"""

import numpy as np
import pytest

from qnp import Status
from qnp.measured import estimate_t1
from qnp.stats import FitDiagnosticsConfig, fit_exponential_decay

T1, E = 100e-6, 0.02


def _fit(curve, delays, rng, shots=1000, **kw):
    return estimate_t1(0, delays, rng.binomial(shots, np.clip(curve, 0, 1)), shots, None, **kw)


def test_valid_single_exponential_is_accepted_with_coverage():
    rng = np.random.default_rng(0)
    delays = np.linspace(0, 3 * T1, 15)
    es = [_fit((1 - 2 * E) * np.exp(-delays / T1) + E, delays, rng) for _ in range(20)]
    ok = [e for e in es if e.status is Status.OK]
    assert len(ok) >= 18  # per-test alphas of 1% each: a few % of valid fits may be rejected
    assert np.mean([e.ci_low <= T1 <= e.ci_high for e in ok]) >= 0.85
    d = ok[0].diagnostics
    assert {"deviance_p", "ppc_p", "runs_test_p", "decay_fraction_spanned", "biexponential", "map"} <= set(d)
    assert d["biexponential"]["tau_fast_map"] <= d["biexponential"]["tau_slow_map"]


def test_fluctuating_t1_is_rejected_as_misspecified_not_estimated():
    rng = np.random.default_rng(1)
    delays = np.linspace(0, 3 * T1, 15)
    rejected = 0
    for _ in range(10):
        t1s = T1 * rng.lognormal(0, 0.3, delays.size)
        e = _fit((1 - 2 * E) * np.exp(-delays / t1s) + E, delays, rng)
        rejected += e.status is Status.MODEL_MISSPECIFICATION
        assert e.value is None or e.status is Status.OK
    assert rejected >= 8


def test_bi_exponential_is_rejected_and_diagnosed_not_replaced():
    rng = np.random.default_rng(2)
    delays = np.linspace(0, 3 * T1, 15)
    curve = (1 - 2 * E) * (0.7 * np.exp(-delays / T1) + 0.3 * np.exp(-delays / 15e-6)) + E
    e = _fit(curve, delays, rng)
    assert e.status is Status.MODEL_MISSPECIFICATION and e.value is None
    codes = {r["code"] for r in e.diagnostics["reasons"]}
    assert "DEVIANCE" in codes or "POSTERIOR_PREDICTIVE" in codes
    bi = e.diagnostics["biexponential"]
    assert bi["log_bf_vs_single"] > 5
    # the alternative model is diagnostic only: no T1 value is reported from it
    assert e.ci_low is None and e.ci_high is None


def test_short_delay_range_is_insufficient_evidence_not_misspecification():
    rng = np.random.default_rng(3)
    delays = np.linspace(0, 0.2 * T1, 15)
    e = _fit((1 - 2 * E) * np.exp(-delays / T1) + E, delays, rng)
    assert e.status is Status.INSUFFICIENT_EVIDENCE
    assert {r["code"] for r in e.diagnostics["reasons"]} & {
        "DELAY_RANGE_COVERAGE",
        "TAU_AT_PRIOR_EDGE",
        "FEW_INFORMATIVE_DELAYS",
    }


def test_tail_only_delays_are_insufficient():
    rng = np.random.default_rng(4)
    delays = np.linspace(5 * T1, 8 * T1, 10)
    e = _fit((1 - 2 * E) * np.exp(-delays / T1) + E, delays, rng)
    assert e.status is not Status.OK


def test_single_glitched_point_is_flagged():
    rng = np.random.default_rng(5)
    delays = np.linspace(0, 3 * T1, 15)
    ones = rng.binomial(1000, (1 - 2 * E) * np.exp(-delays / T1) + E)
    ones[7] = 900  # a readout glitch
    e = estimate_t1(0, delays, ones, 1000, None)
    assert e.status is Status.MODEL_MISSPECIFICATION
    assert 7 in e.diagnostics["suspected_outliers"]


def test_robust_option_is_opt_in_and_reported():
    rng = np.random.default_rng(6)
    delays = np.linspace(0, 3 * T1, 15)
    ones = rng.binomial(1000, (1 - 2 * E) * np.exp(-delays / T1) + E)
    ones[7] = 900
    cfg = FitDiagnosticsConfig(outlier_fraction=0.02)
    fit = fit_exponential_decay(delays, ones, 1000, (0.5, 1.0), (0.0, 0.2), diagnostics=cfg)
    probs = fit.diagnostics["outlier_posterior_probability"]
    assert probs[7] > 0.99 and max(p for i, p in enumerate(probs) if i != 7) < 0.5


def test_diagnostics_can_be_disabled_for_speed():
    rng = np.random.default_rng(7)
    delays = np.linspace(0, 3 * T1, 15)
    e = _fit((1 - 2 * E) * np.exp(-delays / T1) + E, delays, rng, diagnostics=False)
    assert e.status is Status.OK and "deviance_p" not in e.diagnostics


def test_invalid_inputs_fail_explicitly():
    with pytest.raises(ValueError):
        fit_exponential_decay([0, 1e-6, 2e-6], [5, 5, 5], 3, (0.5, 1.0), (0.0, 0.2))
    with pytest.raises(ValueError):
        fit_exponential_decay([0, -1e-6, 2e-6], [1, 1, 1], 3, (0.5, 1.0), (0.0, 0.2))
    # too few delays is a lack of evidence, not malformed input
    fit = fit_exponential_decay([0, 1e-6], [1, 1], 3, (0.5, 1.0), (0.0, 0.2))
    assert not fit.ok and fit.status == "insufficient_evidence" and fit.reasons[0].code == "TOO_FEW_DELAYS"
