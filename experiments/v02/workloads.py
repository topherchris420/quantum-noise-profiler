"""Workloads and data generators for Experiments E (workload shift) and F
(cross-framework). See V02_PREREGISTRATION.md §7-8 and V02_DEVIATIONS.md DV1."""

from __future__ import annotations

from datetime import timedelta

import numpy as np

from qnp.sim import DeviceNoise, QubitNoise, aer_run_counts, cirq_noisy_circuit

from .harness import BATCH_INTERVAL, T0, Batch

E_DEVICE = DeviceNoise(
    {0: QubitNoise(100e-6, 80e-6, 0.02, 0.02, 0.002), 1: QubitNoise(100e-6, 80e-6, 0.02, 0.02, 0.002)},
    depol_2q=0.01,
    gate_scale={"x": 3.0},
)


def mirror_pair(qubits=(0, 1), n_total=None, seed=1234, pad=0, pad_gate="sx", idle_s=0.0, extra_cx=0):
    """The v0.1 mirror pair (random layer + inverse; second circuit adds X on
    both qubits), optionally with identity padding, idle time before
    measurement, or an extra identity cx pair. Qubits are placed on
    ``qubits`` of an ``n_total``-qubit register with one classical bit each."""
    from qiskit import QuantumCircuit

    a, b = qubits
    n_total = n_total or (max(qubits) + 1)
    rng = np.random.default_rng(seed)
    angles = rng.uniform(0, 2 * np.pi, (2, 2))
    out = []
    for flip in (False, True):
        qc = QuantumCircuit(n_total, 2)
        layer = QuantumCircuit(n_total)
        for j, q in enumerate((a, b)):
            layer.rz(angles[j, 0], q)
            layer.sx(q)
            layer.rz(angles[j, 1], q)
        layer.cx(a, b)
        qc.compose(layer, inplace=True)
        qc.compose(layer.inverse(), inplace=True)
        for _ in range(extra_cx):
            qc.cx(a, b)
            qc.cx(a, b)
        for q in (a, b):
            for _ in range(pad):
                getattr(qc, pad_gate)(q)
        if flip:
            qc.x(a)
            qc.x(b)
        if idle_s:
            qc.delay(idle_s, a, unit="s")
            qc.delay(idle_s, b, unit="s")
        qc.measure(a, 0)
        qc.measure(b, 1)
        out.append(qc)
    return out


def random_pair(qubits=(0, 1), n_total=None, seed=1234):
    from qiskit import QuantumCircuit

    a, b = qubits
    n_total = n_total or (max(qubits) + 1)
    rng = np.random.default_rng(seed + 1)
    out = []
    for _ in range(2):
        qc = QuantumCircuit(n_total, 2)
        qc.h(a)
        qc.ry(rng.uniform(0.3, 2.8), b)
        qc.cx(a, b)
        qc.measure(a, 0)
        qc.measure(b, 1)
        out.append(qc)
    return out


E_SCENARIOS = ("E1", "E2", "E3", "E4", "E5", "E6", "E7")


def e_workload(scenario: str, phase: int):
    """(circuits, shots) for scenario and phase (0 before, 1 after batch 24)."""
    base = mirror_pair(pad=4) + random_pair()
    if phase == 0:
        if scenario == "E3":
            return mirror_pair(pad=0) * 3 + mirror_pair(pad=8) + random_pair(), 2000
        return base, 2000
    if scenario == "E1":
        return mirror_pair(pad=8) + random_pair(), 2000
    if scenario in ("E2", "E7"):
        return mirror_pair(pad=4, pad_gate="x") + random_pair(), 2000
    if scenario == "E3":
        return mirror_pair(pad=0) + mirror_pair(pad=8) * 3 + random_pair(), 2000
    if scenario == "E4":
        return base, 500
    if scenario == "E5":
        return mirror_pair(pad=4, idle_s=2e-6) + random_pair(), 2000
    if scenario == "E6":
        return mirror_pair(pad=4, extra_cx=1) + random_pair(), 2000
    raise ValueError(scenario)


