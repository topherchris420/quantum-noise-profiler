"""Readout probes: prep-and-measure circuits become MEASURED readout_error
series (the workload-independent series that carries the absolute threshold);
everything else stays INFERRED workload evidence."""

from datetime import datetime, timezone

import numpy as np
import pytest
from qiskit import QuantumCircuit
from qiskit.circuit import Parameter

from qnp import Metric, Profiler, Provenance, Status
from qnp.adapters.qiskit_adapter import estimates_from_results, readout_probe_preparations
from qnp.measured import READOUT_CONTEXTS, estimate_readout, readout_probe_circuits

TS = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _mirror(n=2):
    qc = QuantumCircuit(n)
    for q in range(n):
        qc.sx(q)
        qc.sxdg(q)
    qc.cx(0, 1)
    qc.cx(0, 1)
    qc.measure_all()
    return qc


def test_probe_circuits_are_recognised_with_their_preparations():
    zero, one = readout_probe_circuits([3, 7], num_qubits=8)
    assert readout_probe_preparations(zero) == {3: (0, ("c", 0, 0)), 7: (0, ("c", 1, 1))}
    assert readout_probe_preparations(one) == {3: (1, ("c", 0, 0)), 7: (1, ("c", 1, 1))}
    mixed = QuantumCircuit(2)
    mixed.x(1)
    mixed.measure_all()  # barrier + measurements into a "meas" register
    assert readout_probe_preparations(mixed) == {0: (0, ("meas", 0, 0)), 1: (1, ("meas", 1, 1))}


def _with(build, n=1, c=1):
    qc = QuantumCircuit(n, c)
    build(qc)
    return qc


@pytest.mark.parametrize(
    "circuit",
    [
        _with(lambda qc: (qc.sx(0), qc.measure(0, 0))),  # another gate
        _with(lambda qc: (qc.x(0), qc.x(0), qc.measure(0, 0))),  # two X: not a preparation
        _with(lambda qc: (qc.x(0), qc.delay(2e-6, 0, unit="s"), qc.measure(0, 0))),  # idle time
        _with(lambda qc: (qc.measure(0, 0), qc.x(0))),  # operation after the measurement
        _with(lambda qc: (qc.reset(0), qc.measure(0, 0))),
        _with(lambda qc: (qc.rx(Parameter("t"), 0), qc.measure(0, 0))),
        _with(lambda qc: (qc.measure(0, 0), qc.measure(1, 0)), n=2),  # two qubits into one bit
        _with(lambda qc: qc.x(0)),  # nothing measured
        _mirror(),
    ],
)
def test_anything_else_is_workload(circuit):
    assert readout_probe_preparations(circuit) is None


def test_estimate_readout_contexts_counts_and_validation():
    e = estimate_readout(5, 1, 30, 1000, TS)
    assert (e.metric, e.provenance, e.context, e.qubits) == (Metric.READOUT_ERROR, Provenance.MEASURED, "p(0|1)", (5,))
    assert (e.successes, e.trials) == (30, 1000) and e.ci_low < 0.03 < e.ci_high
    assert estimate_readout(5, 0, 3, 100, TS).status is Status.INSUFFICIENT_EVIDENCE
    with pytest.raises(ValueError):
        estimate_readout(5, 2, 3, 1000, TS)
    assert READOUT_CONTEXTS == {0: "p(1|0)", 1: "p(0|1)"}


def test_aer_asymmetric_readout_is_recovered_per_qubit_and_workload_stays_inferred():
    from qiskit_aer import AerSimulator
    from qiskit_aer.noise import NoiseModel, ReadoutError

    p10, p01 = {0: 0.02, 1: 0.05}, {0: 0.06, 1: 0.01}  # P(1|0), P(0|1)
    nm = NoiseModel()
    for q in (0, 1):
        nm.add_readout_error(ReadoutError([[1 - p10[q], p10[q]], [p01[q], 1 - p01[q]]]), [q])
    circuits = [*readout_probe_circuits([0, 1]), _mirror()]
    res = AerSimulator(noise_model=nm).run(circuits, shots=40_000, seed_simulator=3).result()
    es = estimates_from_results(circuits, [res.get_counts(i) for i in range(3)], TS)
    measured = {(e.qubits[0], e.context): e for e in es if e.provenance is Provenance.MEASURED}
    assert set(measured) == {(q, c) for q in (0, 1) for c in ("p(1|0)", "p(0|1)")}
    for q in (0, 1):
        assert measured[(q, "p(1|0)")].ci_low <= p10[q] <= measured[(q, "p(1|0)")].ci_high
        assert measured[(q, "p(0|1)")].ci_low <= p01[q] <= measured[(q, "p(0|1)")].ci_high
        assert measured[(q, "p(1|0)")].trials == 40_000
    inferred = [e for e in es if e.provenance is Provenance.INFERRED]
    assert {e.qubits[0] for e in inferred} == {0, 1} and all(e.metric is Metric.EFFECTIVE_FLIP for e in inferred)
    assert all(e.context.startswith("ideal=0|ops=") for e in inferred)  # exact contexts by default
    # v0.2 behaviour on request: every circuit is workload, bucketed contexts
    old = estimates_from_results(
        circuits, [res.get_counts(i) for i in range(3)], TS, context_mode="bucket", readout_probes="off"
    )
    assert all(e.provenance is Provenance.INFERRED for e in old)
    assert {e.context for e in old if e.qubits == (0,)} == {
        "ideal=0|1q<=0|2q<=0",
        "ideal=1|1q<=1|2q<=0",
        "ideal=0|1q<=4|2q<=2",
    }
    with pytest.raises(ValueError, match="readout_probes"):
        estimates_from_results(circuits, [res.get_counts(i) for i in range(3)], TS, readout_probes="maybe")


