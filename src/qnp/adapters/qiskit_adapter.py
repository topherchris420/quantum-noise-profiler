"""Qiskit integration: workload inference from Sampler/legacy results, and
OBSERVED calibration from a BackendV2 Target or IBM BackendProperties."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from ..inferred import FlipTally, QubitIdeal, flip_estimates, tally_marginal
from ..models import Estimate, Metric, Provenance, insufficient, utcnow

_SKIP = {"barrier", "delay"}
_DETERMINISTIC_TOL = 1e-9


class CircuitAnalysis:
    """Noiseless prediction for each measured qubit of one circuit.

    ``measured`` maps physical qubit -> (register name, index in register,
    global clbit index).
    """

    def __init__(self, measured: dict[int, tuple[str, int, int]], ideal: dict[int, QubitIdeal]):
        self.measured = measured
        self.ideal = ideal


_UNIT_NS = {"s": 1e9, "ms": 1e6, "us": 1e3, "ns": 1.0, "ps": 1e-3}


def analyze_circuit(circuit, max_sim_qubits: int = 16, context_mode: str = "bucket") -> CircuitAnalysis:
    from qiskit import QuantumCircuit
    from qiskit.circuit import ControlFlowOp
    from qiskit.quantum_info import Statevector

    measured: dict[int, tuple[str, int, int]] = {}
    n_1q: dict[int, int] = {}
    n_2q: dict[int, int] = {}
    names: dict[int, dict[str, int]] = {}
    idle_ns: dict[int, float] = {}
    idle_dt: dict[int, int] = {}
    gates: list[tuple[Any, list[int]]] = []
    problem = ""

    if circuit.parameters:
        problem = "circuit has unbound parameters"
    for inst in circuit.data:
        op = inst.operation
        qs = [circuit.find_bit(q).index for q in inst.qubits]
        if op.name == "delay":
            unit = getattr(op, "unit", "dt")
            dur = op.duration if getattr(op, "duration", None) is not None else op.params[0]
            for q in qs:
                if unit == "dt":
                    idle_dt[q] = idle_dt.get(q, 0) + int(dur)
                elif unit in _UNIT_NS:
                    idle_ns[q] = idle_ns.get(q, 0.0) + float(dur) * _UNIT_NS[unit]
                else:
                    raise ValueError(f"unsupported delay unit {unit!r}")
            continue
        if op.name in _SKIP:
            continue
        if any(q in measured for q in qs):
            problem = problem or "mid-circuit measurement or operation after measurement"
        if isinstance(op, ControlFlowOp):
            problem = problem or f"control flow ({op.name}) not supported"
        elif op.name == "measure":
            c = inst.clbits[0]
            loc = circuit.find_bit(c)
            reg, idx = (loc.registers[0][0].name, loc.registers[0][1]) if loc.registers else ("", loc.index)
            measured[qs[0]] = (reg, idx, loc.index)
        elif op.name == "reset":
            problem = problem or "reset is not supported by the ideal simulator"
        else:
            gates.append((op, qs))
            counter = n_1q if len(qs) == 1 else n_2q
            for q in qs:
                counter[q] = counter.get(q, 0) + 1
                names.setdefault(q, {})[op.name] = names.get(q, {}).get(op.name, 0) + 1

    def ideal_for(q: int, bit: int | None, reason: str = "") -> QubitIdeal:
        return QubitIdeal(
            bit,
            n_1q.get(q, 0),
            n_2q.get(q, 0),
            reason,
            tuple(sorted(names.get(q, {}).items())),
            idle_ns.get(q, 0.0),
            idle_dt.get(q, 0),
            context_mode,
        )

    if problem:
        return CircuitAnalysis(measured, {q: ideal_for(q, None, problem) for q in measured})

    active = sorted({q for _, qs in gates for q in qs} | set(measured))
    if len(active) > max_sim_qubits:
        reason = f"{len(active)} active qubits > max_sim_qubits={max_sim_qubits}"
        return CircuitAnalysis(measured, {q: ideal_for(q, None, reason) for q in measured})

    index = {q: i for i, q in enumerate(active)}
    reduced = QuantumCircuit(len(active))
    for op, qs in gates:
        reduced.append(op, [index[q] for q in qs])
    try:
        sv = Statevector.from_instruction(reduced)
    except Exception as exc:  # non-unitary or unsupported instruction
        reason = f"ideal simulation failed: {exc}"
        return CircuitAnalysis(measured, {q: ideal_for(q, None, reason) for q in measured})

    ideal: dict[int, QubitIdeal] = {}
    for q in measured:
        p1 = float(sv.probabilities([index[q]])[1])
        if p1 < _DETERMINISTIC_TOL:
            ideal[q] = ideal_for(q, 0)
        elif p1 > 1 - _DETERMINISTIC_TOL:
            ideal[q] = ideal_for(q, 1)
        else:
            ideal[q] = ideal_for(q, None, f"ideal outcome not deterministic (p1={p1:.3f})")
    return CircuitAnalysis(measured, ideal)


def _ones_by_position(counts: Mapping[str, int]) -> tuple[int, dict[int, int]]:
    """Shots and per-bit-position ones from little-endian bitstring counts.

    Raises ``ValueError`` on malformed results: non-binary keys, keys of
    different lengths, negative or non-integer counts, or no shots."""
    if not isinstance(counts, Mapping) or not counts:
        raise ValueError(f"counts must be a non-empty mapping, got {type(counts).__name__}")
    shots = 0
    ones: dict[int, int] = {}
    width = None
    for key, c in counts.items():
        if not isinstance(key, str):
            raise ValueError(f"count keys must be bitstrings, got {key!r}")
        bits = key.replace(" ", "")
        if not bits or set(bits) - {"0", "1"}:
            raise ValueError(f"malformed bitstring key {key!r} (hex keys are not supported; pass bitstring counts)")
        if width is None:
            width = len(bits)
        elif len(bits) != width:
            raise ValueError(f"inconsistent bitstring lengths in counts ({width} vs {len(bits)})")
        if isinstance(c, bool) or int(c) != c:
            raise ValueError(f"count for {key!r} must be an integer, got {c!r}")
        c = int(c)
        if c < 0:
            raise ValueError(f"negative count {c} for {key!r}")
        shots += c
        for pos, ch in enumerate(reversed(bits)):
            if ch == "1":
                ones[pos] = ones.get(pos, 0) + c
    if shots == 0:
        raise ValueError("counts contain no shots")
    return shots, ones


def infer_from_results(
    circuits: Iterable[Any],
    results: Iterable[Any],
    timestamp: datetime | None = None,
    source: str = "qiskit",
    min_shots: int = 200,
    max_sim_qubits: int = 16,
    context_mode: str = "bucket",
) -> list[Estimate]:
    """INFERRED effective-flip estimates from one batch (e.g. one job).

    ``results`` items may be SamplerV2 pub results (``.data`` with per-register
    BitArrays) or plain counts dicts as returned by ``Result.get_counts(i)``.
    Circuits must be the ones actually executed (post-transpilation, physical
    qubit indices), otherwise qubit labels are logical, not physical.
    """
    timestamp = timestamp or utcnow()
    tallies: dict[tuple[int, str], FlipTally] = {}
    unidentified: dict[int, str] = {}
    for circuit, res in zip(circuits, results, strict=True):
        an = analyze_circuit(circuit, max_sim_qubits, context_mode)
        if hasattr(res, "data"):  # SamplerV2 pub result
            per_reg: dict[str, tuple[int, dict[int, int]] | None] = {}
            for name in {reg for reg, _, _ in an.measured.values()}:
                bitarray = getattr(res.data, name, None)
                if bitarray is None or bitarray.shape != ():
                    per_reg[name] = None
                else:
                    per_reg[name] = _ones_by_position(bitarray.get_counts())
            lookup = lambda reg, idx, gidx: (
                None if (reg_tally := per_reg.get(reg)) is None else (reg_tally[0], reg_tally[1].get(idx, 0))
            )
        else:
            shots, ones = _ones_by_position(res)
            width = len(next(iter(res)).replace(" ", ""))
            if width != circuit.num_clbits:
                raise ValueError(
                    f"counts have {width} bits but the circuit has {circuit.num_clbits} classical bits: "
                    "results do not belong to this circuit"
                )
            lookup = lambda reg, idx, gidx: (shots, ones.get(gidx, 0))

        for q, (reg, idx, gidx) in an.measured.items():
            ideal = an.ideal[q]
            if ideal.bit is None:
                unidentified.setdefault(q, ideal.reason)
                continue
            got = lookup(reg, idx, gidx)
            if got is None:
                unidentified.setdefault(q, "result for register missing or parameter-swept")
                continue
            tally_marginal(tallies, q, ideal, *got)
    return flip_estimates(tallies, unidentified, timestamp, source, min_shots)


# --------------------------------------------------------------------------- OBSERVED

_OBSERVED_ASSUMPTIONS = ("vendor-reported value; measurement method and uncertainty not provided",)


def observe_target(target, timestamp: datetime | None = None, source: str = "qiskit-target") -> list[Estimate]:
    """OBSERVED estimates from a Qiskit ``Target`` (T1, T2, measure and gate errors).

    A Target carries no calibration timestamp; pass the time the calibration
    was taken if you know it, otherwise ingestion time is used.
    """
    timestamp = timestamp or utcnow()
    out: list[Estimate] = []
    qprops = target.qubit_properties or []
    for q in range(target.num_qubits):
        props = qprops[q] if q < len(qprops) else None
        for metric, attr in ((Metric.T1, "t1"), (Metric.T2, "t2")):
            val = getattr(props, attr, None) if props is not None else None
            if val is None:
                out.append(
                    insufficient(
                        metric,
                        (q,),
                        Provenance.OBSERVED,
                        f"backend reports no {attr.upper()}",
                        timestamp,
                        source=source,
                    )
                )
            else:
                out.append(
                    Estimate(
                        metric,
                        (q,),
                        Provenance.OBSERVED,
                        timestamp,
                        value=float(val),
                        source=source,
                        assumptions=_OBSERVED_ASSUMPTIONS,
                    )
                )
    for name in target.operation_names:
        if name in _SKIP or name in ("reset", "id"):
            continue
        for qargs, iprops in (target[name] or {}).items():
            if qargs is None or iprops is None or iprops.error is None:
                continue
            metric = Metric.READOUT_ERROR if name == "measure" else Metric.GATE_ERROR
            out.append(
                Estimate(
                    metric,
                    tuple(qargs),
                    Provenance.OBSERVED,
                    timestamp,
                    value=float(iprops.error),
                    context="" if name == "measure" else name,
                    source=source,
                    assumptions=_OBSERVED_ASSUMPTIONS,
                )
            )
    return out


def observe_backend(backend, source: str | None = None) -> list[Estimate]:
    """OBSERVED estimates from a BackendV2. Uses ``backend.properties()``'s
    ``last_update_date`` as the timestamp when available (IBM Runtime)."""
    ts = None
    props = getattr(backend, "properties", None)
    if callable(props):
        try:
            p = props()
            ts = getattr(p, "last_update_date", None)
        except Exception:
            ts = None
    return observe_target(backend.target, ts, source or f"qiskit:{backend.name}")