def e_batches(
    scenario: str, seed: int, n_batches: int = 48, shift_at: int = 24, modes=("bucket", "exact")
) -> dict[str, list[Batch]]:
    from qnp import Status
    from qnp.adapters.qiskit_adapter import infer_from_results

    out: dict[str, list[Batch]] = {m: [] for m in modes}
    t = T0
    for i in range(n_batches):
        phase = int(i >= shift_at)
        circuits, shots = e_workload(scenario, phase)
        dev = E_DEVICE
        if scenario == "E7" and phase:
            dev = dev.with_qubit(0, p_read1_given0=0.03, p_read0_given1=0.03)
        counts = aer_run_counts(circuits, dev, shots, seed * 10_000 + i)
        if i > 0:
            t = t + (timedelta(minutes=30) if (scenario == "E4" and phase) else BATCH_INTERVAL)
        p0 = dev.qubits[0].p_read1_given0
        for m in modes:
            es = infer_from_results(circuits, counts, t, context_mode=m)
            cs: dict[int, dict[str, tuple[int, int]]] = {}
            for e in es:
                if e.status is Status.OK:
                    cs.setdefault(e.qubits[0], {})[e.context] = (e.successes, e.trials)
            out[m].append(Batch(i, t, [p0, 0.02], cs))
    return out


# --------------------------------------------------------------------------- Experiment F

F_QUBITS = (3, 7)
F_DEVICE = DeviceNoise(
    {3: QubitNoise(100e-6, 80e-6, 0.02, 0.02, 0.002), 7: QubitNoise(100e-6, 80e-6, 0.02, 0.02, 0.002)},
    depol_2q=0.01,
)


def f_circuits_qiskit():
    return mirror_pair(qubits=F_QUBITS, n_total=8) + random_pair(qubits=F_QUBITS, n_total=8)


def qiskit_to_cirq(qc):
    """Translate the small gate set used here; measurement key 'm' over the
    measured qubits in classical-bit order."""
    import cirq

    qs = {i: cirq.LineQubit(i) for i in range(qc.num_qubits)}
    ops, meas = [], {}
    for inst in qc.data:
        name = inst.operation.name
        idx = [qc.find_bit(q).index for q in inst.qubits]
        p = [float(x) for x in inst.operation.params]
        if name == "rz":
            ops.append(cirq.rz(p[0]).on(qs[idx[0]]))
        elif name == "sx":
            ops.append((cirq.X**0.5).on(qs[idx[0]]))
        elif name == "sxdg":
            ops.append((cirq.X**-0.5).on(qs[idx[0]]))
        elif name == "x":
            ops.append(cirq.X(qs[idx[0]]))
        elif name == "h":
            ops.append(cirq.H(qs[idx[0]]))
        elif name == "ry":
            ops.append(cirq.ry(p[0]).on(qs[idx[0]]))
        elif name == "cx":
            ops.append(cirq.CNOT(qs[idx[0]], qs[idx[1]]))
        elif name == "delay":
            ops.append(cirq.WaitGate(cirq.Duration(nanos=p[0] * 1e9)).on(qs[idx[0]]))
        elif name == "measure":
            meas[qc.find_bit(inst.clbits[0]).index] = qs[idx[0]]
        elif name == "barrier":
            continue
        else:
            raise ValueError(f"no Cirq translation for {name}")
    order = [meas[k] for k in sorted(meas)]
    return cirq.Circuit([*ops, cirq.measure(*order, key="m")])


def f_batches(
    framework: str, condition: str, seed: int, n_batches: int = 48, step_at: int = 24, shots: int = 2000
) -> list[Batch]:
    from qnp import Status

    qk = f_circuits_qiskit()
    ck = [qiskit_to_cirq(c) for c in qk]
    out = []
    for i in range(n_batches):
        dev = F_DEVICE
        if condition == "F2" and i >= step_at:
            dev = dev.with_qubit(3, p_read1_given0=0.03, p_read0_given1=0.03)
        t = T0 + i * BATCH_INTERVAL
        if framework == "qiskit":
            from qnp.adapters.qiskit_adapter import infer_from_results

            counts = aer_run_counts(qk, dev, shots, seed * 10_000 + i)
            es = infer_from_results(qk, counts, t, context_mode="exact")
        elif framework == "cirq":
            import cirq

            from qnp.adapters.cirq_adapter import infer_from_results as cirq_infer

            sim = cirq.DensityMatrixSimulator(seed=seed * 10_000 + i)
            results = [sim.run(cirq_noisy_circuit(c, dev), repetitions=shots) for c in ck]
            es = cirq_infer(ck, results, t, context_mode="exact")
        else:
            raise ValueError(framework)
        cs: dict[int, dict[str, tuple[int, int]]] = {}
        for e in es:
            if e.status is Status.OK:
                cs.setdefault(e.qubits[0], {})[e.context] = (e.successes, e.trials)
        out.append(Batch(i, t, [dev.qubits[3].p_read1_given0, 0.02], cs))
    return out
