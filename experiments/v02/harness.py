"""v0.2 experiment harness: data generators, engines, comparators and the
per-batch log format shared by Experiments A-C and E-F.

Two data paths produce identical ``Estimate`` streams:

* ``aer_batches`` -- the real pipeline: Qiskit Aer with the configured noise
  model, the ``qnp`` Qiskit adapter, physical-qubit bookkeeping. Used for
  the confirmatory runs.
* ``surrogate_batches`` -- exact numpy emulation of the readout-only
  pipeline: for a deterministic circuit every shot flips independently with
  the injected readout error, so per-(qubit, context) counts are
  Binomial(shots, p). Used for calibration sweeps, where thousands of runs
  are needed; its equivalence to the Aer path is tested in
  tests/test_v02_harness.py.

Every engine is driven batch by batch exactly as in deployment. The log
records, per batch, the alerts *and* the channel e-values and gate states,
so that re-thresholded variants (the "calibrated" configuration) can be
evaluated from the same run without re-simulation.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "experiments") not in sys.path:
    sys.path.insert(0, str(ROOT / "experiments"))

from qnp import DriftConfig, ErrorBudget, Estimate, LegacyDriftConfig, Profiler, Status

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
BATCH_INTERVAL = timedelta(minutes=10)
CTX0 = "ideal=0|1q<=16|2q<=2"  # contexts produced by common.workload() mirror circuits
CTX1 = "ideal=1|1q<=16|2q<=2"
CONTEXTS = (CTX0, CTX1)

# Seed blocks fixed by experiments/V02_PREREGISTRATION.md. Development used
# ad-hoc seeds below 20_000; calibration and confirmatory blocks are disjoint.
SEED_DEV_MAX = 19_999
SEED_CALIBRATION = 20_000
SEED_CONFIRMATORY = 30_000


def seed_for(block: int, experiment: int, condition: int, run: int) -> int:
    """Deterministic, collision-free seed: block + experiment*1000 + condition*200 + run (run < 200)."""
    if not 0 <= run < 200 or not 0 <= condition < 5 or not 0 <= experiment < 10:
        raise ValueError("seed layout supports experiment < 10, condition < 5, run < 200")
    return block + experiment * 1000 + condition * 200 + run


# --------------------------------------------------------------------------- data generation


@dataclass
class Batch:
    i: int
    timestamp: datetime
    p_true: list[float]
    counts: dict[int, dict[str, tuple[int, int]]]  # qubit -> context -> (flips, shots)

    def naive(self, qubit: int) -> float:
        k = sum(c[0] for c in self.counts[qubit].values())
        n = sum(c[1] for c in self.counts[qubit].values())
        return k / n


def surrogate_batches(
    p_schedules: list[np.ndarray],
    shots: int,
    seed: int,
    timestamps: list[datetime] | None = None,
    drop: np.ndarray | None = None,
) -> list[Batch]:
    """Exact emulation of the readout-only Aer pipeline for the standard
    workload (two deterministic mirror circuits per batch, one per ideal bit).
    ``drop[i]`` True removes batch i (missing observation)."""
    rng = np.random.default_rng(seed)
    n_batches = len(p_schedules[0])
    out = []
    for i in range(n_batches):
        counts = {}
        for q, sched in enumerate(p_schedules):
            counts[q] = {ctx: (int(rng.binomial(shots, sched[i])), shots) for ctx in CONTEXTS}
        if drop is not None and drop[i]:
            continue
        ts = timestamps[i] if timestamps is not None else T0 + i * BATCH_INTERVAL
        out.append(Batch(i, ts, [float(s[i]) for s in p_schedules], counts))
    return out


def aer_batches(
    p_schedules: list[np.ndarray],
    shots: int,
    seed: int,
    noise_factory: Callable | None = None,
    timestamps: list[datetime] | None = None,
    drop: np.ndarray | None = None,
) -> list[Batch]:
    """The real pipeline: Aer + qnp Qiskit adapter. ``noise_factory(p0, p1)``
    returns an AerSimulator (default: symmetric readout error only)."""
    from common import readout_simulator, workload

    from qnp.adapters.qiskit_adapter import infer_from_results

    circuits = workload()
    factory = noise_factory or readout_simulator
    out = []
    for i in range(len(p_schedules[0])):
        if drop is not None and drop[i]:
            continue
        p0, p1 = float(p_schedules[0][i]), float(p_schedules[1][i])
        sim = factory(p0, p1)
        res = sim.run(circuits, shots=shots, seed_simulator=seed * 10_000 + i).result()
        counts_list = [res.get_counts(j) for j in range(len(circuits))]
        ts = timestamps[i] if timestamps is not None else T0 + i * BATCH_INTERVAL
        es = infer_from_results(circuits, counts_list, ts)
        counts: dict[int, dict[str, tuple[int, int]]] = {}
        for e in es:
            if e.status is Status.OK:
                counts.setdefault(e.qubits[0], {})[e.context] = (e.successes, e.trials)
        out.append(Batch(i, ts, [p0, p1], counts))
    return out


def batch_estimates(b: Batch) -> list[Estimate]:
    from qnp.inferred import FlipTally, flip_estimates

    tallies = {(q, ctx): FlipTally(k, n) for q, cs in b.counts.items() for ctx, (k, n) in cs.items()}
    return flip_estimates(tallies, {}, b.timestamp, "harness")


# --------------------------------------------------------------------------- engines


@dataclass
class EngineSpec:
    name: str
    kind: str  # "v02" | "v01"
    alpha_session: float = 0.10
    n_qubits: int = 2
    n_metrics: int = 1
    change_probability: float = 0.95  # v01 only
    trend_probability: float = 0.9  # v01 only
    threshold_probability: float = 0.95  # v01 only
    extra: dict[str, Any] = field(default_factory=dict)

    def make(self) -> Profiler:
        if self.kind == "v01":
            cfg = LegacyDriftConfig(
                change_probability=self.change_probability,
                trend_probability=self.trend_probability,
                threshold_probability=self.threshold_probability,
            )
            return Profiler(config=cfg)
        cfg = DriftConfig(
            budget=ErrorBudget(alpha_session=self.alpha_session, n_qubits=self.n_qubits, n_metrics=self.n_metrics),
            **self.extra,
        )
        return Profiler(config=cfg)


V02_DEFAULT = EngineSpec("v02", "v02")
V01_DEFAULT = EngineSpec("v01", "v01")


def run_engine(batches: list[Batch], spec: EngineSpec) -> list[dict]:
    """Feed batches one by one; after each, record alerts and (v0.2) channel evidence."""
    prof = spec.make()
    log = []
    for b in batches:
        prof.add(batch_estimates(b))
        entry: dict[str, Any] = {"i": b.i, "p_true": b.p_true, "naive": [b.naive(q) for q in sorted(b.counts)]}
        if spec.kind == "v01":
            alerts = prof.check(now=b.timestamp)
            entry["evidence"] = None
        else:
            reports = prof.reports(now=b.timestamp)
            alerts = [a for r in reports for a in r.alerts]
            ev = {}
            fprob = prof.config.forecast.forecast_probability
            for r in reports:
                q = r.qubits[0]
                fcs = []
                for ctx, v in r.forecast["per_context"].items():
                    d = v["diagnostics"]
                    pw = d.get("ungated_p_within_horizon")
                    item = {
                        "ctx": ctx,
                        "log_e": v["log_e"],
                        "alertable": bool(d.get("ungated_alertable") and pw is not None and pw >= fprob),
                    }
                    if item["alertable"]:
                        item["crossing"] = d.get("ungated_crossing")
                    fcs.append(item)
                ev[q] = {
                    "drift_log_e": r.drift["log_e"],
                    "drift_bar": r.drift["log_e_threshold_nominal"],
                    "drift_gates_ok": bool(r.drift["gates"]["effect"] and r.drift["gates"]["persistence"]),
                    "thr_log_e": r.threshold.get("log_e"),
                    "thr_bar": r.threshold.get("log_e_threshold_nominal"),
                    "fc": fcs,
                    "fc_bar": r.forecast["log_e_threshold_nominal"],
                }
            entry["evidence"] = ev
        entry["alerts"] = [
            {
                "kind": a.kind,
                "level": a.level.value,
                "qubit": a.qubits[0],
                "context": a.context,
                **{
                    k: a.details.get(k)
                    for k in (
                        "hours_to_threshold_median",
                        "hours_to_threshold_p10",
                        "hours_to_threshold_p90",
                        "probability_within_horizon",
                        "probability",
                        "e_value",
                        "e_threshold",
                    )
                    if a.details.get(k) is not None
                },
            }
            for a in alerts
        ]
        log.append(entry)
    return log


# --------------------------------------------------------------------------- post-hoc decision rules


def first_alarm(
    log: list[dict],
    qubit: int,
    start: int = 0,
    kinds=("drift", "threshold", "forecast"),
    levels=("INFO", "WARNING", "CRITICAL"),
) -> int | None:
    for b in log:
        if b["i"] < start:
            continue
        if any(a["qubit"] == qubit and a["kind"] in kinds and a["level"] in levels for a in b["alerts"]):
            return b["i"]
    return None


def first_alarm_rescaled(
    log: list[dict], qubit: int, log_scale: float, start: int = 0, channels=("drift", "threshold", "forecast")
) -> int | None:
    """First alarm of the v0.2 engine with every e-value threshold divided by
    exp(log_scale) (the empirically calibrated configuration). Exact: the
    gates that do not depend on the threshold (effect, persistence, forecast
    model checks) are recorded per batch. ``log_scale = 0`` reproduces the
    engine's own alarms (tested in tests/test_v02_harness.py)."""
    for b in log:
        if b["i"] < start or not b.get("evidence"):
            continue
        ev = b["evidence"].get(qubit, b["evidence"].get(str(qubit)))
        if ev is None:
            continue
        if "drift" in channels and ev["drift_gates_ok"] and ev["drift_log_e"] >= ev["drift_bar"] - log_scale:
            return b["i"]
        if "threshold" in channels and ev["thr_log_e"] is not None and ev["thr_log_e"] >= ev["thr_bar"] - log_scale:
            return b["i"]
        if "forecast" in channels and any(f["alertable"] and f["log_e"] >= ev["fc_bar"] - log_scale for f in ev["fc"]):
            return b["i"]
    return None