def test_probe_counts_pool_within_a_batch_and_pub_results_work():
    from qiskit.primitives import StatevectorSampler

    zero, one = readout_probe_circuits([0])
    res = StatevectorSampler(seed=1).run([zero, one, zero], shots=500).result()
    es = estimates_from_results([zero, one, zero], res, TS)
    by = {e.context: e for e in es}
    assert by["p(1|0)"].trials == 1000 and by["p(1|0)"].successes == 0
    assert by["p(0|1)"].trials == 500 and by["p(0|1)"].successes == 0


def test_profiler_routes_probes_and_thresholds_them():
    """The absolute threshold applies to the probe series, not to workload rates."""
    from datetime import timedelta

    prof = Profiler()
    zero, one = readout_probe_circuits([0])
    rng = np.random.default_rng(0)
    for i in range(10):
        p = 0.02 if i < 4 else 0.09
        counts0 = {"1": int(rng.binomial(4000, p))}
        counts0["0"] = 4000 - counts0["1"]
        counts1 = {"0": int(rng.binomial(4000, p))}
        counts1["1"] = 4000 - counts1["0"]
        prof.ingest_qiskit([zero, one], [counts0, counts1], TS + timedelta(minutes=10 * i))
    alerts = prof.check()
    crit = [a for a in alerts if a.kind == "threshold"]
    assert crit and crit[0].metric is Metric.READOUT_ERROR and crit[0].provenance is Provenance.MEASURED
    assert crit[0].details["guarantee"] == "exact"


def test_hardware_probe_plans_are_recognised():
    rt = pytest.importorskip("qiskit_ibm_runtime")
    from qnp.hardware import plan_characterization

    backend = rt.fake_provider.FakeTorino()
    plan = plan_characterization(backend, "probe", [0, 5], shots=100)
    preps = [readout_probe_preparations(c) for c in plan.circuits]
    assert [None if p is None else sorted((q, b) for q, (b, _) in p.items()) for p in preps] == [
        [(0, 0)],
        [(0, 1)],
        [(5, 0)],
        [(5, 1)],
    ]


def test_cirq_probes_match_qiskit_on_identical_outcomes():
    import cirq

    from qnp.adapters.cirq_adapter import estimates_from_results as cirq_estimates
    from qnp.adapters.cirq_adapter import readout_probe_circuits as cirq_probes
    from qnp.adapters.cirq_adapter import readout_probe_preparations as cirq_preps

    q3, q7 = cirq.LineQubit(3), cirq.LineQubit(7)
    cz, co = cirq_probes([q3, q7])
    assert cirq_preps(co) == {q3: (1, ("m", 0)), q7: (1, ("m", 1))}
    assert cirq_preps(cirq.Circuit(cirq.H(q3), cirq.measure(q3, key="m"))) is None
    assert cirq_preps(cirq.Circuit(cirq.X(q3), cirq.X(q3), cirq.measure(q3, key="m"))) is None
    rng = np.random.default_rng(4)
    shots = 3000
    bits0 = (rng.random((shots, 2)) < [0.02, 0.04]).astype(np.int8)  # read 1 after prep 0
    bits1 = (rng.random((shots, 2)) > [0.05, 0.03]).astype(np.int8)  # read 0 after prep 1
    rz = cirq.ResultDict(params=cirq.ParamResolver({}), measurements={"m": bits0})
    ro = cirq.ResultDict(params=cirq.ParamResolver({}), measurements={"m": bits1})
    c_es = {(e.qubits, e.context): e for e in cirq_estimates([cz, co], [rz, ro], TS)}
    qz, qo = readout_probe_circuits([3, 7], num_qubits=8)

    def counts(bits):
        out: dict = {}
        for row in bits:
            key = "".join(str(b) for b in row[::-1])  # Qiskit: clbit 0 is the rightmost character
            out[key] = out.get(key, 0) + 1
        return out

    q_es = {(e.qubits, e.context): e for e in estimates_from_results([qz, qo], [counts(bits0), counts(bits1)], TS)}
    assert set(c_es) == set(q_es) == {((q,), c) for q in (3, 7) for c in ("p(1|0)", "p(0|1)")}
    for k in c_es:
        assert (c_es[k].successes, c_es[k].trials) == (q_es[k].successes, q_es[k].trials)
