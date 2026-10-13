import numpy as np

from qnp import ForecastStatus
from qnp.forecast import ForecastConfig, forecast_series, runs_test_pvalue


def _rates(rng, p, n=2000):
    k = rng.binomial(n, p)
    y = k / n
    w = 1 / ((k + 0.5) * (n - k + 0.5) / ((n + 1) ** 2 * (n + 2)))
    return y, w


def test_ramp_gives_valid_forecast_with_predictive_interval_covering_truth():
    rng = np.random.default_rng(0)
    t = np.arange(30) / 6
    p = np.linspace(0.02, 0.06, 48)[:30]
    y, w = _rates(rng, p)
    rep = forecast_series(t, y, w, True, 0.05, t[-1], ForecastConfig(), np.log(80))
    assert rep.status is ForecastStatus.VALID_FORECAST and not rep.reasons
    truth = (0.05 - p[-1]) / ((0.06 - 0.02) / 47 * 6)
    c = rep.crossing
    assert c["p10_hours"] <= truth <= c["p90_hours"]
    assert c["includes_process_variation"] and c["process_sd"] >= 0
    assert rep.slope_per_hour > 0


def test_stable_series_is_insufficient_evidence_with_reason():
    rng = np.random.default_rng(1)
    t = np.arange(30) / 6
    y, w = _rates(rng, np.full(30, 0.045))
    rep = forecast_series(t, y, w, True, 0.05, t[-1], ForecastConfig(), np.log(80))
    assert rep.status is ForecastStatus.INSUFFICIENT_EVIDENCE
    assert [r.code for r in rep.reasons] == ["TREND_NOT_SUPPORTED"]
    assert rep.reasons[0].value < rep.reasons[0].limit


def test_step_is_flagged_as_misspecified_not_extrapolated():
    rng = np.random.default_rng(2)
    t = np.arange(30) / 6
    y, w = _rates(rng, np.r_[np.full(15, 0.02), np.full(15, 0.04)])
    rep = forecast_series(t, y, w, True, 0.05, t[-1], ForecastConfig(), np.log(80))
    assert rep.status in (ForecastStatus.MODEL_MISSPECIFICATION, ForecastStatus.UNSTABLE_TREND)
    assert rep.crossing is None


def test_curvature_is_flagged():
    rng = np.random.default_rng(3)
    t = np.arange(30) / 6
    y, w = _rates(rng, 0.02 + 0.00004 * np.arange(30) ** 2, n=20_000)
    rep = forecast_series(t, y, w, True, 0.05, t[-1], ForecastConfig(), np.log(80))
    assert rep.status is ForecastStatus.MODEL_MISSPECIFICATION
    assert "CURVATURE" in [r.code for r in rep.reasons]


def test_short_history_and_unsupported_horizon():
    rng = np.random.default_rng(4)
    t = np.arange(4) / 6
    y, w = _rates(rng, np.full(4, 0.02))
    rep = forecast_series(t, y, w, True, 0.05, t[-1], ForecastConfig(), np.log(80))
    assert rep.status is ForecastStatus.INSUFFICIENT_HISTORY
    assert {r.code for r in rep.reasons} == {"TOO_FEW_POINTS", "SPAN_TOO_SHORT"}
    # slow ramp: strong trend evidence, but the crossing lies far beyond the data span
    t = np.arange(40) / 6
    y, w = _rates(rng, np.linspace(0.020, 0.024, 40), n=200_000)
    rep = forecast_series(t, y, w, True, 0.05, t[-1], ForecastConfig(), np.log(80))
    assert rep.status is ForecastStatus.UNSUPPORTED_HORIZON
    assert rep.reasons[0].code == "BEYOND_EXTRAPOLATION_CAP" and rep.crossing["p_within_horizon"] < 0.05


def test_runs_test():
    assert runs_test_pvalue(np.array([1, 1, 1, 1, -1, -1, -1, -1, 1, 1, 1, 1, -1, -1, -1, -1])) < 0.05
    assert runs_test_pvalue(np.array([1, -1] * 8)) < 0.05
    assert runs_test_pvalue(np.array([1, 1, -1, 1, -1, -1, 1, -1, 1, 1, -1, -1])) > 0.2