def shewhart_first(
    naive: list[float], qubit: int, k: float, ref: int, shots_per_batch: int, start: int = 0
) -> int | None:
    rates = [row[qubit] for row in naive]
    base = float(np.mean(rates[:ref]))
    sigma = float(np.sqrt(base * (1 - base) / shots_per_batch))
    limit = base + k * sigma
    return next((i for i in range(max(start, ref), len(rates)) if rates[i] > limit), None)


def cusum_first(
    naive: list[float], qubit: int, h: float, ref: int, shots_per_batch: int, kappa: float = 0.5, start: int = 0
) -> int | None:
    """One-sided tabular CUSUM on standardized per-batch rates (reference
    mean and binomial sigma from the first ``ref`` batches); allowance
    ``kappa`` sigma, alarm when the statistic exceeds ``h`` sigma."""
    rates = [row[qubit] for row in naive]
    base = float(np.mean(rates[:ref]))
    sigma = float(np.sqrt(base * (1 - base) / shots_per_batch))
    s = 0.0
    for i in range(ref, len(rates)):
        z = (rates[i] - base) / sigma
        s = max(0.0, s + z - kappa)
        if i >= start and s > h:
            return i
    return None


# --------------------------------------------------------------------------- parallel driver


def _run_one(args):
    kind, spec, gen_args = args
    if kind == "surrogate":
        batches = surrogate_batches(**gen_args)
    else:
        batches = aer_batches(**gen_args)
    return run_engine(batches, spec), [b.naive(q) for b in batches for q in [0]]


def run_many(jobs: list[tuple[str, EngineSpec, dict]], workers: int | None = None) -> list[list[dict]]:
    """Run (data kind, engine, generator kwargs) jobs in parallel, preserving order."""
    workers = workers or max(1, min(os.cpu_count() or 1, 4))
    if workers == 1 or len(jobs) == 1:
        return [_run_one(j)[0] for j in jobs]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        return [log for log, _ in ex.map(_run_one, jobs, chunksize=1)]


__all__ = [
    "BATCH_INTERVAL",
    "CONTEXTS",
    "SEED_CALIBRATION",
    "SEED_CONFIRMATORY",
    "T0",
    "V01_DEFAULT",
    "V02_DEFAULT",
    "Batch",
    "EngineSpec",
    "aer_batches",
    "batch_estimates",
    "cusum_first",
    "first_alarm",
    "first_alarm_rescaled",
    "run_engine",
    "run_many",
    "seed_for",
    "shewhart_first",
    "surrogate_batches",
]
