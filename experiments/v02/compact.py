"""Compact per-run records and the post-hoc decision rules applied to them.

A monitoring run is stored as per-batch arrays (rounded to 6 decimals):

* ``v02``: per qubit, the group drift log e-value ``d``, whether the
  threshold-independent drift gates (effect, persistence) were met ``g``,
  the threshold-channel log e-value ``t`` and the largest log e-value among
  forecasts that were alertable apart from the evidence gate ``f``; the
  nominal log thresholds ``bars``; and ``fc``, the issued q0 forecasts with
  their predictive intervals (for calibration analysis).
* ``v01``: per qubit, whether any v0.1 alert was raised ``any`` and the
  largest posterior probability among WARNING/CRITICAL drift/threshold
  alerts ``p``.
* ``naive``: per-batch pooled flip rate per qubit (input of the charts).

Every summary in results/runs.jsonl for the v0.2 experiments is a function
of these records and the run's config, so tools/verify_results.py can
recompute it.
"""

from __future__ import annotations

import math

import numpy as np

R = 6


def _r(x):
    if x is None:
        return None
    x = float(x)
    if not math.isfinite(x):
        return None
    return round(x, R)


def compact_v02(log: list[dict]) -> dict:
    qubits = sorted({int(q) for b in log if b.get("evidence") for q in b["evidence"]})
    out: dict = {
        "bars": None,
        "q": {str(q): {"d": [], "g": [], "t": [], "f": [], "fb": []} for q in qubits},
        "fc": [],
        "i": [],
    }
    for b in log:
        out["i"].append(b["i"])
        ev = b.get("evidence") or {}
        for q in qubits:
            e = ev.get(q, ev.get(str(q)))
            rec = out["q"][str(q)]
            if e is None:
                rec["d"].append(None)
                rec["g"].append(0)
                rec["t"].append(None)
                rec["f"].append(None)
                rec["fb"].append(None)
                continue
            # drift and threshold thresholds are fixed per session; the forecast
            # threshold log(n_contexts / alpha) changes when contexts appear
            bars = {"d": _r(e["drift_bar"]), "t": _r(e["thr_bar"])}
            if out["bars"] is None:
                out["bars"] = bars
            elif out["bars"] != bars:
                raise ValueError(f"per-qubit thresholds differ: {out['bars']} vs {bars}")
            rec["d"].append(_r(e["drift_log_e"]))
            rec["g"].append(int(bool(e["drift_gates_ok"])))
            rec["t"].append(_r(e["thr_log_e"]))
            rec["fb"].append(_r(e["fc_bar"]))
            al = [f["log_e"] for f in e["fc"] if f["alertable"]]
            rec["f"].append(_r(max(al)) if al else None)
            if q == qubits[0]:
                for f in e["fc"]:
                    if f["alertable"] and f.get("crossing"):
                        c = f["crossing"]
                        out["fc"].append(
                            [
                                b["i"],
                                _r(f["log_e"]),
                                _r(c["median_hours"]),
                                _r(c["p10_hours"]),
                                _r(c["p90_hours"]),
                                _r(e["fc_bar"]),
                            ]
                        )
    return out


def compact_v01(log: list[dict]) -> dict:
    qubits = sorted({int(q) for b in log for q in range(len(b["naive"]))})
    out = {str(q): {"any": [], "p": []} for q in qubits}
    for b in log:
        for q in qubits:
            mine = [a for a in b["alerts"] if a["qubit"] == q]
            out[str(q)]["any"].append(int(bool(mine)))
            ps = [
                a.get("probability", 0.0) or 0.0
                for a in mine
                if a["kind"] in ("drift", "threshold") and a["level"] in ("WARNING", "CRITICAL")
            ]
            out[str(q)]["p"].append(_r(max(ps)) if ps else 0.0)
    return out


# --------------------------------------------------------------------------- decision rules


