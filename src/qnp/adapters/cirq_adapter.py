"""Cirq integration: workload inference from ``cirq.Result`` objects."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any

from ..inferred import FlipTally, QubitIdeal, flip_estimates, tally_marginal
from ..models import Estimate, utcnow

_DETERMINISTIC_TOL = 1e-9


def default_qubit_index(q) -> int:
    """LineQubit -> x. Other qubit types need an explicit ``qubit_index``."""
    if hasattr(q, "x") and not hasattr(q, "row"):
        return int(q.x)
    raise ValueError(f"no default integer index for {q!r}; pass qubit_index=")


def canonical_gate_name(op) -> str:
    """Qiskit-style name for a Cirq gate, so that exact contexts agree across
    frameworks: X -> x, X**0.5 -> sx, H -> h, Y -> y, Ry -> ry, Rz/Z**t -> rz,
    CNOT -> cx, CZ -> cz; otherwise the gate class name in lower case."""
    import cirq

    g = op.gate
    if isinstance(g, cirq.Rx):
        return "rx"
    if isinstance(g, cirq.XPowGate):
        e = g.exponent % 2
        if abs(e - 1) < 1e-9:
            return "x"
        if abs(e - 0.5) < 1e-9:
            return "sx"
        return "sxdg" if abs(e - 1.5) < 1e-9 else "rx"
    if isinstance(g, cirq.HPowGate):
        return "h"
    if isinstance(g, cirq.Ry):
        return "ry"
    if isinstance(g, cirq.YPowGate):
        return "y" if abs(g.exponent % 2 - 1) < 1e-9 else "ry"
    if isinstance(g, (cirq.Rz, cirq.ZPowGate)):
        return "rz"
    if isinstance(g, cirq.CXPowGate):
        return "cx"
    if isinstance(g, cirq.CZPowGate):
        return "cz"
    return type(g).__name__.lower()


def _drop_waits(circuit):
    import cirq

    return cirq.Circuit(
        cirq.Moment(op for op in m.operations if not isinstance(op.gate, cirq.WaitGate)) for m in circuit
    )


def analyze_circuit(circuit, max_sim_qubits: int = 16, context_mode: str = "bucket"):
    """Return ({cirq qubit: (measurement key, column)}, {cirq qubit: QubitIdeal})."""
    import cirq
    import numpy as np

    measured: dict[Any, tuple[str, int]] = {}
    n_1q: dict[Any, int] = {}
    n_2q: dict[Any, int] = {}
    names: dict[Any, dict[str, int]] = {}
    idle_ns: dict[Any, float] = {}
    for op in circuit.all_operations():
        if cirq.is_measurement(op):
            key = cirq.measurement_key_name(op)
            for col, q in enumerate(op.qubits):
                measured[q] = (key, col)
        elif isinstance(op.gate, cirq.WaitGate):
            for q in op.qubits:
                idle_ns[q] = idle_ns.get(q, 0.0) + float(op.gate.duration.total_nanos())
        else:
            counter = n_1q if len(op.qubits) == 1 else n_2q
            name = canonical_gate_name(op)
            for q in op.qubits:
                counter[q] = counter.get(q, 0) + 1
                names.setdefault(q, {})[name] = names.get(q, {}).get(name, 0) + 1

    def ideal_for(q, bit, reason=""):
        return QubitIdeal(
            bit,
            n_1q.get(q, 0),
            n_2q.get(q, 0),
            reason,
            tuple(sorted(names.get(q, {}).items())),
            idle_ns.get(q, 0.0),
            0,
            context_mode,
        )

    problem = ""
    if cirq.is_parameterized(circuit):
        problem = "circuit has unresolved parameters"
    elif not circuit.are_all_measurements_terminal():
        problem = "mid-circuit measurement"
    elif not cirq.has_unitary(_drop_waits(cirq.drop_terminal_measurements(circuit))):
        problem = "circuit contains non-unitary operations"
    elif len(circuit.all_qubits()) > max_sim_qubits:
        problem = f"{len(circuit.all_qubits())} qubits > max_sim_qubits={max_sim_qubits}"
    if problem:
        return measured, {q: ideal_for(q, None, problem) for q in measured}

    unitary_part = _drop_waits(cirq.drop_terminal_measurements(circuit))
    order = sorted(circuit.all_qubits())
    state = cirq.final_state_vector(unitary_part, qubit_order=order, dtype=np.complex128)
    probs = np.abs(state) ** 2
    n = len(order)
    ideal = {}
    for q in measured:
        i = order.index(q)
        # Cirq is big-endian: qubit i is bit (n - 1 - i) of the basis index.
        mask = 1 << (n - 1 - i)
        p1 = float(probs[[b for b in range(2**n) if b & mask]].sum())
        if p1 < _DETERMINISTIC_TOL:
            ideal[q] = ideal_for(q, 0)
        elif p1 > 1 - _DETERMINISTIC_TOL:
            ideal[q] = ideal_for(q, 1)
        else:
            ideal[q] = ideal_for(q, None, f"ideal outcome not deterministic (p1={p1:.3f})")
    return measured, ideal


def infer_from_results(
    circuits: Iterable[Any],
    results: Iterable[Any],
    timestamp: datetime | None = None,
    source: str = "cirq",
    qubit_index: Callable[[Any], int] = default_qubit_index,
    min_shots: int = 200,
    max_sim_qubits: int = 16,
    context_mode: str = "bucket",
) -> list[Estimate]:
    import numpy as np

    timestamp = timestamp or utcnow()
    tallies: dict[tuple[int, str], FlipTally] = {}
    unidentified: dict[int, str] = {}
    owner: dict[int, Any] = {}
    for circuit, res in zip(circuits, results, strict=True):
        measured, ideal = analyze_circuit(circuit, max_sim_qubits, context_mode)
        for q, (key, col) in measured.items():
            qi = qubit_index(q)
            if not isinstance(qi, int) or isinstance(qi, bool) or qi < 0:
                raise ValueError(f"qubit_index({q!r}) returned {qi!r}; need a non-negative int")
            if owner.setdefault(qi, q) != q:
                raise ValueError(f"inconsistent qubit identifiers: {owner[qi]!r} and {q!r} both map to index {qi}")
            if key not in res.measurements:
                raise ValueError(f"result has no measurement key {key!r}: results do not belong to this circuit")
            data = res.measurements[key]
            if data.ndim != 2 or col >= data.shape[1]:
                raise ValueError(f"measurement {key!r} has shape {data.shape}; expected a column for {q!r}")
            if not np.isin(data, (0, 1)).all():
                raise ValueError(f"measurement {key!r} contains values other than 0/1")
            if ideal[q].bit is None:
                unidentified.setdefault(qi, ideal[q].reason)
                continue
            bits = res.measurements[key][:, col]
            tally_marginal(tallies, qi, ideal[q], int(bits.shape[0]), int(bits.sum()))
    return flip_estimates(tallies, unidentified, timestamp, source, min_shots)
