"""Adapters must fail explicitly on malformed input and expose exact contexts."""

from datetime import datetime, timezone

import numpy as np
import pytest
from qiskit import QuantumCircuit

from qnp.adapters.qiskit_adapter import analyze_circuit, infer_from_results

TS = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _one():
    qc = QuantumCircuit(1, 1)
    qc.x(0)
    qc.measure(0, 0)
    return qc


@pytest.mark.parametrize(
    "counts, fragment",
    [
        ({"1": 900, "2": 100}, "malformed bitstring"),
        ({"0x1": 1000}, "malformed bitstring"),
        ({"1": 900, "01": 100}, "inconsistent bitstring lengths"),
        ({"1": -5, "0": 100}, "negative count"),
        ({"1": 2.5}, "must be an integer"),
        ({}, "non-empty mapping"),
        ({"1": 0, "0": 0}, "no shots"),
        ({"11": 1000}, "do not belong to this circuit"),
    ],
)
def test_malformed_counts_raise(counts, fragment):
    with pytest.raises(ValueError, match=fragment):
        infer_from_results([_one()], [counts], TS)


def test_naive_timestamp_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        infer_from_results([_one()], [{"1": 1000}], datetime(2026, 10, 1))


def test_exact_context_separates_idle_and_gate_composition():
    a = QuantumCircuit(1, 1)
    a.sx(0)
    a.sx(0)
    a.sx(0)
    a.sx(0)
    a.x(0)
    a.measure(0, 0)
    b = QuantumCircuit(1, 1)
    b.x(0)
    b.x(0)
    b.x(0)
    b.x(0)
    b.x(0)
    b.measure(0, 0)
    c = QuantumCircuit(1, 1)
    c.x(0)
    c.delay(20e-6, 0, unit="s")
    c.measure(0, 0)
    d = QuantumCircuit(1, 1)
    d.x(0)
    d.measure(0, 0)
    bucket = {analyze_circuit(x).ideal[0].context for x in (a, b)}
    assert len(bucket) == 1  # v0.1 buckets pool them
    exact = [analyze_circuit(x, context_mode="exact").ideal[0].context for x in (a, b, c, d)]
    assert len(set(exact)) == 4
    assert exact[0] == "ideal=1|ops=sx4.x1|idle=0" and exact[2] == "ideal=1|ops=x1|idle=20000ns"
    assert analyze_circuit(c).ideal[0].context == analyze_circuit(d).ideal[0].context  # bucket ignores idle


def test_exact_contexts_agree_across_frameworks():
    import cirq

    from qnp.adapters.cirq_adapter import analyze_circuit as cirq_analyze

    qc = QuantumCircuit(2)
    qc.rz(0.3, 0)
    qc.sx(0)
    qc.cx(0, 1)
    qc.cx(0, 1)
    qc.sx(0)
    qc.sx(0)
    qc.sx(0)
    qc.rz(-0.3, 0)
    qc.x(1)
    qc.delay(1e-6, 1, unit="s")
    qc.measure_all()
    q0, q1 = cirq.LineQubit.range(2)
    cc = cirq.Circuit(
        cirq.rz(0.3).on(q0),
        (cirq.X**0.5).on(q0),
        cirq.CNOT(q0, q1),
        cirq.CNOT(q0, q1),
        (cirq.X**0.5).on(q0),
        (cirq.X**0.5).on(q0),
        (cirq.X**0.5).on(q0),
        cirq.rz(-0.3).on(q0),
        cirq.X(q1),
        cirq.WaitGate(cirq.Duration(nanos=1000)).on(q1),
        cirq.measure(q0, q1, key="m"),
    )
    qk = analyze_circuit(qc, context_mode="exact").ideal
    _, ci = cirq_analyze(cc, context_mode="exact")
    assert qk[0].context == ci[q0].context and qk[1].context == ci[q1].context
    assert qk[1].context == "ideal=1|ops=cx2.x1|idle=1000ns"


def test_cirq_inconsistent_qubit_identifiers_raise():
    import cirq

    from qnp.adapters.cirq_adapter import infer_from_results as cirq_infer

    a, b = cirq.GridQubit(0, 1), cirq.GridQubit(1, 1)
    circ = cirq.Circuit(cirq.X(a), cirq.measure(a, b, key="m"))
    res = cirq.Simulator(seed=1).run(circ, repetitions=300)
    with pytest.raises(ValueError, match="inconsistent qubit identifiers"):
        cirq_infer([circ], [res], TS, qubit_index=lambda q: q.col)
    with pytest.raises(ValueError, match="no default integer index"):
        cirq_infer([circ], [res], TS)
    ok = cirq_infer([circ], [res], TS, qubit_index=lambda q: 10 * q.row + q.col)
    assert {e.qubits for e in ok} == {(1,), (11,)}


def test_cirq_result_for_wrong_circuit_raises():
    import cirq

    from qnp.adapters.cirq_adapter import infer_from_results as cirq_infer

    q = cirq.LineQubit(0)
    circ = cirq.Circuit(cirq.X(q), cirq.measure(q, key="m"))
    other = cirq.Simulator(seed=1).run(cirq.Circuit(cirq.measure(q, key="z")), repetitions=300)
    with pytest.raises(ValueError, match="no measurement key"):
        cirq_infer([circ], [other], TS)


def test_observe_backend_without_calibration_metadata():
    from qiskit.transpiler import Target

    from qnp import Status
    from qnp.adapters.qiskit_adapter import observe_target

    es = observe_target(Target(num_qubits=2), TS)
    assert es and all(e.status is Status.INSUFFICIENT_EVIDENCE and "reports no" in e.reason for e in es)


def test_identical_counts_give_identical_estimates_across_frameworks():
    """Same physical qubits, same counts -> same estimates from both adapters."""
    import cirq

    from qnp.adapters.cirq_adapter import infer_from_results as cirq_infer

    rng = np.random.default_rng(0)
    bits = np.column_stack([rng.random(2000) < 0.03, rng.random(2000) > 0.05]).astype(int)  # q3 ideal 0, q7 ideal 1
    qc = QuantumCircuit(8, 2)
    qc.x(7)
    qc.measure(3, 0)
    qc.measure(7, 1)
    keys = ["".join(str(b) for b in row[::-1]) for row in bits]  # clbit 1 is leftmost
    counts = {k: keys.count(k) for k in set(keys)}
    q3, q7 = cirq.LineQubit(3), cirq.LineQubit(7)
    cc = cirq.Circuit(cirq.X(q7), cirq.measure(q3, q7, key="m"))
    res = cirq.ResultDict(params=cirq.ParamResolver({}), measurements={"m": bits})
    a = {(e.qubits, e.context.split("|")[0]): e for e in infer_from_results([qc], [counts], TS)}
    b = {(e.qubits, e.context.split("|")[0]): e for e in cirq_infer([cc], [res], TS)}
    assert set(a) == set(b) == {((3,), "ideal=0"), ((7,), "ideal=1")}
    for k in a:
        assert (a[k].successes, a[k].trials, a[k].value, a[k].ci_low, a[k].ci_high) == (
            b[k].successes,
            b[k].trials,
            b[k].value,
            b[k].ci_low,
            b[k].ci_high,
        )
