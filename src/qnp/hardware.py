"""IBM Quantum validation pathway: read-only by default, budgeted, auditable.

Nothing in this module submits a job unless *all* of the following hold:

1. the session was created with ``dry_run=False`` **and** ``allow_submission=True``;
2. the call passes ``authorize=True`` for that specific plan;
3. the plan fits the session's ``JobBudget`` (jobs, shots, circuits,
   estimated QPU seconds), counting everything already submitted.

Reading calibration data (``backend.properties()``, ``backend.target``) is
always allowed and never consumes QPU time. No function here triggers, or
can trigger, a physical recalibration: Qiskit Runtime exposes no such call,
and the profiler's ``mark_recalibrated`` only records that one happened.

Every snapshot and submission records backend identity and version, the
per-property calibration timestamps reported by the backend, execution
timestamps from ``job.metrics()``, physical qubit indices and the software
versions in use.

Vendor calibration values are *not* ground truth: they are point estimates
from the vendor's own procedure (method, fit model and uncertainty not
reported), taken at a time that may be hours before the job, and often on a
schedule unrelated to the workload. See docs/HARDWARE_VALIDATION.md.
"""

from __future__ import annotations

import platform
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from importlib import metadata
from typing import Any

import numpy as np

from .measured import DecaySweepPlan
from .models import Estimate, Metric, Provenance, insufficient

__all__ = [
    "BudgetExceeded",
    "CharacterizationPlan",
    "HardwareSession",
    "JobBudget",
    "SubmissionRefused",
    "align_delays",
    "backend_snapshot",
    "delay_grid_seconds",
    "estimates_from_sweep_job",
    "estimates_from_t1_job",
    "observe_ibm_backend",
    "plan_characterization",
    "software_versions",
]

VENDOR_ASSUMPTIONS = (
    "vendor-reported value; measurement method, fit model and uncertainty not provided",
    "timestamp is the vendor's calibration time for this property, not the execution time of any job",
)


class SubmissionRefused(RuntimeError):
    """Raised when a job would be submitted without explicit authorization."""


class BudgetExceeded(RuntimeError):
    """Raised when a plan does not fit the remaining job budget."""


