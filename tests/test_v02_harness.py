"""The v0.2 experiment harness: surrogate/Aer equivalence and exactness of
post-hoc threshold rescaling."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

from v02.harness import (
    EngineSpec,
    aer_batches,
    first_alarm,
    first_alarm_rescaled,
    run_engine,
    seed_for,
    surrogate_batches,
)


def test_surrogate_matches_aer_count_distribution():
    p = [np.full(40, 0.03), np.full(40, 0.02)]
    sur = surrogate_batches(p, 2000, 11)
    aer = aer_batches(p, 2000, 11)
    for q, truth in ((0, 0.03), (1, 0.02)):
        for b in (sur, aer):
            ks = np.array([k for x in b for k, _ in x.counts[q].values()])
            # mean and variance of Binomial(2000, p) counts
            assert ks.mean() == pytest.approx(2000 * truth, abs=4 * np.sqrt(2000 * truth / len(ks)))
            assert ks.var(ddof=1) == pytest.approx(2000 * truth * (1 - truth), rel=0.35)
    assert set(aer[0].counts[0]) == set(sur[0].counts[0])  # same contexts


def test_rescaled_rule_reproduces_engine_alarms_and_direct_offset():
    sched = [np.r_[np.full(20, 0.02), np.full(20, 0.026)], np.full(40, 0.02)]
    batches = surrogate_batches(sched, 2000, 5)
    log0 = run_engine(batches, EngineSpec("v02", "v02"))
    for q in (0, 1):
        assert first_alarm_rescaled(log0, q, 0.0) == first_alarm(log0, q)
    c = 2.0
    log_c = run_engine(batches, EngineSpec("v02c", "v02", extra={"log_e_offset": c}))
    for q in (0, 1):
        assert first_alarm_rescaled(log0, q, c) == first_alarm(log_c, q)


def test_seed_layout_is_collision_free():
    seeds = {seed_for(30_000, e, c, r) for e in range(6) for c in range(5) for r in range(200)}
    assert len(seeds) == 6 * 5 * 200
    with pytest.raises(ValueError):
        seed_for(30_000, 0, 0, 200)


def test_experiment_f_circuits_have_identical_exact_flip_probabilities_in_aer_and_cirq():
    """Exact (density-matrix) cross-framework check behind docs/INVESTIGATION_V02.md section 5."""
    import cirq
    from qiskit_aer import AerSimulator
    from v02.workloads import F_DEVICE, mirror_pair, qiskit_to_cirq

    from qnp.sim import DeviceNoise, aer_noise_model, cirq_noisy_circuit

    for dev in (F_DEVICE, DeviceNoise(F_DEVICE.qubits, depol_2q=0.0)):
        for qc in mirror_pair(qubits=(3, 7), n_total=8):
            a = qc.remove_final_measurements(inplace=False)
            a.save_density_matrix(qubits=[3, 7])
            pa = np.real(
                np.diag(
                    np.asarray(
                        AerSimulator(method="density_matrix", noise_model=aer_noise_model(dev))
                        .run(a)
                        .result()
                        .data()["density_matrix"]
                    )
                )
            )
            noisy = cirq_noisy_circuit(qiskit_to_cirq(qc), dev)
            noisy = cirq.Circuit(
                cirq.Moment(
                    o for o in m.operations if not (cirq.is_measurement(o) or isinstance(o.gate, cirq.KrausChannel))
                )
                for m in noisy
            )
            q3, q7 = cirq.LineQubit(3), cirq.LineQubit(7)
            pc = np.real(
                np.diag(
                    np.asarray(cirq.DensityMatrixSimulator().simulate(noisy, qubit_order=[q3, q7]).final_density_matrix)
                )
            )
            # Aer index = b3 + 2*b7 (little-endian); Cirq index = 2*b3 + b7 (big-endian)
            assert pa[1] + pa[3] == pytest.approx(pc[2] + pc[3], abs=1e-6)
            assert pa[2] + pa[3] == pytest.approx(pc[1] + pc[3], abs=1e-6)
