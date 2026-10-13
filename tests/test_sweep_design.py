"""Decay sweeps that can see measurement drift: random acquisition order and
interleaved ground references (v0.3; v0.2 Experiment D11)."""

from datetime import datetime, timezone

import numpy as np
import pytest

from qnp import Status
from qnp.measured import (
    V02_SWEEP,
    DecaySweepPlan,
    decay_plan_circuits,
    decay_sweep_plan,
    estimate_t1,
    estimate_t1_from_plan,
)
from qnp.stats import SweepReferences, reference_homogeneity

TS = datetime(2026, 10, 1, tzinfo=timezone.utc)
T1, E, SHOTS = 100e-6, 0.02, 1000
DELAYS = np.linspace(0, 3 * T1, 15)


def _simulate(plan, rng, offset=None):
    """Counts of outcome 1 per acquired circuit; ``offset[j]`` is added to P(1) of slot j."""
    p = []
    for j, (what, i) in enumerate(plan.slots):
        base = E if what == "reference" else (1 - 2 * E) * np.exp(-plan.delays_s[i] / T1) + E
        p.append(base + (0.0 if offset is None else offset[j]))
    return rng.binomial(SHOTS, np.clip(p, 0, 1))


def test_plan_layout_and_validation():
    plan = decay_sweep_plan(DELAYS, seed=3)
    assert len(plan.slots) == 20 and plan.n_references == 5 and plan.randomized
    assert plan.reference_positions() == (0, 5, 10, 14, 19)
    assert sorted(plan.delay_positions()) == sorted(set(range(20)) - set(plan.reference_positions()))
    assert decay_sweep_plan(DELAYS, seed=3) == plan  # reproducible
    v02 = decay_sweep_plan(DELAYS, **V02_SWEEP)
    assert v02.slots == tuple(("delay", i) for i in range(15)) and not v02.randomized
    for bad in ({"n_references": 1}, {"n_references": -2}):
        with pytest.raises(ValueError):
            decay_sweep_plan(DELAYS, **bad)
    with pytest.raises(ValueError, match="at least 3"):
        decay_sweep_plan([0, 1e-6])
    with pytest.raises(ValueError):
        DecaySweepPlan((0.0, 1.0, 2.0), (("delay", 0), ("delay", 0), ("delay", 2)))
    assert plan.to_dict()["n_references"] == 5


def test_plan_circuits_follow_the_acquisition_order():
    plan = decay_sweep_plan(DELAYS, seed=4)
    circs = decay_plan_circuits(plan, "t1")
    assert len(circs) == 20
    for j, (c, (what, i)) in enumerate(zip(circs, plan.slots)):
        assert c.metadata["slot"] == j and c.metadata["index"] == i
        names = [inst.operation.name for inst in c.data]
        if what == "reference":
            assert names == ["measure"] and c.metadata["qnp"] == "reference"
        else:
            assert names == ["x", "delay", "measure"] and c.metadata["delay_s"] == pytest.approx(plan.delays_s[i])
    assert [c.data[1].operation.name for c in decay_plan_circuits(plan, "t2_echo") if c.metadata["qnp"] != "reference"][
        0
    ] == "delay"
    with pytest.raises(ValueError):
        decay_plan_circuits(plan, "ramsey")


def test_reference_homogeneity_test():
    stat, p, dof = reference_homogeneity([20, 22, 19, 21, 18], [1000] * 5)
    assert dof == 4 and p > 0.5
    stat, p, dof = reference_homogeneity([10, 15, 20, 30, 40], [1000] * 5)
    assert p < 1e-4 and stat / dof > 6
    assert reference_homogeneity([20], [1000]) == (0.0, 1.0, 0)
    with pytest.raises(ValueError):
        SweepReferences((0, 1), (5, 2000), (1000, 1000))


