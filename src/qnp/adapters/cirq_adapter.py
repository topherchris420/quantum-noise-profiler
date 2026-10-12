"""Cirq integration: workload inference from ``cirq.Result`` objects."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Iterable

from ..inferred import FlipTally, QubitIdeal, flip_estimates, tally_marginal
from ..models import Estimate, utcnow

_DETERMINISTIC_TOL = 1e-9


def default_qubit_index(q) -> int:
    """LineQubit -> x. Other qubit types need an explicit ``qubit_index``."""
    if hasattr(q, "x") and not hasattr(q, "row"):
        return int(q.x)
    raise ValueError(f"no default integer index for {q!r}; pass qubit_index=")


def analyze_circuit(circuit, max_sim_qubits: int = 16):
    """Return ({cirq qubit: (measurement key, column)}, {cirq qubit: QubitIdeal})."""
    import cirq
    import numpy as np

    measured: dict[Any, tuple[str, int]] = {}
    n_1q: dict[Any, int] = {}
    n_2q: dict[Any, int] = {}
    for op in circuit.all_operations():
        if cirq.is_measurement(op):
            key = cirq.measurement_key_name(op)
            for col, q in enumerate(op.qubits):
                measured[q] = (key, col)
        else:
            counter = n_1q if len(op.qubits) == 1 else n_2q
            for q in op.qubits:
                counter[q] = counter.get(q, 0) + 1

    def ideal_for(q, bit, reason=""):
        return QubitIdeal(bit, n_1q.get(q, 0), n_2q.get(q, 0), reason)

    problem = ""
    if cirq.is_parameterized(circuit):
        problem = "circuit has unresolved parameters"
    elif not circuit.are_all_measurements_terminal():
        problem = "mid-circuit measurement"
    elif not cirq.has_unitary(cirq.drop_terminal_measurements(circuit)):
        problem = "circuit contains non-unitary operations"
    elif len(circuit.all_qubits()) > max_sim_qubits:
        problem = f"{len(circuit.all_qubits())} qubits > max_sim_qubits={max_sim_qubits}"
    if problem:
        return measured, {q: ideal_for(q, None, problem) for q in measured}

    unitary_part = cirq.drop_terminal_measurements(circuit)
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
) -> list[Estimate]:
    timestamp = timestamp or utcnow()
    tallies: dict[tuple[int, str], FlipTally] = {}
    unidentified: dict[int, str] = {}
    for circuit, res in zip(circuits, results, strict=True):
        measured, ideal = analyze_circuit(circuit, max_sim_qubits)
        for q, (key, col) in measured.items():
            qi = qubit_index(q)
            if ideal[q].bit is None:
                unidentified.setdefault(qi, ideal[q].reason)
                continue
            bits = res.measurements[key][:, col]
            tally_marginal(tallies, qi, ideal[q], int(bits.shape[0]), int(bits.sum()))
    return flip_estimates(tallies, unidentified, timestamp, source, min_shots)
