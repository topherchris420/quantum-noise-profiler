"""Behavioural tests of the v0.2 sequential engine through the public API."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from qnp import (
    V02_THRESHOLDS,
    AlertLevel,
    DriftConfig,
    ErrorBudget,
    Estimate,
    ForecastStatus,
    Metric,
    Profiler,
    Provenance,
    Status,
)
from qnp.drift import analyze_series
from qnp.inferred import FlipTally, flip_estimates
from qnp.measured import estimate_readout

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
CTX0 = "ideal=0|1q<=0|2q<=0"
CTX1 = "ideal=1|1q<=0|2q<=0"
P10 = "p(1|0)"


def flip_series(rates, shots=4000, seed=0, step=timedelta(minutes=10), ctx=CTX0, qubit=0):
    rng = np.random.default_rng(seed)
    out = []
    for i, p in enumerate(rates):
        k = int(rng.binomial(shots, p))
        out += flip_estimates({(qubit, ctx): FlipTally(k, shots)}, {}, T0 + i * step, "test")
    return out


def readout_series(rates, shots=4000, seed=0, step=timedelta(minutes=10), prepared=0, qubit=0):
    """MEASURED readout_error from readout probes: the series v0.3 thresholds apply to."""
    rng = np.random.default_rng(seed)
    return [
        estimate_readout(qubit, prepared, int(rng.binomial(shots, p)), shots, T0 + i * step)
        for i, p in enumerate(rates)
    ]


def kinds(alerts):
    return sorted((a.kind, a.level.value) for a in alerts)


def test_stable_series_rarely_alarms_over_a_whole_session():
    cfg = DriftConfig()
    fired = 0
    for s in range(30):
        es = flip_series([0.02] * 48, seed=s)
        states: dict = {}
        if any(analyze_series(es[:n], cfg, states=states) for n in range(1, 49)):
            fired += 1
    assert fired <= 3  # budget 10% over the session; the bound is loose for 30 runs


def test_step_is_detected_with_evidence_details():
    es = flip_series([0.02] * 24 + [0.03] * 6, seed=1)
    alerts = analyze_series(es, DriftConfig())
    drift = [a for a in alerts if a.kind == "drift"]
    assert drift and drift[0].level is AlertLevel.WARNING
    d = drift[0].details
    assert d["e_value"] >= d["e_threshold"] and d["guarantee"] == "bayesian_marginal"
    assert d["alpha_series"] == pytest.approx(0.05)
    assert d["batches_since_change"] >= 2 and d["probability"] >= 0.5


def test_single_outlier_batch_does_not_alarm():
    es = flip_series([0.02] * 20 + [0.05] + [0.02] * 3, seed=2)
    assert not [a for a in analyze_series(es, DriftConfig()) if a.kind == "drift"]


def test_effect_size_gate_blocks_trivial_changes():
    es = flip_series([0.020] * 12 + [0.021] * 12, shots=1_000_000, seed=3)
    assert not [a for a in analyze_series(es, DriftConfig()) if a.kind == "drift"]


def test_threshold_breach_is_critical_and_exact():
    es = readout_series([0.02] * 6 + [0.09] * 6, seed=4)
    alerts = analyze_series(es, DriftConfig())
    thr = [a for a in alerts if a.kind == "threshold"]
    assert thr and thr[0].level is AlertLevel.CRITICAL and thr[0].details["guarantee"] == "exact"


def test_just_below_threshold_does_not_trip_threshold_channel():
    cfg = DriftConfig()
    fired = 0
    for s in range(20):
        es = readout_series([0.045] * 48, seed=100 + s)
        states: dict = {}
        if any(a.kind == "threshold" for n in range(1, 49) for a in analyze_series(es[:n], cfg, states=states)):
            fired += 1
    assert fired <= 2


def test_workload_dependent_rates_get_no_absolute_threshold_by_default():
    """v0.2 Experiment E5/E6: a workload whose effective flip rate is above 5%
    on unchanged hardware raised CRITICAL alerts. v0.3 monitors such rates for
    relative change only, says why, and reproduces v0.2 on request."""
    es = flip_series([0.09] * 12, seed=4)
    prof = Profiler()
    prof.add(es)
    (rep,) = prof.reports()
    assert rep.threshold["threshold"] is None and "workload" in rep.threshold["note"]
    assert not rep.alerts
    v02 = analyze_series(es, DriftConfig(thresholds=dict(V02_THRESHOLDS)))
    assert [a.kind for a in v02 if a.level is AlertLevel.CRITICAL] == ["threshold"]
    assert V02_THRESHOLDS == {Metric.EFFECTIVE_FLIP: 0.05, Metric.READOUT_ERROR: 0.05}


def test_forecast_on_ramp_has_predictive_interval_and_statuses():
    rates = np.linspace(0.02, 0.045, 30)
    prof = Profiler(config=DriftConfig(budget=ErrorBudget(n_qubits=1, n_metrics=1)))
    prof.add(readout_series(rates, shots=20_000, seed=5))
    alerts = prof.check()
    fc = [a for a in alerts if a.kind == "forecast"]
    assert fc, [a.message for a in alerts]
    d = fc[0].details
    assert (
        d["includes_process_variation"]
        and d["hours_to_threshold_p10"] <= d["hours_to_threshold_median"] <= d["hours_to_threshold_p90"]
    )
    truth_h = (0.05 - rates[-1]) / ((rates[1] - rates[0]) * 6)
    # an 80% interval may miss the truth 20% of the time; check the median and width instead
    assert abs(d["hours_to_threshold_median"] - truth_h) < 0.25
    assert 0 < d["hours_to_threshold_p90"] - d["hours_to_threshold_p10"] < 1.0
    (rep,) = prof.report()
    assert rep["forecast"]["per_context"][P10]["status"] == ForecastStatus.VALID_FORECAST.value
    assert rep["provenance"] == "measured" and rep["metric"] == "readout_error"


def test_rejected_forecasts_carry_machine_readable_reasons():
    prof = Profiler(config=DriftConfig())
    prof.add(flip_series([0.03] * 4, seed=6))
    (rep,) = prof.report()
    fc = rep["forecast"]["per_context"][CTX0]
    assert fc["status"] == "INSUFFICIENT_HISTORY"
    assert {r["code"] for r in fc["reasons"]} == {"TOO_FEW_POINTS", "SPAN_TOO_SHORT"}
    prof.add(flip_series([0.03] * 20, seed=6)[4:])
    (rep,) = prof.report()
    fc = rep["forecast"]["per_context"][CTX0]
    assert fc["status"] == "INSUFFICIENT_EVIDENCE" and fc["reasons"][0]["code"] == "TREND_NOT_SUPPORTED"


def test_contexts_are_combined_and_family_budget_is_explicit():
    prof = Profiler(config=DriftConfig(budget=ErrorBudget(alpha_session=0.10)))
    prof.add(flip_series([0.02] * 24 + [0.028] * 8, seed=7, ctx=CTX0))
    prof.add(flip_series([0.02] * 24 + [0.028] * 8, seed=8, ctx=CTX1))
    prof.add(flip_series([0.02] * 32, seed=9, ctx=CTX0, qubit=1))
    reps = prof.reports()
    assert prof.family["n_qubits"] == 2 and prof.family["n_metrics"] == 1
    q0 = [r for r in reps if r.qubits == (0,)][0]
    assert q0.contexts == [CTX0, CTX1]
    assert q0.alpha["drift"] == pytest.approx(0.10 * 0.5 / 2)
    assert q0.drift["log_e_shared"] is not None and q0.drift["log_e"] >= q0.drift["log_e_threshold"]
    assert all(a.qubits == (0,) for a in prof.check())


def test_family_growth_is_reported():
    prof = Profiler(config=DriftConfig())
    prof.add(flip_series([0.02] * 5, seed=10))
    prof.check()
    prof.add(flip_series([0.02] * 5, seed=11, qubit=1))
    prof.check()
    assert prof.family["exceeded"] and prof.notices


def _t1(value, ts, rel_width=0.1, prov=Provenance.MEASURED):
    return Estimate(
        Metric.T1,
        (0,),
        prov,
        ts,
        value=value,
        ci_low=value * (1 - rel_width),
        ci_high=value * (1 + rel_width),
        ci_level=0.95,
    )


def test_interval_series_detects_t1_drop_not_noise():
    rng = np.random.default_rng(5)
    stable = [_t1(100e-6 * rng.normal(1, 0.03), T0 + timedelta(hours=i)) for i in range(10)]
    assert not analyze_series(stable, DriftConfig(thresholds={}))
    dropped = stable + [_t1(60e-6, T0 + timedelta(hours=10 + i)) for i in range(4)]
    alerts = analyze_series(dropped, DriftConfig(thresholds={}))
    assert ("drift", "WARNING") in kinds(alerts) and alerts[0].details["guarantee"] == "exact"


def test_point_series_uses_plug_in_scatter_and_says_so():
    vals = [100, 104, 97, 101, 99, 103, 98, 102]
    es = [
        Estimate(Metric.T1, (0,), Provenance.OBSERVED, T0 + timedelta(hours=i), value=v * 1e-6)
        for i, v in enumerate(vals)
    ]
    cfg = DriftConfig(thresholds={Metric.T1: 80e-6})
    assert not analyze_series(es, cfg)
    es += [Estimate(Metric.T1, (0,), Provenance.OBSERVED, T0 + timedelta(hours=8 + i), value=60e-6) for i in range(4)]
    alerts = analyze_series(es, cfg)
    assert alerts and {a.kind for a in alerts} <= {"drift", "threshold"}
    thr = [a for a in alerts if a.kind == "threshold"]
    assert thr and thr[0].details["guarantee"] == "plug_in"


def test_provenances_are_separate_series_and_recalibration_resets_baseline():
    prof = Profiler(config=DriftConfig(thresholds={}))
    for i in range(12):
        ts = T0 + timedelta(hours=i)
        prof.add(Estimate(Metric.T1, (0,), Provenance.OBSERVED, ts, value=100e-6))
        prof.add(_t1(100e-6 if i < 8 else 60e-6, ts))
    alerts = prof.check()
    assert alerts and {a.provenance for a in alerts} == {Provenance.MEASURED}
    prof.mark_recalibrated(T0 + timedelta(hours=7, minutes=30))
    assert not prof.check()  # only post-recalibration points: no baseline yet


def test_insufficient_estimates_never_alarm_and_duplicates_fail_explicitly():
    es = flip_series([0.02] * 3)
    es += flip_estimates({(0, CTX0): FlipTally(40, 50)}, {}, T0 + timedelta(hours=5), "t", min_shots=200)
    assert es[-1].status is Status.INSUFFICIENT_EVIDENCE
    assert not analyze_series(es, DriftConfig())
    dup = flip_series([0.02] * 3) + flip_series([0.02] * 3)
    with pytest.raises(ValueError, match="duplicate observation"):
        analyze_series(dup, DriftConfig())


def test_legacy_engine_still_available_through_profiler():
    from qnp import LegacyDriftConfig

    prof = Profiler(config=LegacyDriftConfig())
    prof.add(flip_series([0.02] * 8 + [0.03] * 3, seed=1))
    assert ("drift", "WARNING") in kinds(prof.check())
    with pytest.raises(TypeError):
        prof.report()


def test_budget_validation():
    with pytest.raises(ValueError):
        ErrorBudget(alpha_session=1.5)
    with pytest.raises(ValueError):
        ErrorBudget(shares={"drift": 0.5, "threshold": 0.5})
    with pytest.raises(ValueError):
        DriftConfig(combine_contexts="product")


def test_each_provenance_counts_in_the_family_budget():
    """Observed and measured T1 of one qubit are two tests of one quantity:
    the per-group alpha must be halved, not granted twice (review finding)."""
    prof = Profiler(config=DriftConfig(thresholds={}))
    for i in range(6):
        ts = T0 + timedelta(hours=i)
        prof.add(Estimate(Metric.T1, (0,), Provenance.OBSERVED, ts, value=100e-6))
        prof.add(_t1(100e-6, ts))
    reps = prof.reports()
    assert prof.family["n_provenances"] == 2
    assert all(r.alpha["drift"] == pytest.approx(0.10 * 0.5 / 2) for r in reps)
    single = Profiler(config=DriftConfig(thresholds={}))
    single.add([_t1(100e-6, T0 + timedelta(hours=i)) for i in range(6)])
    (r1,) = single.reports()
    assert r1.alpha["drift"] == pytest.approx(0.10 * 0.5)


def test_zero_share_disables_a_channel_instead_of_crashing():
    cfg = DriftConfig(budget=ErrorBudget(shares={"drift": 0.75, "threshold": 0.25, "forecast": 0.0}))
    prof = Profiler(config=cfg)
    prof.add(readout_series(np.linspace(0.02, 0.045, 30), shots=20_000, seed=5))
    (rep,) = prof.reports()
    assert rep.alpha["forecast"] == 0 and rep.forecast["log_e_threshold"] == float("inf")
    assert not [a for a in rep.alerts if a.kind == "forecast"]
    assert all(v["status"] != "VALID_FORECAST" for v in rep.forecast["per_context"].values())


def test_constant_vendor_series_reports_instead_of_crashing():
    """A vendor value re-read unchanged at every snapshot has zero variation."""
    prof = Profiler(config=DriftConfig(thresholds={Metric.T1: 80e-6}))
    prof.add([Estimate(Metric.T1, (0,), Provenance.OBSERVED, T0 + timedelta(hours=i), value=100e-6) for i in range(8)])
    (rep,) = prof.reports()
    (fc,) = rep.forecast["per_context"].values()
    assert fc["status"] == "INSUFFICIENT_EVIDENCE" and fc["reasons"][0]["code"] == "NO_VARIATION"
    assert not rep.alerts