def test_valid_sweep_is_accepted_and_records_the_design():
    rng = np.random.default_rng(10)
    plan = decay_sweep_plan(DELAYS, seed=10)
    e = estimate_t1_from_plan(0, plan, _simulate(plan, rng), SHOTS, TS)
    assert e.status is Status.OK and e.ci_low <= T1 <= e.ci_high
    d = e.diagnostics
    assert d["acquisition_order"] == "not monotone in delay" and "order_note" not in d
    assert d["references"]["n"] == 5 and d["references"]["p"] > 0.01
    assert "acquisition_runs_test_p" in d and d["sweep_plan"]["n_references"] == 5


def test_drifting_readout_is_refused_with_the_interleaved_design():
    """A linear readout offset along the acquisition (v0.2 D11-type drift)."""
    rng = np.random.default_rng(11)
    plan = decay_sweep_plan(DELAYS, seed=11)
    ones = _simulate(plan, rng, offset=np.linspace(-0.015, 0.015, len(plan.slots)))
    e = estimate_t1_from_plan(0, plan, ones, SHOTS, TS)
    assert e.status is Status.MODEL_MISSPECIFICATION and e.value is None
    assert "READOUT_DRIFT" in {r["code"] for r in e.diagnostics["reasons"]}


def test_sequential_design_cannot_see_the_same_drift_and_says_so():
    """The v0.2 design: the same drift bends the curve and is absorbed by the
    fit; the estimate carries a note that drift is undetectable."""
    rng = np.random.default_rng(11)
    plan = decay_sweep_plan(DELAYS, **V02_SWEEP)
    ones = _simulate(plan, rng, offset=np.linspace(-0.015, 0.015, len(plan.slots)))
    e = estimate_t1_from_plan(0, plan, ones, SHOTS, TS)
    assert e.diagnostics["acquisition_order"] == "monotone in delay"
    assert "cannot be detected" in e.diagnostics["order_note"]
    assert "READOUT_DRIFT" not in {r["code"] for r in e.diagnostics.get("reasons", [])}


def test_estimate_t1_without_acquisition_information_notes_the_limitation():
    rng = np.random.default_rng(12)
    ones = rng.binomial(SHOTS, (1 - 2 * E) * np.exp(-DELAYS / T1) + E)
    e = estimate_t1(0, DELAYS, ones, SHOTS, TS)
    assert e.diagnostics["acquisition_order"] == "not supplied" and "order_note" in e.diagnostics
    with pytest.raises(ValueError, match="acquisition_positions"):
        estimate_t1(0, DELAYS, ones, SHOTS, TS, acquisition_positions=[0] * 15)


def test_drift_reason_is_added_to_insufficient_evidence():
    """A short delay range stays INSUFFICIENT_EVIDENCE; drift is reported alongside."""
    rng = np.random.default_rng(13)
    delays = np.linspace(0, 0.05 * T1, 15)
    plan = decay_sweep_plan(delays, seed=13)
    ones = _simulate(plan, rng, offset=np.linspace(-0.03, 0.03, len(plan.slots)))
    e = estimate_t1_from_plan(0, plan, ones, SHOTS, TS)
    codes = {r["code"] for r in e.diagnostics["reasons"]}
    assert e.status is Status.INSUFFICIENT_EVIDENCE and "READOUT_DRIFT" in codes


def test_plan_counts_must_match_the_plan():
    plan = decay_sweep_plan(DELAYS, seed=1)
    with pytest.raises(ValueError, match="counts"):
        estimate_t1_from_plan(0, plan, [10] * 19, SHOTS, TS)


def test_run_t1_uses_the_interleaved_design_by_default():
    pytest.importorskip("qiskit_aer")
    from qiskit.providers.fake_provider import GenericBackendV2
    from qiskit_aer import AerSimulator

    from qnp.measured import run_t1

    b = GenericBackendV2(num_qubits=2, seed=7)
    truth = b.target.qubit_properties[0].t1
    e = run_t1(AerSimulator.from_backend(b), 0, np.linspace(0, 3 * truth, 15), shots=SHOTS, seed=5, timestamp=TS)
    assert e.status is Status.OK and e.ci_low <= truth <= e.ci_high
    assert e.diagnostics["sweep_plan"]["n_references"] == 5 and e.diagnostics["sweep_plan"]["randomized"]
    assert e.diagnostics["references"]["p"] > 0.01  # no readout drift in this simulator