def v02_alarms(rec: dict, q: int, c: float = 0.0) -> list[bool]:
    v = rec["v02"]
    bars = v["bars"]
    qr = v["q"][str(q)]
    out = []
    for d, g, t, f, fb in zip(qr["d"], qr["g"], qr["t"], qr["f"], qr["fb"]):
        hit = (
            (g and d is not None and d >= bars["d"] - c)
            or (t is not None and t >= bars["t"] - c)
            or (f is not None and f >= fb - c)
        )
        out.append(bool(hit))
    return out


def v02_channel_alarms(rec: dict, q: int, c: float, channel: str) -> list[bool]:
    v = rec["v02"]
    bars = v["bars"]
    qr = v["q"][str(q)]
    if channel == "drift":
        return [bool(g and d is not None and d >= bars["d"] - c) for d, g in zip(qr["d"], qr["g"])]
    if channel == "threshold":
        return [x is not None and x >= bars["t"] - c for x in qr["t"]]
    return [x is not None and x >= fb - c for x, fb in zip(qr["f"], qr["fb"])]


def v01_alarms(rec: dict, q: int, bar: float | None = None) -> list[bool]:
    """``bar=None``: any v0.1 alert (default v0.1). Otherwise WARNING/CRITICAL
    drift/threshold alerts with posterior probability >= bar."""
    r = rec["v01"][str(q)]
    if bar is None:
        return [bool(x) for x in r["any"]]
    return [p >= bar for p in r["p"]]


def shewhart_alarms(rec: dict, q: int, k: float, ref: int, shots_per_batch: int) -> list[bool]:
    rates = [row[q] for row in rec["naive"]]
    base = float(np.mean(rates[:ref]))
    sigma = math.sqrt(max(base * (1 - base), 1e-12) / shots_per_batch)
    return [i >= ref and r > base + k * sigma for i, r in enumerate(rates)]


def cusum_alarms(rec: dict, q: int, h: float, ref: int, shots_per_batch: int, kappa: float = 0.5) -> list[bool]:
    rates = [row[q] for row in rec["naive"]]
    base = float(np.mean(rates[:ref]))
    sigma = math.sqrt(max(base * (1 - base), 1e-12) / shots_per_batch)
    s, out = 0.0, []
    for i, r in enumerate(rates):
        if i < ref:
            out.append(False)
            continue
        s = max(0.0, s + (r - base) / sigma - kappa)
        out.append(s > h)
    return out


def naive_alarms(rec: dict, q: int, threshold: float) -> list[bool]:
    return [row[q] > threshold for row in rec["naive"]]


def method_alarms(rec: dict, q: int, method: str, params: dict) -> list[bool]:
    spb = params["shots_per_batch"]
    if method == "v02":
        return v02_alarms(rec, q, 0.0)
    if method == "v02cal":
        return v02_alarms(rec, q, params["c_star"])
    if method == "v01":
        return v01_alarms(rec, q, None)
    if method == "v01cal":
        return v01_alarms(rec, q, params["b_star"])
    if method == "shewhart":
        return shewhart_alarms(rec, q, params["k_star"], params["ref"], spb)
    if method == "cusum":
        return cusum_alarms(rec, q, params["h_star"], params["ref"], spb)
    if method == "naive":
        return naive_alarms(rec, q, params["threshold"])
    raise ValueError(method)


def first_true(flags: list[bool], start: int = 0, end: int | None = None, index: list[int] | None = None) -> int | None:
    """First batch index (``index`` maps positions to batch numbers) in [start, end)."""
    idx = index or list(range(len(flags)))
    for pos, f in enumerate(flags):
        i = idx[pos]
        if i < start or (end is not None and i >= end):
            continue
        if f:
            return i
    return None


def methods_available(rec: dict) -> list[str]:
    m = ["v02", "v02cal", "shewhart", "cusum", "naive"]
    if rec.get("v01") is not None:
        m += ["v01", "v01cal"]
    return m
