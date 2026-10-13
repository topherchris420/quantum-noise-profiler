"""v0.3 harness: drive the engine batch by batch on estimate streams with
several metrics per qubit, and record per (qubit, metric) group the channel
evidence needed to apply the calibrated thresholds post hoc (as in v0.2:
every e-value threshold divided by exp(c); the effect, persistence and
forecast-model gates do not depend on the threshold, so the rescaling is
exact; tests/test_v03_harness.py checks it against a direct run).
"""

from __future__ import annotations

import math
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from qnp import V02_THRESHOLDS, DriftConfig, ErrorBudget, Estimate, Profiler

R = 6
SEED_CONFIRMATORY_V03 = 60_000  # Experiments G and I (V03_PREREGISTRATION.md section 0)
SEED_H = 70_000  # Experiment H


@dataclass
class EngineSpec3:
    """``arch="v03"``: v0.3 defaults (threshold on readout_error only);
    ``arch="v02"``: v0.2 thresholds (absolute threshold on effective flip
    rates too). The family is declared up front."""

    name: str
    arch: str
    n_qubits: int = 2
    n_metrics: int = 1
    log_e_offset: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    def make(self) -> Profiler:
        if self.arch not in ("v02", "v03"):
            raise ValueError(self.arch)
        kw: dict[str, Any] = {} if self.arch == "v03" else {"thresholds": dict(V02_THRESHOLDS)}
        kw.update(self.extra)
        cfg = DriftConfig(
            budget=ErrorBudget(alpha_session=0.10, n_qubits=self.n_qubits, n_metrics=self.n_metrics, n_provenances=1),
            log_e_offset=self.log_e_offset,
            **kw,
        )
        return Profiler(config=cfg)


def _r(x):
    if x is None:
        return None
    x = float(x)
    return round(x, R) if math.isfinite(x) else None


def run_engine3(batches: Sequence[tuple[int, Any, list[Estimate]]], spec: EngineSpec3) -> dict:
    """Feed (batch index, timestamp, estimates) one batch at a time; after each
    batch record, per group ``"<qubit>:<metric>"``, the drift log e-value
    ``d``, the threshold-independent drift gates ``g``, the threshold-channel
    log e-value ``t`` (None without a threshold), the largest log e-value of a
    forecast that is alertable apart from its evidence gate ``f``, and the
    forecast threshold ``fb``; ``bars`` holds the nominal drift and threshold
    log thresholds. Also returns the alerts of the configured engine."""
    prof = spec.make()
    out: dict[str, Any] = {"i": [], "bars": None, "g": {}, "alerts": []}
    fprob = prof.config.forecast.forecast_probability  # type: ignore[union-attr]
    for i, ts, es in batches:
        prof.add(es)
        reports = prof.reports(now=ts)
        out["i"].append(i)
        seen = set()
        for r in reports:
            key = f"{r.qubits[0]}:{r.metric.value}"
            seen.add(key)
            bars = {"d": _r(r.drift["log_e_threshold_nominal"]), "t": _r(r.threshold.get("log_e_threshold_nominal"))}
            if r.threshold.get("threshold") is not None and bars["t"] is not None:
                out["bars"] = out["bars"] or {}
                if out["bars"].get("t") not in (None, bars["t"]):
                    raise ValueError("threshold bars differ between groups")
                out["bars"]["t"] = bars["t"]
            out["bars"] = out["bars"] or {}
            if out["bars"].get("d") not in (None, bars["d"]):
                raise ValueError("drift bars differ between groups")
            out["bars"]["d"] = bars["d"]
            fl = []
            for v in r.forecast["per_context"].values():
                d = v["diagnostics"]
                pw = d.get("ungated_p_within_horizon")
                if d.get("ungated_alertable") and pw is not None and pw >= fprob:
                    fl.append(v["log_e"])
            rec = out["g"].setdefault(key, {"d": [], "g": [], "t": [], "f": [], "fb": [], "first": len(out["i"]) - 1})
            rec["d"].append(_r(r.drift["log_e"]))
            rec["g"].append(int(bool(r.drift["gates"]["effect"] and r.drift["gates"]["persistence"])))
            rec["t"].append(_r(r.threshold.get("log_e")))
            rec["f"].append(_r(max(fl)) if fl else None)
            rec["fb"].append(_r(r.forecast["log_e_threshold_nominal"]))
            for a in r.alerts:
                out["alerts"].append([i, key, a.kind, a.level.value])
        for key, rec in out["g"].items():
            if key not in seen:  # group without data yet in this batch (cannot happen once it exists)
                for k in ("d", "g", "t", "f", "fb"):
                    rec[k].append(None if k != "g" else 0)
    return out


def group_alarms(rec: dict, key: str, c: float) -> list[bool]:
    """Per-batch alarm of one group with every threshold lowered by ``c`` nats;
    aligned with ``rec["i"]`` (False before the group's first batch)."""
    g = rec["g"].get(key)
    n = len(rec["i"])
    if g is None:
        return [False] * n
    bars = rec["bars"]
    flags = [False] * g["first"]
    for d, ok, t, f, fb in zip(g["d"], g["g"], g["t"], g["f"], g["fb"]):
        hit = (
            (ok and d is not None and d >= bars["d"] - c)
            or (t is not None and bars.get("t") is not None and t >= bars["t"] - c)
            or (f is not None and fb is not None and f >= fb - c)
        )
        flags.append(bool(hit))
    return flags[:n] + [False] * (n - len(flags))


def group_channel_alarms(rec: dict, key: str, c: float, channel: str) -> list[bool]:
    """As ``group_alarms`` for one channel (``drift``, ``threshold``, ``forecast``)."""
    g = rec["g"].get(key)
    n = len(rec["i"])
    if g is None:
        return [False] * n
    bars = rec["bars"]
    flags = [False] * g["first"]
    for d, ok, t, f, fb in zip(g["d"], g["g"], g["t"], g["f"], g["fb"]):
        if channel == "drift":
            hit = ok and d is not None and d >= bars["d"] - c
        elif channel == "threshold":
            hit = t is not None and bars.get("t") is not None and t >= bars["t"] - c
        else:
            hit = f is not None and fb is not None and f >= fb - c
        flags.append(bool(hit))
    return flags[:n] + [False] * (n - len(flags))


def qubit_alarms(rec: dict, q: int, c: float, metrics: Sequence[str] | None = None) -> list[bool]:
    """Any group of qubit ``q`` (optionally only the given metrics) alarms."""
    keys = [k for k in rec["g"] if k.split(":")[0] == str(q) and (metrics is None or k.split(":")[1] in metrics)]
    n = len(rec["i"])
    out = [False] * n
    for k in keys:
        out = [a or b for a, b in zip(out, group_alarms(rec, k, c))]
    return out


def first_true(flags: Sequence[bool], index: Sequence[int], start: int = 0, end: int | None = None) -> int | None:
    for f, i in zip(flags, index):
        if i < start or (end is not None and i >= end):
            continue
        if f:
            return i
    return None
