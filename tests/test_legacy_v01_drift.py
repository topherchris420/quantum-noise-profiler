"""Regression tests for the FROZEN v0.1 decision rules (qnp.legacy.v01_drift).
These pin the baseline behaviour; the v0.2 engine is tested in test_drift_v02.py."""

from datetime import datetime, timedelta, timezone

import numpy as np

from qnp import AlertLevel, Estimate, Metric, Profiler, Provenance  # noqa: F401
from qnp.inferred import FlipTally, flip_estimates
from qnp.legacy.v01_drift import LegacyDriftConfig as DriftConfig
from qnp.legacy.v01_drift import analyze_series
from qnp.stats import beta_interval

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
CTX = "ideal=0|1q<=0|2q<=0"


def flip_series(rates, shots=4000, seed=0, step=timedelta(minutes=10)):
    rng = np.random.default_rng(seed)
    out = []
    for i, p in enumerate(rates):
        k = int(rng.binomial(shots, p))
        out += flip_estimates({(0, CTX): FlipTally(k, shots)}, {}, T0 + i * step, "test")
    return out


def kinds(alerts):
    return sorted((a.kind, a.level.value) for a in alerts)


def test_stable_binomial_series_rarely_alarms():
    cfg = DriftConfig()
    fired = sum(bool(analyze_series(flip_series([0.02] * 12, seed=s), cfg)) for s in range(40))
    assert fired <= 2  # ~5% nominal tail, and the effect-size gate makes it rarer


def test_binomial_step_is_detected():
    alerts = analyze_series(flip_series([0.02] * 8 + [0.03] * 3, seed=1), DriftConfig())
    assert ("drift", "WARNING") in kinds(alerts)


def test_effect_size_gate_blocks_trivial_changes():
    # 2.0% -> 2.1% with 10^6 shots/batch is real but below the 10% effect gate.
    alerts = analyze_series(flip_series([0.020] * 8 + [0.021] * 3, shots=1_000_000, seed=2), DriftConfig())
    assert not [a for a in alerts if a.kind == "drift"]


def test_threshold_breach_is_critical():
    alerts = analyze_series(flip_series([0.02] * 5 + [0.08] * 3, seed=3), DriftConfig())
    assert ("threshold", "CRITICAL") in kinds(alerts)


def test_gradual_trend_produces_forecast_before_threshold():
    rates = np.linspace(0.01, 0.035, 12)  # +0.25%/10 min, threshold 5%
    alerts = analyze_series(flip_series(rates, shots=20_000, seed=4), DriftConfig())
    fc = [a for a in alerts if a.kind == "forecast"]
    assert fc and not [a for a in alerts if a.kind == "threshold"]
    hours = fc[0].details["hours_to_threshold_median"]
    assert 0.3 < hours < 3  # truth: (0.05-0.035)/0.015 per hour = 1.0 h


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
    stable = [_t1(100e-6 * rng.normal(1, 0.03), T0 + timedelta(hours=i)) for i in range(8)]
    assert not analyze_series(stable, DriftConfig(thresholds={}))
    dropped = stable + [_t1(70e-6, T0 + timedelta(hours=8 + i)) for i in range(3)]
    assert ("drift", "WARNING") in kinds(analyze_series(dropped, DriftConfig(thresholds={})))


def test_point_series_uses_baseline_scatter():
    vals = [100, 104, 97, 101, 99, 103]
    es = [
        Estimate(Metric.T1, (0,), Provenance.OBSERVED, T0 + timedelta(hours=i), value=v * 1e-6)
        for i, v in enumerate(vals)
    ]
    cfg = DriftConfig(thresholds={}, recent_batches=1)
    assert not analyze_series(es, cfg)
    es.append(Estimate(Metric.T1, (0,), Provenance.OBSERVED, T0 + timedelta(hours=7), value=60e-6))
    (a,) = analyze_series(es, cfg)
    assert a.kind == "drift" and "predictive_tail_probability" in a.details


def test_provenances_are_separate_series_and_recalibration_resets_baseline():
    prof = Profiler(config=DriftConfig(thresholds={}))
    # Observed T1 is steady at 100us; measured T1 drops. Mixing them would blur both.
    for i in range(8):
        ts = T0 + timedelta(hours=i)
        prof.add(Estimate(Metric.T1, (0,), Provenance.OBSERVED, ts, value=100e-6))
        prof.add(_t1(100e-6 if i < 5 else 60e-6, ts))
    alerts = prof.check()
    assert [a.provenance for a in alerts] == [Provenance.MEASURED]
    prof.mark_recalibrated(T0 + timedelta(hours=4, minutes=30))
    assert not prof.check()  # only 3 post-recal points: no baseline yet


def test_insufficient_estimates_never_alarm():
    es = flip_series([0.02] * 3)
    es += flip_estimates({(0, CTX): FlipTally(40, 50)}, {}, T0 + timedelta(hours=5), "t", min_shots=200)
    assert es[-1].value is None
    assert not analyze_series(es, DriftConfig())


def test_beta_interval_jeffreys():
    m, lo, hi = beta_interval(0, 1000)
    assert lo == 0.0 or lo < 1e-5
    assert 0 < m < hi < 0.004
