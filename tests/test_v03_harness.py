"""The v0.3 experiment harness: exactness of post-hoc threshold rescaling with
several metrics per qubit, and the closed-loop operational simulator."""

import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

from v03.harness import EngineSpec3, first_true, group_alarms, qubit_alarms, run_engine3
from v03.operational import (
    BATCH_MIN,
    THRESHOLD,
    ChartMonitor,
    OpsScenario,
    OracleMonitor,
    Policy,
    frontier_at,
    inverse_frontier_at,
    make_world,
    simulate,
    true_error,
)

from qnp.inferred import FlipTally, flip_estimates
from qnp.measured import estimate_readout


def _stream(n=30, step_at=15, seed=0):
    from v02.harness import T0

    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        ts = T0 + i * timedelta(minutes=10)
        es = []
        for q in (0, 1):
            p_ro = 0.03 if (q == 0 and i >= step_at) else 0.02
            for prep in (0, 1):
                es.append(estimate_readout(q, prep, int(rng.binomial(2000, p_ro)), 2000, ts))
            for ctx, p in (("ideal=0|ops=a|idle=0", 0.025), ("ideal=1|ops=b|idle=0", 0.04)):
                p_eff = p * (1.5 if (q == 0 and i >= step_at) else 1.0)
                es += flip_estimates({(q, ctx): FlipTally(int(rng.binomial(2000, p_eff)), 2000)}, {}, ts, "t")
        out.append((i, ts, es))
    return out


@pytest.mark.parametrize("arch, n_metrics", [("v03", 2), ("v02", 1)])
def test_posthoc_rescaling_reproduces_a_direct_run(arch, n_metrics):
    stream = _stream()
    if arch == "v02":  # the v0.2 architecture sees every circuit as an effective flip rate
        stream = [(i, ts, [e for e in es if e.metric.value == "effective_flip_rate"]) for i, ts, es in stream]
    rec0 = run_engine3(stream, EngineSpec3("c0", arch, n_metrics=n_metrics))
    c = 2.0
    rec_c = run_engine3(stream, EngineSpec3("c2", arch, n_metrics=n_metrics, log_e_offset=c))
    for q in (0, 1):
        direct = [any(a[0] == i and a[1].startswith(f"{q}:") for a in rec_c["alerts"]) for i in rec_c["i"]]
        assert qubit_alarms(rec0, q, c) == direct
        own = [any(a[0] == i and a[1].startswith(f"{q}:") for a in rec0["alerts"]) for i in rec0["i"]]
        assert qubit_alarms(rec0, q, 0.0) == own
    assert first_true(qubit_alarms(rec0, 0, c), rec0["i"], 15) is not None  # the step is seen
    if arch == "v03":
        assert set(rec0["g"]) == {f"{q}:{m}" for q in (0, 1) for m in ("effective_flip_rate", "readout_error")}
        assert all(t is None for t in rec0["g"]["0:effective_flip_rate"]["t"])  # no absolute threshold
        assert len(group_alarms(rec0, "9:readout_error", c)) == len(rec0["i"])


def _scenario(**kw):
    return OpsScenario("test", **{"drift_per_day": 0.5, "jump_per_day": 0.5, **kw})


def test_world_is_reproducible_and_events_clear_at_calibration():
    w1, w2 = make_world(_scenario(), 288, 5), make_world(_scenario(), 288, 5)
    assert w1.events == w2.events and np.array_equal(w1.fluct, w2.fluct)
    from v03.operational import World

    flat = np.ones((2, 100))
    bases = [np.full(102, 0.02), np.full(102, 0.02)]
    w = World(100, 0, [[(10, "drift", 0.006), (40, "jump", 2.0)], []], bases, flat)
    assert true_error(w, 0, 9, 0, 0) == pytest.approx(0.02)  # before any event
    assert true_error(w, 0, 20, 0, 0) == pytest.approx(0.02 + 0.006 * 10 * 10 / 60)  # ramp: 0.6%/h for 100 min
    assert true_error(w, 0, 50, 0, 0) == pytest.approx((0.02 + 0.006 * 40 * 10 / 60) * 2.0)
    assert true_error(w, 0, 50, 45, 1) == pytest.approx(0.02)  # a calibration at batch 45 cleared both
    assert true_error(w, 0, 50, 20, 1) == pytest.approx(0.04)  # cleared the ramp only; the jump came later
    assert true_error(w, 1, 50, 0, 0) == pytest.approx(0.02)


def test_policies_on_a_world():
    w = make_world(_scenario(), 3 * 144, 11)
    fixed24 = simulate(Policy("fixed24"), w)
    none = simulate(Policy("none", schedule_hours=None), w)
    oracle = simulate(Policy("oracle", OracleMonitor), w)
    fixed4 = simulate(Policy("fixed4", schedule_hours=4.0), w)
    assert none.calibrations == 0 and fixed24.calibrations == fixed24.scheduled == 2 * 2  # 2 qubits, days 1 and 2
    assert fixed4.calibrations > fixed24.calibrations
    assert oracle.failed <= fixed24.failed <= none.failed
    assert oracle.triggered == oracle.triggered_above
    assert fixed24.jobs + fixed24.downtime == 2 * 3 * 144
    cusum = simulate(Policy("cusum", lambda: ChartMonitor("cusum", 10.0)), w)
    assert cusum.calibrations == cusum.scheduled + cusum.triggered
    assert simulate(Policy("fixed24"), w).to_dict() == fixed24.to_dict()  # deterministic


def test_stable_world_never_fails():
    w = make_world(OpsScenario("stable", 0.0, 0.0), 2 * 144, 3)
    assert all(not ev for ev in w.events)
    out = simulate(Policy("fixed24"), w)
    assert out.failed == 0 and THRESHOLD == 0.05 and BATCH_MIN == 10.0


def test_frontier_interpolation():
    pts = [(0.0, 0.20), (1.0, 0.10), (6.0, 0.01)]
    assert frontier_at(pts, 0.5) == pytest.approx(0.15)
    assert frontier_at(pts, 7.0) is None
    assert inverse_frontier_at(pts, 0.10) == pytest.approx(1.0)
    assert inverse_frontier_at(pts, 0.5) is None
