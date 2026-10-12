from datetime import datetime, timezone

import pytest
from qiskit import QuantumCircuit, transpile
from qiskit.circuit import Parameter

from qnp import Metric, Provenance, Status
from qnp.adapters.qiskit_adapter import analyze_circuit, infer_from_results, observe_target

TS = datetime(2026, 10, 1, tzinfo=timezone.utc)


def test_ideal_bits_deterministic_vs_superposed():
    qc = QuantumCircuit(3)
    qc.x(0)
    qc.h(1)
    qc.measure_all()
    an = analyze_circuit(qc)
    assert an.ideal[0].bit == 1
    assert an.ideal[1].bit is None and "not deterministic" in an.ideal[1].reason
    assert an.ideal[2].bit == 0


def test_entangle_then_uncompute_is_deterministic():
    qc = QuantumCircuit(2)
    qc.h(0); qc.cx(0, 1); qc.cx(0, 1); qc.h(0); qc.x(1)
    qc.measure_all()
    an = analyze_circuit(qc)
    assert (an.ideal[0].bit, an.ideal[1].bit) == (0, 1)
    assert an.ideal[1].n_2q == 2


@pytest.mark.parametrize("build, fragment", [
    (lambda qc: (qc.measure(0, 0), qc.x(0), qc.measure(0, 0)), "mid-circuit"),
    (lambda qc: (qc.reset(0), qc.measure(0, 0)), "reset"),
    (lambda qc: (qc.rx(Parameter("t"), 0), qc.measure(0, 0)), "unbound parameters"),
])
def test_unsupported_circuits_are_reported_not_guessed(build, fragment):
    qc = QuantumCircuit(1, 1)
    build(qc)
    an = analyze_circuit(qc)
    assert an.ideal[0].bit is None and fragment in an.ideal[0].reason


def test_too_wide_to_simulate():
    qc = QuantumCircuit(5)
    qc.x(range(5))
    qc.measure_all()
    an = analyze_circuit(qc, max_sim_qubits=4)
    assert all(i.bit is None and "max_sim_qubits" in i.reason for i in an.ideal.values())


def _probe_circuits():
    zero = QuantumCircuit(2); zero.measure_all()
    one = QuantumCircuit(2); one.x([0, 1]); one.measure_all()
    return [zero, one]


def test_recovers_injected_readout_error_sampler_v2(aer):
    from qiskit_aer.primitives import SamplerV2

    sim = aer(p_by_qubit={0: 0.03, 1: 0.10})
    circs = _probe_circuits()
    sampler = SamplerV2(seed=11, options={"backend_options": {"noise_model": sim.options.noise_model}})
    result = sampler.run(circs, shots=20_000).result()
    es = infer_from_results(circs, result, TS)
    by = {(e.qubits[0], e.context.split("|")[0]): e for e in es}
    for (q, ideal), truth in {(0, "ideal=0"): 0.03, (0, "ideal=1"): 0.03,
                              (1, "ideal=0"): 0.10, (1, "ideal=1"): 0.10}.items():
        e = by[(q, ideal)]
        assert e.provenance is Provenance.INFERRED and e.metric is Metric.EFFECTIVE_FLIP
        assert e.ci_low <= truth <= e.ci_high, (q, ideal, e.value, e.ci_low, e.ci_high)


def test_legacy_counts_and_physical_layout(aer):
    sim = aer(p_by_qubit={3: 0.05})
    qc = QuantumCircuit(1, 1); qc.x(0); qc.measure(0, 0)
    isa = transpile(qc, sim, initial_layout=[3], coupling_map=[[i, i + 1] for i in range(4)],
                    optimization_level=0)
    counts = sim.run(isa, shots=20_000, seed_simulator=5).result().get_counts()
    (e,) = infer_from_results([isa], [counts], TS)
    assert e.qubits == (3,) and e.ci_low <= 0.05 <= e.ci_high


def test_too_few_shots_is_insufficient(aer):
    sim = aer(p_by_qubit={0: 0.05})
    qc = QuantumCircuit(1); qc.measure_all()
    counts = sim.run(qc, shots=50, seed_simulator=1).result().get_counts()
    (e,) = infer_from_results([qc], [counts], TS, min_shots=200)
    assert e.status is Status.INSUFFICIENT_EVIDENCE and e.value is None and e.trials == 50


def test_superposition_only_workload_yields_insufficient_evidence(aer):
    sim = aer(p_by_qubit={0: 0.05})
    qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1); qc.measure_all()
    counts = sim.run(qc, shots=4000, seed_simulator=1).result().get_counts()
    es = infer_from_results([qc], [counts], TS)
    assert {e.qubits for e in es} == {(0,), (1,)}
    assert all(e.status is Status.INSUFFICIENT_EVIDENCE and e.value is None for e in es)


def test_observe_target_reads_calibration():
    from qiskit.providers.fake_provider import GenericBackendV2

    b = GenericBackendV2(num_qubits=2, seed=1)
    es = observe_target(b.target, TS)
    t1 = [e for e in es if e.metric is Metric.T1 and e.qubits == (0,)][0]
    assert t1.provenance is Provenance.OBSERVED and t1.value == b.target.qubit_properties[0].t1
    assert t1.ci_low is None  # vendor gives no uncertainty; we don't invent one
    assert any(e.metric is Metric.READOUT_ERROR for e in es)
    assert any(e.metric is Metric.GATE_ERROR and e.context == "cx" for e in es)
