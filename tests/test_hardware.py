"""The IBM pathway is read-only by default and refuses unbudgeted or
unauthorized submissions. Uses qiskit-ibm-runtime fake backends only: no
network, no account, no QPU time."""

from datetime import datetime, timezone

import numpy as np
import pytest

rt = pytest.importorskip("qiskit_ibm_runtime")

from qnp import Metric, Provenance  # noqa: E402
from qnp.hardware import (  # noqa: E402
    BudgetExceeded,
    HardwareSession,
    JobBudget,
    SubmissionRefused,
    backend_snapshot,
    estimates_from_t1_job,
    execution_timestamps,
    observe_ibm_backend,
    plan_characterization,
)


@pytest.fixture(scope="module")
def backend():
    from qiskit_ibm_runtime.fake_provider import FakeTorino

    return FakeTorino()


def test_snapshot_records_identity_versions_and_per_property_timestamps(backend):
    s = backend_snapshot(backend, [0, 5])
    assert s["backend_name"] == "fake_torino" and s["backend_version"] and s["local_simulation"]
    assert s["software"]["qiskit"] and s["software"]["quantum-noise-profiler"] is not None
    t1 = s["qubits"]["0"]["T1"]
    assert t1["value"] > 0 and datetime.fromisoformat(t1["calibrated_at"]).tzinfo is not None
    assert set(s["qubits"]) == {"0", "5"}
    with pytest.raises(ValueError, match="does not exist"):
        backend_snapshot(backend, [500])


def test_observed_estimates_use_property_timestamps_and_asymmetric_readout(backend):
    es = observe_ibm_backend(backend, [0])
    by = {(e.metric, e.context): e for e in es}
    assert by[(Metric.T1, "")].provenance is Provenance.OBSERVED
    assert by[(Metric.T1, "")].timestamp != by[(Metric.READOUT_ERROR, "")].timestamp  # different calibrations
    assert (Metric.READOUT_ERROR, "p(1|0)") in by and (Metric.READOUT_ERROR, "p(0|1)") in by
    assert all(e.ci_low is None for e in es)  # vendor gives no uncertainty; none is invented


def test_dry_run_is_default_and_sends_nothing(backend):
    plan = plan_characterization(backend, "t1", [0], np.linspace(0, 400e-6, 8), shots=200)
    s = HardwareSession(backend)
    rec = s.submit(plan)
    assert rec["status"] == "dry_run" and rec["budget_ok"] is False  # zero default budget
    assert "job_id" not in rec and s._jobs == 0
    # 8 delays in random order + 5 interleaved ground references
    assert plan.n_circuits == 13 and plan.total_shots == 2600 and plan.estimated_qpu_seconds > 0
    assert all(c.metadata["physical_qubit"] == 0 for c in plan.circuits)
    assert plan.sweep is not None and plan.sweep.randomized and plan.summary()["sweep"]["n_references"] == 5
    v02 = plan_characterization(
        backend, "t1", [0], np.linspace(0, 400e-6, 8), shots=200, n_references=0, randomize=False
    )
    assert v02.n_circuits == 8 and any("cannot be detected" in n for n in v02.notes)


def test_submission_needs_permission_authorization_and_budget(backend):
    plan = plan_characterization(backend, "t1", [0], np.linspace(0, 400e-6, 8), shots=200)
    with pytest.raises(SubmissionRefused, match="allow_submission"):
        HardwareSession(backend, dry_run=False).submit(plan, authorize=True)
    s = HardwareSession(
        backend,
        dry_run=False,
        allow_submission=True,
        budget=JobBudget(max_jobs=1, max_total_shots=10_000, max_estimated_qpu_seconds=60),
    )
    with pytest.raises(SubmissionRefused, match="authorize"):
        s.submit(plan)
    tight = HardwareSession(
        backend,
        dry_run=False,
        allow_submission=True,
        budget=JobBudget(max_jobs=1, max_total_shots=100, max_estimated_qpu_seconds=60),
    )
    with pytest.raises(BudgetExceeded, match="shots"):
        tight.submit(plan, authorize=True)


def test_authorized_run_on_local_fake_backend_produces_measured_t1(backend):
    delays = np.linspace(0, 3 * backend.target.qubit_properties[0].t1, 12)
    plan = plan_characterization(backend, "t1", [0], delays, shots=400)
    s = HardwareSession(
        backend,
        dry_run=False,
        allow_submission=True,
        budget=JobBudget(max_jobs=1, max_total_shots=10_000, max_estimated_qpu_seconds=60),
    )
    rec = s.submit(plan, authorize=True)
    assert rec["status"] == "submitted" and rec["local_simulation"] and rec["snapshot_before"]["backend_name"]
    with pytest.raises(BudgetExceeded):
        s.submit(plan, authorize=True)  # budget now spent
    job = rec["job"]
    ts = execution_timestamps(job)
    assert "available" in ts  # fake jobs may have no timestamps; that is reported, not invented
    (e,) = estimates_from_t1_job(plan, job.result(), datetime.now(timezone.utc))
    assert e.qubits == (0,) and e.metric is Metric.T1 and e.source.endswith("fake_torino")


def test_plan_validation(backend):
    with pytest.raises(ValueError):
        plan_characterization(backend, "t1", [0, 0], [0, 1e-6, 2e-6])
    with pytest.raises(ValueError):
        plan_characterization(backend, "ramsey", [0], [0, 1e-6, 2e-6])
    with pytest.raises(ValueError):
        plan_characterization(backend, "t1", [0], [0, 1e-6])
    for bad in (1.9, True, "1"):
        with pytest.raises(ValueError, match="must be integers"):
            plan_characterization(backend, "probe", [bad], shots=100)
    with pytest.raises(ValueError, match="must be integers"):
        backend_snapshot(backend, [0.0])
    probe = plan_characterization(backend, "probe", [np.int64(3), 4], shots=100)
    assert probe.n_circuits == 4


def test_sweep_delays_are_rounded_to_the_backend_grid():
    """IBM backends reject delays off their timing grid; the fit must use the
    delays that run."""
    from qiskit_ibm_runtime.fake_provider import FakeManilaV2

    from qnp.hardware import delay_grid_seconds

    b = FakeManilaV2()
    grid = delay_grid_seconds(b)
    assert grid == pytest.approx(16 * b.target.dt)
    plan = plan_characterization(b, "t1", [0], np.linspace(0, 300e-6, 15), shots=100, seed=1)
    steps = np.asarray(plan.sweep.delays_s) / grid
    assert np.allclose(steps, np.round(steps)) and any("delay grid" in n for n in plan.notes)
    echo = plan_characterization(b, "t2_echo", [0], np.linspace(0, 300e-6, 15), shots=100, seed=1)
    halves = np.asarray(echo.sweep.delays_s) / (2 * grid)
    assert np.allclose(halves, np.round(halves))
    with pytest.raises(ValueError, match="delay grid"):
        plan_characterization(b, "t1", [0], [0, 1e-10, 2e-10, 3e-10], shots=100)
