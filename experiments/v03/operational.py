"""Experiment I: do earlier warnings reduce failed jobs or calibration overhead?

A closed-loop simulation. Two qubits run one job slot per 10-minute batch;
every batch also carries readout probes (prepare |0> / |1>, 2000 shots each)
that the monitoring policies see. Each qubit's readout error starts at a
fresh base value after every calibration and then degrades through random
events until the next calibration of that qubit:

* gradual degradation: from its onset the error grows linearly (absolute
  slope per hour);
* abrupt degradation: the error is multiplied by a factor (TLS-like jump);
* a stationary log-Ornstein-Uhlenbeck fluctuation always multiplies it.

A calibration costs one batch of downtime for that qubit, then resets the
error to the next base value and clears every event that started before it.
A job "fails" when it runs on a qubit whose true error is above the 5%
recalibration threshold.

Common random numbers: event times and sizes, base values and fluctuation
paths are drawn once per run, in absolute time, and shared by every policy;
the probe counts of batch i on qubit q use a generator seeded by (run seed,
q, i), so two policies that are in the same state draw the same counts.

The parameters of the degradation process are illustrative, not fitted to
any device: the answer to the operational question depends on them, which
is why several scenarios are run (V03_PREREGISTRATION.md, Experiment I).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
BATCH_MIN = 10.0
THRESHOLD = 0.05
SHOTS = 2000  # per probe circuit and qubit
SPB = 2 * SHOTS  # probe shots per qubit per batch (both preparations)
N_QUBITS = 2
REF = 10  # reference window of the control charts after each calibration


@dataclass(frozen=True)
class OpsScenario:
    name: str
    drift_per_day: float  # gradual-degradation onsets per qubit per day
    jump_per_day: float  # abrupt degradations per qubit per day
    slope_per_hour: tuple[float, float] = (0.002, 0.008)  # uniform: absolute increase of the error per hour
    jump_factor: tuple[float, float] = (1.3, 3.0)  # log-uniform multiplicative jump
    base: tuple[float, float] = (0.015, 0.025)  # uniform: error right after a calibration
    fluct_sigma: float = 0.05  # stationary log-OU fluctuation (sd of the log)
    fluct_tau_batches: float = 5.0


@dataclass
class World:
    """Random streams of one run, shared by every policy."""

    n_batches: int
    seed: int
    events: list[list[tuple[int, str, float]]]  # per qubit: (start batch, "drift"|"jump", slope or factor)
    bases: list[np.ndarray]  # per qubit: base error after the k-th calibration (k = 0: start of the run)
    fluct: np.ndarray  # (qubits, batches) multiplicative fluctuation


def make_world(sc: OpsScenario, n_batches: int, seed: int) -> World:
    rng = np.random.default_rng([seed, 7])
    per_batch = BATCH_MIN / (24 * 60)
    events: list[list[tuple[int, str, float]]] = []
    for _q in range(N_QUBITS):
        ev: list[tuple[int, str, float]] = []
        for kind, rate in (("drift", sc.drift_per_day), ("jump", sc.jump_per_day)):
            if rate <= 0:
                continue
            n = rng.poisson(rate * n_batches * per_batch)
            starts = np.sort(rng.integers(1, n_batches, n))
            for s in starts:
                if kind == "drift":
                    prm = float(rng.uniform(*sc.slope_per_hour))
                else:
                    lo, hi = np.log(sc.jump_factor[0]), np.log(sc.jump_factor[1])
                    prm = float(np.exp(rng.uniform(lo, hi)))
                ev.append((int(s), kind, prm))
        events.append(sorted(ev))
    bases = [rng.uniform(*sc.base, size=n_batches + 2) for _ in range(N_QUBITS)]
    a = math.exp(-1 / sc.fluct_tau_batches)
    x = np.empty((N_QUBITS, n_batches))
    x[:, 0] = rng.normal(size=N_QUBITS)
    for i in range(1, n_batches):
        x[:, i] = a * x[:, i - 1] + math.sqrt(1 - a * a) * rng.normal(size=N_QUBITS)
    return World(n_batches, seed, events, bases, np.exp(sc.fluct_sigma * x))


def true_error(w: World, q: int, i: int, cleared_until: int, n_cal: int) -> float:
    """Error of qubit q at batch i, given that its last calibration cleared
    every event that started at or before batch ``cleared_until``."""
    add, mult = 0.0, 1.0
    for start, kind, prm in w.events[q]:
        if start <= cleared_until or start > i:
            continue
        if kind == "drift":
            add += prm * (i - start) * BATCH_MIN / 60
        else:
            mult *= prm
    return float(min(0.5, (w.bases[q][n_cal] + add) * mult * w.fluct[q, i]))


def probe_counts(w: World, q: int, i: int, p: float) -> tuple[int, int]:
    rng = np.random.default_rng([w.seed, 11, q, i])
    return int(rng.binomial(SHOTS, p)), int(rng.binomial(SHOTS, p))


# --------------------------------------------------------------------------- policies


class Monitor:
    """Decides, from one qubit's probe data since its last calibration,
    whether to request a recalibration. ``reset`` starts a fresh session."""

    name = "none"

    def reset(self, q: int, i: int) -> None:  # pragma: no cover - interface
        pass

    def observe(self, q: int, i: int, k0: int, k1: int, p_true: float) -> tuple[bool, dict]:
        return False, {}


class NoMonitor(Monitor):
    name = "none"


class OracleMonitor(Monitor):
    """Knows the true error: triggers as soon as it is above the threshold."""

    name = "oracle"

    def observe(self, q, i, k0, k1, p_true):
        return p_true > THRESHOLD, {}


class NaiveMonitor(Monitor):
    """Per-batch point estimate above the threshold."""

    name = "naive"

    def observe(self, q, i, k0, k1, p_true):
        return (k0 + k1) / SPB > THRESHOLD, {}


class ChartMonitor(Monitor):
    """Shewhart (k sigma) or one-sided tabular CUSUM (allowance 0.5 sigma,
    alarm above h sigma) on the per-batch pooled probe error rate, with the
    reference mean and binomial sigma estimated from the first ``REF``
    batches after each calibration (as in the v0.2 comparators)."""

    def __init__(self, kind: str, level: float):
        self.kind, self.level = kind, level
        self.name = f"{kind}({level:g})"
        self.state: dict[int, dict[str, Any]] = {}

    def reset(self, q, i):
        self.state[q] = {"rates": [], "s": 0.0}

    def observe(self, q, i, k0, k1, p_true):
        st = self.state[q]
        r = (k0 + k1) / SPB
        if len(st["rates"]) < REF:
            st["rates"].append(r)
            return False, {}
        base = float(np.mean(st["rates"]))
        sigma = math.sqrt(max(base * (1 - base), 1e-12) / SPB)
        if self.kind == "shewhart":
            return r > base + self.level * sigma, {}
        st["s"] = max(0.0, st["s"] + (r - base) / sigma - 0.5)
        return st["s"] > self.level, {}


class _MemoryStore:
    """In-memory stand-in for ``EstimateStore`` (same interface, no SQLite),
    so a long closed-loop run does not re-parse its history every batch."""

    def __init__(self) -> None:
        self.es: list = []

    def add(self, es) -> int:
        es = list(es)
        self.es += es
        return len(es)

    def all(self):
        return sorted(self.es, key=lambda e: e.timestamp)

    def series(self):
        out: dict = {}
        for e in self.all():
            out.setdefault(e.series_key, []).append(e)
        return out

    def mark_recalibrated(self, ts, qubits=None, note="") -> None:  # pragma: no cover - not used
        raise NotImplementedError

    def last_recalibration(self, qubits):
        return None


class EngineMonitor(Monitor):
    """The v0.3 engine on the qubit's MEASURED readout probes. A fresh
    profiler per qubit and calibration (baselines restart); the family is
    declared as 2 qubits x 1 metric x 1 provenance, so every group gets the
    same per-series alpha as in a joint profiler.

    ``triggers``: ``"crossing"`` -- CRITICAL threshold or WARNING forecast
    alerts (the qubit is, or is projected to be, beyond the threshold);
    ``"any"`` -- also WARNING drift alerts (a meaningful relative increase)."""

    def __init__(self, log_e_offset: float, triggers: str = "crossing"):
        if triggers not in ("crossing", "any"):
            raise ValueError(triggers)
        self.c, self.triggers = log_e_offset, triggers
        self.name = f"engine(c={log_e_offset:g},{triggers})"
        self.prof: dict[int, Any] = {}

    def reset(self, q, i):
        from qnp import DriftConfig, ErrorBudget, Profiler

        cfg = DriftConfig(
            budget=ErrorBudget(alpha_session=0.10, n_qubits=N_QUBITS, n_metrics=1, n_provenances=1),
            log_e_offset=self.c,
        )
        self.prof[q] = Profiler(store=_MemoryStore(), config=cfg)  # type: ignore[arg-type]

    def observe(self, q, i, k0, k1, p_true):
        from qnp.measured import estimate_readout

        ts = T0 + timedelta(minutes=BATCH_MIN * i)
        prof = self.prof[q]
        prof.add([estimate_readout(q, 0, k0, SHOTS, ts), estimate_readout(q, 1, k1, SHOTS, ts)])
        alerts = prof.check(now=ts)
        hit = []
        for a in alerts:
            crossing = (a.kind == "threshold") or (a.kind == "forecast" and a.level.value == "WARNING")
            if crossing or (self.triggers == "any" and a.kind == "drift"):
                hit.append(a.kind)
        return bool(hit), {"kinds": sorted(set(hit))}


@dataclass
class Policy:
    name: str
    monitor_factory: Callable[[], Monitor] = NoMonitor
    schedule_hours: float | None = 24.0  # fixed calibration of every qubit, None: none


@dataclass
class Outcome:
    jobs: int = 0
    failed: int = 0
    downtime: int = 0
    calibrations: int = 0
    scheduled: int = 0
    triggered: int = 0
    triggered_above: int = 0  # true error above the threshold when triggered
    triggered_degraded: int = 0  # below threshold, but >= 10% above its post-calibration base
    triggered_false: int = 0  # neither
    excess: float = 0.0  # sum over executed jobs of max(0, error - threshold)
    trigger_kinds: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


def simulate(policy: Policy, w: World) -> Outcome:
    """Run one policy on one world."""
    mon = policy.monitor_factory()
    out = Outcome()
    period = None if policy.schedule_hours is None else round(policy.schedule_hours * 60 / BATCH_MIN)
    n_cal = [0] * N_QUBITS
    cleared = [0] * N_QUBITS  # events starting at or before this batch were cleared by a calibration
    down = [-1] * N_QUBITS  # batch index of a pending/ongoing calibration downtime
    base_now = [float(w.bases[q][0]) for q in range(N_QUBITS)]
    for q in range(N_QUBITS):
        mon.reset(q, 0)

    def calibrate(q: int, at: int) -> None:
        down[q] = at
        n_cal[q] += 1
        cleared[q] = at
        base_now[q] = float(w.bases[q][n_cal[q]])
        out.calibrations += 1

    for i in range(w.n_batches):
        for q in range(N_QUBITS):
            if down[q] == i:  # this batch is the calibration itself
                out.downtime += 1
                continue
            if down[q] == i - 1 and i > 0:
                mon.reset(q, i)  # first batch after a calibration: fresh monitoring session
            p = true_error(w, q, i, cleared[q], n_cal[q])
            out.jobs += 1
            if p > THRESHOLD:
                out.failed += 1
                out.excess += p - THRESHOLD
            k0, k1 = probe_counts(w, q, i, p)
            trig, info = mon.observe(q, i, k0, k1, p)
            if trig and i + 1 < w.n_batches:
                out.triggered += 1
                if p > THRESHOLD:
                    out.triggered_above += 1
                elif p >= 1.1 * base_now[q] * w.fluct[q, i]:
                    out.triggered_degraded += 1
                else:
                    out.triggered_false += 1
                for k in info.get("kinds", []):
                    out.trigger_kinds[k] = out.trigger_kinds.get(k, 0) + 1
                calibrate(q, i + 1)
        if period and (i + 1) % period == 0 and i + 1 < w.n_batches:
            for q in range(N_QUBITS):
                if down[q] != i + 1:
                    calibrate(q, i + 1)
                    out.scheduled += 1
    return out


# --------------------------------------------------------------------------- analysis helpers


def frontier_at(points: list[tuple[float, float]], x: float) -> float | None:
    """Piecewise-linear interpolation of failed fraction (y) at calibration
    rate ``x`` along the fixed-schedule frontier ``points`` = [(rate, failed)].
    None outside the range spanned by the schedules (no extrapolation)."""
    pts = sorted(points)
    xs = [p[0] for p in pts]
    if not pts or x < xs[0] or x > xs[-1]:
        return None
    return float(np.interp(x, xs, [p[1] for p in pts]))


def inverse_frontier_at(points: list[tuple[float, float]], y: float) -> float | None:
    """Calibration rate a fixed schedule needs to reach failed fraction ``y``
    (the frontier is decreasing in the calibration rate). None outside range."""
    pts = sorted(points, key=lambda p: p[1])
    ys = [p[1] for p in pts]
    if not pts or y < ys[0] or y > ys[-1]:
        return None
    return float(np.interp(y, ys, [p[0] for p in pts]))
