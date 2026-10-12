"""Shared harness: simulated workloads, streaming profiler runs, and an
append-only result log. Every run is recorded -- passing or failing."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from importlib import metadata
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
# Override only for smoke tests; real runs always go to <repo>/results.
RESULTS = Path(os.environ.get("QNP_RESULTS_DIR", ROOT / "results"))
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
BATCH_INTERVAL = timedelta(minutes=10)


# --------------------------------------------------------------------------- provenance of runs


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def source_tree_hash() -> str:
    """SHA-256 over the contents of src/ and experiments/ (sorted paths), so a
    run can prove which code it executed independently of git state."""
    import hashlib

    h = hashlib.sha256()
    for sub in ("src", "experiments"):
        for path in sorted((ROOT / sub).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            h.update(str(path.relative_to(ROOT)).encode())
            h.update(path.read_bytes())
    return h.hexdigest()


def environment() -> dict:
    pkgs = {}
    for name in ("numpy", "scipy", "qiskit", "qiskit-aer", "cirq-core", "qiskit-experiments", "quantum-noise-profiler"):
        try:
            pkgs[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            pkgs[name] = None
    return {
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain", "--", "src", "experiments")),
        "source_tree_sha256": source_tree_hash(),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": pkgs,
    }


@dataclass
class Criterion:
    name: str
    description: str
    threshold: float
    observed: float
    comparison: str  # ">=" or "<="

    @property
    def passed(self) -> bool:
        return self.observed >= self.threshold if self.comparison == ">=" else self.observed <= self.threshold

    def to_dict(self) -> dict:
        return {**self.__dict__, "passed": self.passed}


def record(
    experiment: str,
    config: dict,
    summary: dict,
    criteria: list[Criterion],
    trials: list[dict],
    started: datetime,
    notes: str = "",
    env_at_start: dict | None = None,
    protocol: str = "",
) -> dict:
    """Append one run to results/runs.jsonl and its raw trials to results/raw/.
    Never overwrites; failures are recorded exactly like successes.

    ``env_at_start`` should be ``environment()`` captured before the first
    trial (v0.1 recorded the environment at completion only; see
    docs/V01_AUDIT.md D4). ``protocol`` names the preregistration file and
    section that fixed the criteria."""
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "raw").mkdir(exist_ok=True)
    run_id = f"{experiment}-{started.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
    raw_path = RESULTS / "raw" / f"{run_id}.jsonl"
    with raw_path.open("x") as f:
        for t in trials:
            f.write(json.dumps(t, default=_jsonable) + "\n")
    entry = {
        "run_id": run_id,
        "experiment": experiment,
        "started": started.isoformat(),
        "finished": datetime.now(timezone.utc).isoformat(),
        "environment": environment(),
        "environment_at_start": env_at_start,
        "protocol": protocol,
        "config": config,
        "summary": summary,
        "criteria": [c.to_dict() for c in criteria],
        "passed_all": all(c.passed for c in criteria),
        "raw": os.path.relpath(raw_path, ROOT).replace("\\", "/"),
        "notes": notes,
    }
    with (RESULTS / "runs.jsonl").open("a") as f:
        f.write(json.dumps(entry, default=_jsonable) + "\n")
    return entry


def _jsonable(x):
    if isinstance(x, (np.floating, np.integer)):
        return x.item()
    if isinstance(x, np.ndarray):
        return x.tolist()
    if isinstance(x, datetime):
        return x.isoformat()
    return str(x)


def print_entry(entry: dict) -> None:
    print(f"\n== {entry['run_id']}  passed_all={entry['passed_all']}")
    for k, v in entry["summary"].items():
        print(f"   {k}: {v}")
    for c in entry["criteria"]:
        mark = "PASS" if c["passed"] else "FAIL"
        print(f"   [{mark}] {c['name']}: observed {c['observed']:.4g} {c['comparison']} {c['threshold']:g}")


# --------------------------------------------------------------------------- simulated workload


def workload(n_det_pairs: int = 1, n_random: int = 2, seed: int = 1234):
    """A two-qubit job: deterministic 'mirror' circuits (random layer, then its
    inverse; optionally X on both) plus circuits with non-deterministic output.
    Circuit structure is fixed across batches so contexts are stable."""
    from qiskit import QuantumCircuit

    rng = np.random.default_rng(seed)
    circuits = []
    for _ in range(n_det_pairs):
        for flip in (False, True):
            qc = QuantumCircuit(2)
            layer = QuantumCircuit(2)
            for q in range(2):
                layer.rz(rng.uniform(0, 2 * np.pi), q)
                layer.sx(q)
                layer.rz(rng.uniform(0, 2 * np.pi), q)
            layer.cx(0, 1)
            qc.compose(layer, inplace=True)
            qc.compose(layer.inverse(), inplace=True)
            if flip:
                qc.x([0, 1])
            qc.measure_all()
            circuits.append(qc)
    for _ in range(n_random):
        qc = QuantumCircuit(2)
        qc.h(0)
        qc.ry(rng.uniform(0.3, 2.8), 1)
        qc.cx(0, 1)
        qc.measure_all()
        circuits.append(qc)
    return circuits


def readout_simulator(p0: float, p1: float):
    """Aer simulator whose only noise is symmetric readout error per qubit, so
    the ground-truth effective flip rate equals the injected readout error."""
    from qiskit_aer import AerSimulator
    from qiskit_aer.noise import NoiseModel, ReadoutError

    nm = NoiseModel()
    for q, p in ((0, p0), (1, p1)):
        nm.add_readout_error(ReadoutError([[1 - p, p], [p, 1 - p]]), [q])
    return AerSimulator(noise_model=nm)


def run_batch(circuits, p0: float, p1: float, shots: int, seed: int):
    sim = readout_simulator(p0, p1)
    res = sim.run(circuits, shots=shots, seed_simulator=seed).result()
    return [res.get_counts(i) for i in range(len(circuits))]


def naive_rate(counts_list, circuits, qubit: int) -> float:
    """Conventional per-batch point estimate: pooled flip fraction on
    deterministic circuits, no uncertainty, no history."""
    from qnp.adapters.qiskit_adapter import analyze_circuit

    flips = shots = 0
    for qc, counts in zip(circuits, counts_list):
        ideal = analyze_circuit(qc).ideal[qubit].bit
        if ideal is None:
            continue
        for key, c in counts.items():
            bit = int(key.replace(" ", "")[::-1][qubit])
            flips += c * (bit != ideal)
            shots += c
    return flips / shots


def stream(p0_schedule, p1_schedule, seed: int, shots: int, config=None) -> list[dict]:
    """Feed one batch per schedule step through a fresh Profiler, checking
    after every batch exactly as a live deployment would."""
    from qnp import Profiler

    prof = Profiler(config=config)
    circuits = workload()
    log = []
    for i, (p0, p1) in enumerate(zip(p0_schedule, p1_schedule)):
        ts = T0 + i * BATCH_INTERVAL
        counts = run_batch(circuits, p0, p1, shots, seed * 10_000 + i)
        prof.ingest_qiskit(circuits, counts, ts)
        alerts = prof.check(now=ts)
        log.append(
            {
                "i": i,
                "p_true": [p0, p1],
                "naive": [naive_rate(counts, circuits, 0), naive_rate(counts, circuits, 1)],
                "alerts": [
                    {
                        "kind": a.kind,
                        "level": a.level.value,
                        "qubit": a.qubits[0],
                        "context": a.context,
                        **{
                            k: a.details.get(k)
                            for k in ("hours_to_threshold_median", "probability", "predictive_tail_probability")
                            if a.details.get(k) is not None
                        },
                    }
                    for a in alerts
                ],
            }
        )
    return log


def first_index(log, pred) -> int | None:
    for b in log:
        if any(pred(a) for a in b["alerts"]):
            return b["i"]
    return None
