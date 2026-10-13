"""MEASURED mode: dedicated characterization sequences with Bayesian fits.

T1: X, wait tau, measure.          P(1) = A*exp(-tau/T1) + B
T2: Hahn echo  SX, tau/2, X, tau/2, SX, measure.
                                   P(0) = A*exp(-tau/T2) + B
A and B absorb state-prep and readout error and are marginalized.

Readout probes: prepare |b> (nothing, or one X), measure. The flip rate is
the assignment error P(read 1-b | prepared b), reported as ``readout_error``
with context ``p(1|0)`` or ``p(0|1)``, the same contexts as the vendor's
``prob_meas1_prep0`` / ``prob_meas0_prep1``. Unlike a workload circuit's
effective flip rate, it does not change when the workload changes, so it is
the series an absolute recalibration threshold can be applied to.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np

from .models import Estimate, Metric, Provenance, Status, insufficient, utcnow
from .stats import DecayFit, FitDiagnosticsConfig, SweepReferences, beta_interval, fit_exponential_decay

T1_ASSUMPTIONS = (
    "single-exponential energy relaxation P1 = A exp(-t/T1) + B",
    "log-uniform prior on T1; uniform priors on A in [0.5,1], B in [0,0.2]",
)
T2_ASSUMPTIONS = (
    "Hahn echo; single-exponential decay P0 = A exp(-t/T2) + B",
    "log-uniform prior on T2; uniform priors on A in [0.2,0.55], B in [0.4,0.65]",
)
READOUT_CONTEXTS = {0: "p(1|0)", 1: "p(0|1)"}
READOUT_ASSUMPTIONS = (
    "dedicated prep-and-measure probe: P(read 1-b | prepared b); lumps state preparation, the X gate (b = 1) "
    "and assignment error, like the vendor's prob_meas1_prep0 / prob_meas0_prep1",
    "every qubit of the probe circuit is read out simultaneously (readout crosstalk included)",
    "shots are independent and the rate is constant within the batch",
)


def readout_probe_circuits(qubits: Sequence[int], num_qubits: int | None = None):
    """Two Qiskit circuits that prepare every qubit in ``qubits`` in |0> and
    in |1> (one X each) and measure them, one classical bit per qubit.

    Appended to a monitored job, their results become MEASURED
    ``readout_error`` estimates (``Profiler.ingest_qiskit`` recognises them
    by their structure). ``qubits`` index the circuit's qubits; for physical
    qubits, build the circuits on the device width and run them without a
    layout change (or pass the transpiled circuits)."""
    from qiskit import QuantumCircuit

    qs = [int(q) for q in qubits]
    if not qs or len(set(qs)) != len(qs) or min(qs) < 0:
        raise ValueError(f"need distinct non-negative qubit indices, got {list(qubits)!r}")
    n = max(qs) + 1 if num_qubits is None else int(num_qubits)
    if max(qs) >= n:
        raise ValueError(f"qubit {max(qs)} does not fit a {n}-qubit circuit")
    out = []
    for prep in (0, 1):
        qc = QuantumCircuit(n, len(qs), metadata={"qnp": "probe", "prep": prep})
        if prep:
            for q in qs:
                qc.x(q)
        for j, q in enumerate(qs):
            qc.measure(q, j)
        out.append(qc)
    return out


def estimate_readout(
    qubit: int,
    prepared: int,
    errors: int,
    shots: int,
    timestamp: datetime | None = None,
    source: str = "qnp-readout-probe",
    min_shots: int = 200,
    level: float = 0.95,
) -> Estimate:
    """MEASURED assignment error of one qubit from a readout probe:
    ``errors`` of ``shots`` read the wrong bit after preparing ``prepared``.
    Binomial counts are kept, so the threshold channel is exact."""
    if prepared not in READOUT_CONTEXTS:
        raise ValueError(f"prepared must be 0 or 1, got {prepared!r}")
    ctx = READOUT_CONTEXTS[prepared]
    ts = timestamp or utcnow()
    if shots < min_shots:
        return insufficient(
            Metric.READOUT_ERROR,
            (qubit,),
            Provenance.MEASURED,
            f"{shots} shots < min_shots={min_shots}",
            ts,
            successes=errors,
            trials=shots,
            context=ctx,
            source=source,
            assumptions=READOUT_ASSUMPTIONS,
        )
    mean, lo, hi = beta_interval(errors, shots, level)
    return Estimate(
        Metric.READOUT_ERROR,
        (qubit,),
        Provenance.MEASURED,
        ts,
        Status.OK,
        mean,
        lo,
        hi,
        level,
        successes=errors,
        trials=shots,
        context=ctx,
        source=source,
        assumptions=READOUT_ASSUMPTIONS,
    )


def t1_circuits(delays_s: Sequence[float]):
    from qiskit import QuantumCircuit

    out = []
    for tau in delays_s:
        qc = QuantumCircuit(1, 1, metadata={"qnp": "t1", "delay_s": float(tau)})
        qc.x(0)
        qc.delay(float(tau), 0, unit="s")
        qc.measure(0, 0)
        out.append(qc)
    return out


def t2_echo_circuits(delays_s: Sequence[float]):
    from qiskit import QuantumCircuit

    out = []
    for tau in delays_s:
        qc = QuantumCircuit(1, 1, metadata={"qnp": "t2_echo", "delay_s": float(tau)})
        qc.sx(0)
        qc.delay(float(tau) / 2, 0, unit="s")
        qc.x(0)
        qc.delay(float(tau) / 2, 0, unit="s")
        qc.sx(0)
        qc.measure(0, 0)
        out.append(qc)
    return out


# --------------------------------------------------------------------------- sweep design


@dataclass(frozen=True)
class DecaySweepPlan:
    """Acquisition plan of a T1 or T2 sweep: ``slots[j]`` is the circuit
    acquired j-th, either ``("delay", i)`` (the sweep point ``delays_s[i]``)
    or ``("reference", r)`` (the r-th ground reference: prepare |0>, measure).

    A slow measurement drift adds a smooth offset along the acquisition. When
    delays are acquired in delay order that offset bends the decay curve and
    the fit absorbs it (v0.2 Experiment D11: 28.5% confidently wrong T1).
    Acquiring the delays in random order turns it into scatter that the
    goodness-of-fit checks can see, and ground references spread over the
    acquisition measure it directly: their outcome probability does not depend
    on T1 or T2 at all."""

    delays_s: tuple[float, ...]
    slots: tuple[tuple[str, int], ...]
    seed: int | None = None

    def __post_init__(self) -> None:
        d = sorted(i for kind, i in self.slots if kind == "delay")
        r = sorted(i for kind, i in self.slots if kind == "reference")
        if any(kind not in ("delay", "reference") for kind, _ in self.slots):
            raise ValueError("slots must be ('delay', i) or ('reference', r)")
        if d != list(range(len(self.delays_s))) or r != list(range(len(r))):
            raise ValueError("every delay must be acquired exactly once and references numbered 0..K-1")

    @property
    def n_references(self) -> int:
        return sum(kind == "reference" for kind, _ in self.slots)

    def delay_positions(self) -> tuple[int, ...]:
        """Acquisition position of each sweep delay, aligned with ``delays_s``."""
        pos = {i: j for j, (kind, i) in enumerate(self.slots) if kind == "delay"}
        return tuple(pos[i] for i in range(len(self.delays_s)))

    def reference_positions(self) -> tuple[int, ...]:
        pos = {i: j for j, (kind, i) in enumerate(self.slots) if kind == "reference"}
        return tuple(pos[i] for i in range(len(pos)))

    @property
    def randomized(self) -> bool:
        """True when the acquisition order is not monotone in delay."""
        by_time = np.asarray(self.delays_s)[np.argsort(self.delay_positions())]
        return not (np.all(np.diff(by_time) >= 0) or np.all(np.diff(by_time) <= 0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "delays_s": list(self.delays_s),
            "slots": [list(x) for x in self.slots],
            "seed": self.seed,
            "n_references": self.n_references,
            "randomized": self.randomized,
        }


def decay_sweep_plan(
    delays_s: Sequence[float], n_references: int = 5, randomize: bool = True, seed: int | None = None
) -> DecaySweepPlan:
    """Sweep delays in random acquisition order with ``n_references`` ground
    references spread evenly over the acquisition, first and last position
    included. ``n_references=0, randomize=False`` is the v0.2 design (delays
    acquired in the order given)."""
    delays = tuple(float(x) for x in delays_s)
    if len(delays) < 3:
        raise ValueError("a decay sweep needs at least 3 delays")
    if not isinstance(n_references, int) or n_references < 0 or n_references == 1:
        raise ValueError("n_references must be 0 or an int >= 2 (one reference cannot show drift)")
    order = np.random.default_rng(seed).permutation(len(delays)) if randomize else np.arange(len(delays))
    total = len(delays) + n_references
    ref_at = [int(x) for x in np.round(np.linspace(0, total - 1, n_references))] if n_references else []
    if len(set(ref_at)) != len(ref_at):
        raise ValueError(f"{n_references} references do not fit {len(delays)} delays")
    slots: list[tuple[str, int]] = []
    it = iter(int(i) for i in order)
    refs = iter(range(n_references))
    for j in range(total):
        slots.append(("reference", next(refs)) if j in ref_at else ("delay", next(it)))
    return DecaySweepPlan(delays, tuple(slots), seed)


V02_SWEEP = {"n_references": 0, "randomize": False}  # decay_sweep_plan(delays, **V02_SWEEP): the v0.2 design


def ground_reference_circuit():
    """Prepare |0> and measure: the reference interleaved in decay sweeps."""
    from qiskit import QuantumCircuit

    qc = QuantumCircuit(1, 1, metadata={"qnp": "reference", "prep": 0})
    qc.measure(0, 0)
    return qc


def decay_plan_circuits(plan: DecaySweepPlan, kind: str = "t1"):
    """Qiskit circuits of ``plan`` in acquisition order (``kind`` = ``t1`` or
    ``t2_echo``); each carries its slot and index in ``metadata``."""
    if kind not in ("t1", "t2_echo"):
        raise ValueError("kind must be 't1' or 't2_echo'")
    sweep = t1_circuits(plan.delays_s) if kind == "t1" else t2_echo_circuits(plan.delays_s)
    out = []
    for j, (what, i) in enumerate(plan.slots):
        c = sweep[i].copy() if what == "delay" else ground_reference_circuit()
        c.metadata = {**(c.metadata or {}), "slot": j, "index": i}
        out.append(c)
    return out


def _plan_counts(
    plan: DecaySweepPlan, ones: Sequence[int], shots
) -> tuple[list[int], list[int], SweepReferences | None]:
    """Split per-circuit counts of outcome 1 (acquisition order) into the sweep
    points (aligned with ``plan.delays_s``) and the references."""
    ones = [int(x) for x in ones]
    if len(ones) != len(plan.slots):
        raise ValueError(f"{len(ones)} counts for a plan of {len(plan.slots)} circuits")
    n = [int(x) for x in np.broadcast_to(np.asarray(shots), (len(ones),))]
    k_d, n_d = [0] * len(plan.delays_s), [0] * len(plan.delays_s)
    rk, rn = [0] * plan.n_references, [0] * plan.n_references
    for j, (what, i) in enumerate(plan.slots):
        if what == "delay":
            k_d[i], n_d[i] = ones[j], n[j]
        else:
            rk[i], rn[i] = ones[j], n[j]
    refs = SweepReferences(plan.reference_positions(), tuple(rk), tuple(rn)) if plan.n_references else None
    return k_d, n_d, refs


def _estimate(metric, qubit, fit, timestamp, source, assumptions) -> Estimate:
    diagnostics = {**fit.diagnostics, "reasons": [r.to_dict() for r in fit.reasons]}
    diagnostics.pop("pearson_residuals", None) if len(diagnostics.get("pearson_residuals", [])) > 64 else None
    if not fit.ok:
        status = (
            Status.MODEL_MISSPECIFICATION if fit.status == "model_misspecification" else Status.INSUFFICIENT_EVIDENCE
        )
        return Estimate(
            metric,
            (qubit,),
            Provenance.MEASURED,
            timestamp,
            status,
            None,
            reason=fit.reason,
            source=source,
            assumptions=assumptions,
            diagnostics=diagnostics,
        )
    return Estimate(
        metric,
        (qubit,),
        Provenance.MEASURED,
        timestamp,
        Status.OK,
        fit.median,
        fit.ci_low,
        fit.ci_high,
        fit.level,
        source=source,
        assumptions=assumptions,
        diagnostics=diagnostics,
    )


# (amplitude range, offset range) of the marginalized SPAM parameters
_RANGES: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {
    "t1": ((0.5, 1.0), (0.0, 0.2)),
    "t2_echo": ((0.2, 0.55), (0.4, 0.65)),
}


def estimate_t1(
    qubit: int,
    delays_s,
    ones,
    shots,
    timestamp: datetime | None = None,
    source: str = "qnp-t1",
    diagnostics: FitDiagnosticsConfig | bool = True,
    *,
    acquisition_positions=None,
    references: SweepReferences | None = None,
) -> Estimate:
    """T1 from a relaxation sweep. ``status`` is OK only when the single-
    exponential model passes its checks; otherwise INSUFFICIENT_EVIDENCE
    (delays do not resolve T1) or MODEL_MISSPECIFICATION (the data contradict
    a single exponential, or the measurement drifted during the sweep), with
    machine-readable reasons in ``diagnostics``. ``acquisition_positions``
    and ``references`` enable the drift checks (see ``estimate_t1_from_plan``)."""
    fit = fit_exponential_decay(
        np.asarray(delays_s),
        np.asarray(ones),
        shots,
        amp_range=_RANGES["t1"][0],
        offset_range=_RANGES["t1"][1],
        diagnostics=diagnostics,
        acquisition_positions=acquisition_positions,
        references=references,
    )
    return _estimate(Metric.T1, qubit, fit, timestamp or utcnow(), source, T1_ASSUMPTIONS)


def estimate_t2_echo(
    qubit: int,
    delays_s,
    zeros,
    shots,
    timestamp: datetime | None = None,
    source: str = "qnp-t2-echo",
    diagnostics: FitDiagnosticsConfig | bool = True,
    *,
    acquisition_positions=None,
    references: SweepReferences | None = None,
) -> Estimate:
    fit = fit_exponential_decay(
        np.asarray(delays_s),
        np.asarray(zeros),
        shots,
        amp_range=_RANGES["t2_echo"][0],
        offset_range=_RANGES["t2_echo"][1],
        diagnostics=diagnostics,
        acquisition_positions=acquisition_positions,
        references=references,
    )
    return _estimate(Metric.T2, qubit, fit, timestamp or utcnow(), source, T2_ASSUMPTIONS)


def _fit_plan(plan, ones, shots, kind, diagnostics) -> DecayFit:
    k_d, n_d, refs = _plan_counts(plan, ones, shots)
    if kind == "t2_echo":
        k_d = [n - k for k, n in zip(k_d, n_d)]  # the echo decay is fitted on P(0)
    fit = fit_exponential_decay(
        np.asarray(plan.delays_s),
        np.asarray(k_d),
        np.asarray(n_d),
        amp_range=_RANGES[kind][0],
        offset_range=_RANGES[kind][1],
        diagnostics=diagnostics,
        acquisition_positions=plan.delay_positions(),
        references=refs,
    )
    fit.diagnostics["sweep_plan"] = plan.to_dict()
    return fit


def estimate_t1_from_plan(
    qubit: int,
    plan: DecaySweepPlan,
    ones: Sequence[int],
    shots,
    timestamp: datetime | None = None,
    source: str = "qnp-t1",
    diagnostics: FitDiagnosticsConfig | bool = True,
) -> Estimate:
    """T1 from the circuits of ``plan`` (``decay_plan_circuits``): ``ones[j]``
    counts outcome 1 in the j-th acquired circuit. The fit sees the
    acquisition order and the ground references, so measurement drift during
    the sweep is reported as MODEL_MISSPECIFICATION (``READOUT_DRIFT``,
    ``ACQUISITION_RUNS``) instead of bending the T1 estimate."""
    fit = _fit_plan(plan, ones, shots, "t1", diagnostics)
    return _estimate(Metric.T1, qubit, fit, timestamp or utcnow(), source, T1_ASSUMPTIONS)


def estimate_t2_echo_from_plan(
    qubit: int,
    plan: DecaySweepPlan,
    ones: Sequence[int],
    shots,
    timestamp: datetime | None = None,
    source: str = "qnp-t2-echo",
    diagnostics: FitDiagnosticsConfig | bool = True,
) -> Estimate:
    """Hahn-echo T2 from the circuits of ``plan``; ``ones[j]`` counts outcome
    1 in the j-th acquired circuit (the decay is fitted on outcome 0)."""
    fit = _fit_plan(plan, ones, shots, "t2_echo", diagnostics)
    return _estimate(Metric.T2, qubit, fit, timestamp or utcnow(), source, T2_ASSUMPTIONS)


def _run_plan(backend, qubit, plan, kind, shots, seed):
    from qiskit import transpile

    circs = transpile(decay_plan_circuits(plan, kind), backend, initial_layout=[qubit], optimization_level=0)
    res = backend.run(circs, shots=shots, seed_simulator=seed).result()
    return [res.get_counts(i).get("1", 0) for i in range(len(circs))]


def run_t1(
    backend,
    qubit: int,
    delays_s,
    shots: int = 1000,
    seed: int | None = None,
    timestamp: datetime | None = None,
    plan: DecaySweepPlan | None = None,
) -> Estimate:
    """Run a T1 sweep on ``backend`` (anything with ``.run``, e.g. AerSimulator).

    By default the delays are acquired in random order with 5 interleaved
    ground references (``decay_sweep_plan(delays_s, seed=seed)``); pass
    ``plan=decay_sweep_plan(delays_s, **V02_SWEEP)`` for the v0.2 design."""
    plan = plan or decay_sweep_plan(delays_s, seed=seed)
    if not np.allclose(plan.delays_s, np.asarray(delays_s, float)):
        raise ValueError("plan.delays_s differ from delays_s")
    ones = _run_plan(backend, qubit, plan, "t1", shots, seed)
    return estimate_t1_from_plan(qubit, plan, ones, shots, timestamp)


def run_t2_echo(
    backend,
    qubit: int,
    delays_s,
    shots: int = 1000,
    seed: int | None = None,
    timestamp: datetime | None = None,
    plan: DecaySweepPlan | None = None,
) -> Estimate:
    """Run a Hahn-echo sweep; same design defaults as ``run_t1``."""
    plan = plan or decay_sweep_plan(delays_s, seed=seed)
    if not np.allclose(plan.delays_s, np.asarray(delays_s, float)):
        raise ValueError("plan.delays_s differ from delays_s")
    ones = _run_plan(backend, qubit, plan, "t2_echo", shots, seed)
    return estimate_t2_echo_from_plan(qubit, plan, ones, shots, timestamp)
