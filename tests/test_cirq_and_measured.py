from datetime import datetime, timezone

import numpy as np
import pytest

from qnp import Metric, Provenance, Status
from qnp.measured import estimate_t1, run_t1, run_t2_echo

TS = datetime(2026, 10, 1, tzinfo=timezone.utc)


def test_cirq_recovers_injected_bit_flip():
    import cirq

    from qnp.adapters.cirq_adapter import infer_from_results

    q0, q1, q2 = cirq.LineQubit.range(3)
    circuit = cirq.Circuit(
        cirq.X(q1),
        cirq.H(q2),
        cirq.bit_flip(0.04).on(q0),
        cirq.bit_flip(0.04).on(q1),
        cirq.measure(q0, q1, key="m"),
        cirq.measure(q2, key="s"),
    )
    # Noise channels are part of the "executed" circuit here; the profiler must
    # analyze the noiseless program, so pass the circuit without them.
    ideal_program = cirq.Circuit(cirq.X(q1), cirq.H(q2), cirq.measure(q0, q1, key="m"), cirq.measure(q2, key="s"))
    result = cirq.DensityMatrixSimulator(seed=3).run(circuit, repetitions=20_000)
    es = {e.qubits: e for e in infer_from_results([ideal_program], [result], TS)}
    for q in (0, 1):
        assert es[(q,)].ci_low <= 0.04 <= es[(q,)].ci_high
    assert es[(2,)].status is Status.INSUFFICIENT_EVIDENCE


@pytest.fixture(scope="module")
def relaxing_backend():
    from qiskit.providers.fake_provider import GenericBackendV2
    from qiskit_aer import AerSimulator

    b = GenericBackendV2(num_qubits=2, seed=7)
    return b, AerSimulator.from_backend(b)


def test_measured_t1_recovers_target(relaxing_backend):
    b, sim = relaxing_backend
    truth = b.target.qubit_properties[0].t1
    e = run_t1(sim, 0, np.linspace(0, 3 * truth, 15), shots=1000, seed=3, timestamp=TS)
    assert e.provenance is Provenance.MEASURED and e.status is Status.OK
    assert e.ci_low <= truth <= e.ci_high
    assert (e.ci_high - e.ci_low) / truth < 0.2


def test_measured_t2_echo_recovers_target(relaxing_backend):
    b, sim = relaxing_backend
    truth = b.target.qubit_properties[1].t2
    e = run_t2_echo(sim, 1, np.linspace(0, 3 * truth, 15), shots=1000, seed=4, timestamp=TS)
    assert e.metric is Metric.T2 and e.status is Status.OK
    assert e.ci_low <= truth <= e.ci_high


def test_t1_with_delays_far_too_short_is_insufficient():
    # True T1 = 100 us but we only probed out to 1 us: the decay is unresolved.
    delays = np.linspace(0, 1e-6, 10)
    rng = np.random.default_rng(0)
    ones = rng.binomial(1000, 0.98 * np.exp(-delays / 100e-6) + 0.01)
    e = estimate_t1(0, delays, ones, 1000, TS)
    assert e.status is Status.INSUFFICIENT_EVIDENCE and e.value is None
    assert "do not bracket" in e.reason


def test_bayesian_t1_agrees_with_qiskit_experiments(relaxing_backend):
    pytest.importorskip("qiskit_experiments")
    from qiskit_experiments.library import T1

    b, sim = relaxing_backend
    truth = b.target.qubit_properties[0].t1
    delays = np.linspace(0, 3 * truth, 15)
    ours = run_t1(sim, 0, delays, shots=1000, seed=9, timestamp=TS)
    data = T1(physical_qubits=(0,), delays=delays).run(sim, shots=1000, seed_simulator=9).block_for_results()
    theirs = data.analysis_results("T1", dataframe=True).iloc[0]["value"]
    # Same data-generating process, independent fitters: should agree within our CI width.
    assert abs(ours.value - theirs.nominal_value) < (ours.ci_high - ours.ci_low)