def software_versions() -> dict[str, str | None]:
    out: dict[str, str | None] = {"python": sys.version.split()[0], "platform": platform.platform()}
    for name in ("quantum-noise-profiler", "qiskit", "qiskit-ibm-runtime", "qiskit-aer", "numpy", "scipy"):
        try:
            out[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            out[name] = None
    return out


def _iso(x) -> str | None:
    if x is None:
        return None
    if isinstance(x, datetime):
        if x.tzinfo is None:
            raise ValueError(f"backend reported a naive timestamp {x!r}")
        return x.isoformat()
    return str(x)


def _is_local(backend) -> bool:
    """True for fake/local backends (no QPU time is consumed)."""
    mod = type(backend).__module__
    return "fake_provider" in mod or "qiskit_aer" in mod or mod.startswith("qiskit.providers.fake")


# --------------------------------------------------------------------------- read-only snapshot


def backend_snapshot(backend, qubits: Sequence[int] | None = None) -> dict[str, Any]:
    """Read-only record of what the backend reports about itself.

    Missing metadata is recorded as missing (``None`` plus an entry in
    ``missing``), never filled in."""
    retrieved = datetime.now(timezone.utc)
    snap: dict[str, Any] = {
        "retrieved_at": retrieved.isoformat(),
        "backend_name": getattr(backend, "name", None),
        "backend_version": getattr(backend, "backend_version", None),
        "backend_class": f"{type(backend).__module__}.{type(backend).__name__}",
        "local_simulation": _is_local(backend),
        "num_qubits": getattr(backend, "num_qubits", None),
        "software": software_versions(),
        "missing": [],
        "qubits": {},
        "gates": {},
    }
    cfg = None
    try:
        cfg = backend.configuration()
    except Exception:  # BackendV2 without a configuration
        snap["missing"].append("configuration")
    if cfg is not None:
        snap["processor_type"] = getattr(cfg, "processor_type", None)
        snap["dt_s"] = getattr(cfg, "dt", None)
        snap["default_rep_delay_s"] = getattr(cfg, "default_rep_delay", None)
    props = None
    try:
        props = backend.properties()
    except Exception:
        props = None
    if props is None:
        snap["missing"].append("properties")
        snap["last_update_date"] = None
    else:
        snap["last_update_date"] = _iso(getattr(props, "last_update_date", None))
    n = snap["num_qubits"] or 0
    qs = list(range(n)) if qubits is None else [_physical_index(q) for q in qubits]
    for q in qs:
        if not 0 <= q < n:
            raise ValueError(f"physical qubit {q} does not exist on {snap['backend_name']} ({n} qubits)")
        entry: dict[str, Any] = {}
        if props is not None:
            try:
                for key, (val, ts) in props.qubit_property(q).items():
                    entry[key] = {"value": float(val), "calibrated_at": _iso(ts)}
            except Exception as exc:
                entry["error"] = f"qubit_property failed: {exc}"
        tq = (backend.target.qubit_properties or [None] * n)[q] if hasattr(backend, "target") else None
        if tq is not None:
            entry["target_t1_s"] = getattr(tq, "t1", None)
            entry["target_t2_s"] = getattr(tq, "t2", None)
        snap["qubits"][str(q)] = entry
    if props is not None:
        for g in getattr(props, "gates", []) or []:
            qa = tuple(g.qubits)
            if qubits is not None and not set(qa) <= set(qs):
                continue
            rec = {p.name: {"value": float(p.value), "calibrated_at": _iso(p.date)} for p in g.parameters}
            snap["gates"][f"{g.gate}{list(qa)}"] = rec
    return snap


def observe_ibm_backend(backend, qubits: Sequence[int] | None = None, source: str | None = None) -> list[Estimate]:
    """OBSERVED estimates with each property's own calibration timestamp.

    Unlike ``observe_backend`` (which stamps every value with
    ``last_update_date``), this uses the per-property dates that IBM
    ``BackendProperties`` carries, and records the asymmetric readout
    probabilities P(1|0) and P(0|1) as separate READOUT_ERROR contexts."""
    snap = backend_snapshot(backend, qubits)
    src = source or f"ibm:{snap['backend_name']}@{snap['backend_version']}"
    now = datetime.now(timezone.utc)
    out: list[Estimate] = []
    mapping = {
        "T1": (Metric.T1, ""),
        "T2": (Metric.T2, ""),
        "readout_error": (Metric.READOUT_ERROR, ""),
        "prob_meas1_prep0": (Metric.READOUT_ERROR, "p(1|0)"),
        "prob_meas0_prep1": (Metric.READOUT_ERROR, "p(0|1)"),
    }
    for qs, entry in snap["qubits"].items():
        q = int(qs)
        for key, (metric, ctx) in mapping.items():
            rec = entry.get(key)
            if rec is None:
                if not ctx:
                    out.append(
                        insufficient(
                            metric, (q,), Provenance.OBSERVED, f"backend reports no {key}", now, source=src, context=ctx
                        )
                    )
                continue
            ts = datetime.fromisoformat(rec["calibrated_at"]) if rec["calibrated_at"] else now
            val = rec["value"]
            if not np.isfinite(val) or (metric in (Metric.T1, Metric.T2) and val <= 0):
                out.append(
                    insufficient(
                        metric,
                        (q,),
                        Provenance.OBSERVED,
                        f"backend reports invalid {key}={val}",
                        ts,
                        source=src,
                        context=ctx,
                    )
                )
                continue
            out.append(
                Estimate(
                    metric,
                    (q,),
                    Provenance.OBSERVED,
                    ts,
                    value=float(val),
                    context=ctx,
                    source=src,
                    assumptions=VENDOR_ASSUMPTIONS,
                )
            )
    return out


# --------------------------------------------------------------------------- budgets and plans


@dataclass
class JobBudget:
    max_jobs: int = 0
    max_total_shots: int = 0
    max_circuits_per_job: int = 300
    max_estimated_qpu_seconds: float = 0.0

    def __post_init__(self) -> None:
        for name in ("max_jobs", "max_total_shots", "max_circuits_per_job"):
            v = getattr(self, name)
            if not isinstance(v, int) or v < 0:
                raise ValueError(f"{name} must be a non-negative int")
        if self.max_estimated_qpu_seconds < 0:
            raise ValueError("max_estimated_qpu_seconds must be >= 0")


@dataclass
class CharacterizationPlan:
    kind: str
    backend_name: str
    physical_qubits: list[int]
    delays_s: list[float]
    shots: int
    circuits: list[Any] = field(repr=False)
    estimated_qpu_seconds: float = 0.0
    notes: list[str] = field(default_factory=list)
    # acquisition plan of each qubit's t1 / t2_echo sweep (random delay order,
    # ground references); the circuits follow them, qubit after qubit
    sweeps: dict[int, DecaySweepPlan] | None = None
    parallel: bool = False  # probes: all qubits in the same two circuits

    @property
    def sweep(self) -> DecaySweepPlan | None:
        """The sweep plan shared by every qubit (None if they differ or for probes)."""
        if not self.sweeps:
            return None
        plans = list(self.sweeps.values())
        return plans[0] if all(p == plans[0] for p in plans) else None

    @property
    def n_circuits(self) -> int:
        return len(self.circuits)

    @property
    def total_shots(self) -> int:
        return self.n_circuits * self.shots

    def summary(self) -> dict[str, Any]:
        d = {k: v for k, v in asdict(self).items() if k not in ("circuits", "sweeps")}
        d.update(n_circuits=self.n_circuits, total_shots=self.total_shots)
        d["sweep"] = None if self.sweep is None else self.sweep.to_dict()
        d["sweeps"] = None if not self.sweeps else {str(q): p.to_dict() for q, p in self.sweeps.items()}
        return d


def _estimate_seconds(backend, circuits, shots: int) -> float:
    """Crude upper estimate of QPU time: per shot, the longest circuit
    duration plus the repetition delay and measurement; per job, a fixed
    overhead. It is a budgeting guard, not a billing prediction."""
    try:
        rep = float(backend.configuration().default_rep_delay)
    except Exception:
        rep = 250e-6
    try:
        meas = float(backend.target["measure"][(0,)].duration or 1e-6)
    except Exception:
        meas = 2e-6
    per_circ = []
    for c in circuits:
        d = sum(
            float(inst.operation.duration or 0.0) if getattr(inst.operation, "unit", "s") == "s" else 0.0
            for inst in c.data
            if inst.operation.name == "delay"
        )
        per_circ.append(d + meas + rep)
    return float(sum(per_circ) * shots + 5.0)


def delay_grid_seconds(backend) -> float | None:
    """Smallest delay step the backend accepts: dt times the least common
    multiple of its granularity and pulse/acquire alignment (IBM backends
    reject delays off this grid). None if the backend reports no dt."""
    import math

    target = getattr(backend, "target", None)
    dt = getattr(target, "dt", None) or getattr(backend, "dt", None)
    if not dt:
        return None
    try:
        tc = target.timing_constraints()  # type: ignore[union-attr]
        step = math.lcm(int(tc.granularity), int(tc.pulse_alignment), int(tc.acquire_alignment))
    except Exception:
        step = 1
    return float(dt) * step


def align_delays(backend, delays_s: Sequence[float], parts: int = 1) -> list[float]:
    """Round each delay to the backend's delay grid (``parts`` equal pieces
    each on the grid, e.g. 2 for the two halves of a Hahn echo), so that the
    delays the device executes are the ones the fit uses."""
    grid = delay_grid_seconds(backend)
    if grid is None:
        return [float(d) for d in delays_s]
    step = grid * parts
    return [float(round(float(d) / step) * step) for d in delays_s]


def _physical_index(q) -> int:
    """A physical qubit index exactly as given: a non-boolean integer. Floats,
    strings and booleans are rejected rather than coerced, so a job can never
    be laid out on a different qubit than the caller wrote."""
    if isinstance(q, bool) or not isinstance(q, (int, np.integer)):
        raise ValueError(f"physical qubit identifiers must be integers, got {q!r} ({type(q).__name__})")
    return int(q)


def plan_characterization(
    backend,
    kind: str,
    physical_qubits: Sequence[int],
    delays_s: Sequence[float] | Mapping[int, Sequence[float]] = (),
    shots: int = 1000,
    *,
    n_references: int = 5,
    randomize: bool = True,
    seed: int | None = None,
    parallel: bool = False,
) -> CharacterizationPlan:
    """Build (but do not run) ISA circuits for T1, Hahn-echo T2 or basis-state
    probes on explicit physical qubits.

    Sweeps follow ``qnp.measured.decay_sweep_plan(delays, n_references,
    randomize, seed)``: delays in random order with interleaved ground
    references, so that readout drift during the sweep is detectable
    (``n_references=0, randomize=False`` is the v0.2 design). ``delays_s``
    may map each physical qubit to its own delays (e.g. scaled to its vendor
    T1). ``parallel=True`` (probes only) prepares and reads every qubit in
    the same two circuits (``qnp.measured.readout_probe_circuits``)."""
    from qiskit import QuantumCircuit, transpile

    from .measured import decay_plan_circuits, decay_sweep_plan, readout_probe_circuits

    if kind not in ("t1", "t2_echo", "probe"):
        raise ValueError("kind must be 't1', 't2_echo' or 'probe'")
    if shots <= 0 or not isinstance(shots, int):
        raise ValueError("shots must be a positive int")
    if parallel and kind != "probe":
        raise ValueError("parallel=True is only supported for probes")
    n = backend.num_qubits
    qs = [_physical_index(q) for q in physical_qubits]
    if len(set(qs)) != len(qs) or any(not 0 <= q < n for q in qs):
        raise ValueError(f"invalid physical qubits {physical_qubits} for a {n}-qubit backend")
    per_qubit = isinstance(delays_s, Mapping)
    if isinstance(delays_s, Mapping):
        if set(delays_s) != set(qs):
            raise ValueError("per-qubit delays must be given for exactly the planned qubits")
        delays_of = {q: [float(x) for x in delays_s[q]] for q in qs}
    else:
        delays_of = {q: [float(x) for x in delays_s] for q in qs}
    if kind != "probe" and any(len(d) < 3 or any(x < 0 for x in d) for d in delays_of.values()):
        raise ValueError("decay characterization needs >= 3 non-negative delays")
    grid = delay_grid_seconds(backend)
    if kind != "probe":
        delays_of = {q: align_delays(backend, d, 2 if kind == "t2_echo" else 1) for q, d in delays_of.items()}
        if any(len(set(d)) < 3 for d in delays_of.values()):
            raise ValueError("fewer than 3 distinct delays remain on the backend's delay grid")
    sweeps = None if kind == "probe" else {q: decay_sweep_plan(delays_of[q], n_references, randomize, seed) for q in qs}
    circuits = []
    if parallel:
        circuits = transpile(
            readout_probe_circuits(qs, num_qubits=n), backend, initial_layout=list(range(n)), optimization_level=0
        )
        for c in circuits:
            c.metadata = {**(c.metadata or {}), "physical_qubits": qs}
    for q in [] if parallel else qs:
        if sweeps is not None:
            logical = decay_plan_circuits(sweeps[q], kind)
        else:
            z = QuantumCircuit(1, 1, metadata={"qnp": "probe", "prep": 0})
            z.measure(0, 0)
            o = QuantumCircuit(1, 1, metadata={"qnp": "probe", "prep": 1})
            o.x(0)
            o.measure(0, 0)
            logical = [z, o]
        isa = transpile(logical, backend, initial_layout=[q], optimization_level=0)
        for c in isa:
            c.metadata = {**(c.metadata or {}), "physical_qubit": q}
        circuits += isa
    notes = []
    if kind != "probe" and grid is not None:
        notes.append(f"delays rounded to the backend's delay grid ({grid:.4g} s); the fit uses the rounded delays")
    if kind == "t2_echo":
        notes.append("Hahn echo T2 is not T2* (Ramsey); IBM's reported T2 is Hahn echo")
    if sweeps is not None and not all(p.randomized for p in sweeps.values()):
        notes.append("delays acquired in delay order: measurement drift during the sweep cannot be detected")
    common = [] if per_qubit or not qs else delays_of[qs[0]]
    plan = CharacterizationPlan(kind, backend.name, qs, common, shots, circuits, 0.0, notes, sweeps, parallel)
    plan.estimated_qpu_seconds = _estimate_seconds(backend, circuits, shots)
    return plan


# --------------------------------------------------------------------------- session


@dataclass
class HardwareSession:
    """Guards every interaction with a (possibly real) backend.

    Defaults are the safe ones: ``dry_run=True``, ``allow_submission=False``,
    a zero budget."""

    backend: Any
    dry_run: bool = True
    allow_submission: bool = False
    budget: JobBudget = field(default_factory=JobBudget)
    log: list[dict[str, Any]] = field(default_factory=list)
    _jobs: int = 0
    _shots: int = 0
    _seconds: float = 0.0

    def snapshot(self, qubits: Sequence[int] | None = None) -> dict[str, Any]:
        snap = backend_snapshot(self.backend, qubits)
        self.log.append(
            {
                "event": "snapshot",
                "at": snap["retrieved_at"],
                "backend": snap["backend_name"],
                "last_update_date": snap["last_update_date"],
            }
        )
        return snap

    def check_budget(self, plan: CharacterizationPlan) -> None:
        b = self.budget
        problems = []
        if self._jobs + 1 > b.max_jobs:
            problems.append(f"jobs {self._jobs + 1} > max_jobs {b.max_jobs}")
        if self._shots + plan.total_shots > b.max_total_shots:
            problems.append(f"shots {self._shots + plan.total_shots} > max_total_shots {b.max_total_shots}")
        if plan.n_circuits > b.max_circuits_per_job:
            problems.append(f"circuits {plan.n_circuits} > max_circuits_per_job {b.max_circuits_per_job}")
        if self._seconds + plan.estimated_qpu_seconds > b.max_estimated_qpu_seconds:
            problems.append(
                f"estimated QPU s {self._seconds + plan.estimated_qpu_seconds:.1f} > {b.max_estimated_qpu_seconds}"
            )
        if problems:
            raise BudgetExceeded("; ".join(problems))

    def submit(self, plan: CharacterizationPlan, authorize: bool = False) -> dict[str, Any]:
        """Run a characterization plan, or describe what would run.

        In dry-run mode (the default) nothing is sent; the returned record
        says what would have been submitted and whether it fits the budget."""
        record: dict[str, Any] = {
            "plan": plan.summary(),
            "software": software_versions(),
            "requested_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self.check_budget(plan)
            record["budget_ok"] = True
        except BudgetExceeded as exc:
            record["budget_ok"] = False
            record["budget_problem"] = str(exc)
        if self.dry_run:
            record["status"] = "dry_run"
            self.log.append({"event": "dry_run", **record})
            return record
        if not self.allow_submission:
            raise SubmissionRefused("session does not allow submission (allow_submission=False)")
        if not authorize:
            raise SubmissionRefused("submission requires authorize=True for this plan")
        if not record["budget_ok"]:
            raise BudgetExceeded(record["budget_problem"])
        from qiskit_ibm_runtime import SamplerV2

        record["snapshot_before"] = backend_snapshot(self.backend, plan.physical_qubits)
        sampler = SamplerV2(mode=self.backend)
        job = sampler.run(plan.circuits, shots=plan.shots)
        self._jobs += 1
        self._shots += plan.total_shots
        self._seconds += plan.estimated_qpu_seconds
        record["job_id"] = job.job_id()
        record["status"] = "submitted"
        record["local_simulation"] = _is_local(self.backend)
        self.log.append({"event": "submitted", "job_id": record["job_id"], "plan": plan.summary()})
        record["job"] = job
        return record


def execution_timestamps(job) -> dict[str, bool | str | None]:
    """Execution timestamps from ``job.metrics()`` when the service provides
    them. Local/fake jobs have none; that is reported, not invented."""
    try:
        m = job.metrics()
    except Exception as exc:
        return {"available": False, "reason": f"job.metrics() failed: {exc}"}
    ts = (m or {}).get("timestamps") or {}
    return {
        "available": bool(ts),
        "created": ts.get("created"),
        "running": ts.get("running"),
        "finished": ts.get("finished"),
    }


def _ones(pub) -> int:
    bits = next(iter(pub.data.values())) if hasattr(pub.data, "values") else pub.data.c
    return sum(v for k, v in bits.get_counts().items() if k.endswith("1"))


def estimates_from_sweep_job(plan: CharacterizationPlan, result, timestamp: datetime) -> list[Estimate]:
    """MEASURED T1 or Hahn-echo T2 per physical qubit from a SamplerV2 result
    of a ``t1`` or ``t2_echo`` plan, with the drift checks of its sweep plan."""
    from .measured import estimate_t1_from_plan, estimate_t2_echo_from_plan

    if plan.kind not in ("t1", "t2_echo") or not plan.sweeps:
        raise ValueError("plan is not a decay-sweep plan")
    if timestamp.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    fn = estimate_t1_from_plan if plan.kind == "t1" else estimate_t2_echo_from_plan
    out, offset = [], 0
    for q in plan.physical_qubits:
        sw = plan.sweeps[q]
        ones = [_ones(result[offset + j]) for j in range(len(sw.slots))]
        offset += len(sw.slots)
        out.append(fn(q, sw, ones, plan.shots, timestamp, source=f"qnp-{plan.kind}@{plan.backend_name}"))
    return out


def estimates_from_t1_job(plan: CharacterizationPlan, result, timestamp: datetime) -> list[Estimate]:
    """MEASURED T1 per physical qubit from a SamplerV2 result of a t1 plan."""
    if plan.kind != "t1":
        raise ValueError("plan is not a T1 plan")
    return estimates_from_sweep_job(plan, result, timestamp)
