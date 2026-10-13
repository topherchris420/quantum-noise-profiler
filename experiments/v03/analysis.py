"""Summaries and criteria of the v0.3 study (experiments/V03_PREREGISTRATION.md),
as pure functions of the stored per-run records and the run config; used by
experiments/run_v03.py and, to recompute every recorded value, by
tools/verify_results.py."""

from __future__ import annotations

import itertools

import numpy as np
from v02.stats_utils import delay_summary, rate_with_ci

from .harness import first_true, group_channel_alarms, qubit_alarms

RO = "readout_error"
EF = "effective_flip_rate"


def _methods(config):
    return (("anytime", 0.0), ("cal", float(config["calibrated"]["c_star"])))


# --------------------------------------------------------------------------- Experiment G


def exp_g_summary(trials, config):
    shift = config["shift_at"]
    i_cross = config["ramp_crossing_batch"]
    minutes = config["batch_minutes"]
    out: dict = {}
    for sc in config["scenarios"]:
        ts = [t for t in trials if t["scenario"] == sc]
        res: dict = {"n_runs": len(ts)}
        for arch in ("v02", "v03"):
            r_arch: dict = {}
            for m, c in _methods(config):
                recs = [t[arch] for t in ts]
                if sc == "G7":
                    pre_false, det6, det6_ro, delays = [], [], [], []
                    for rec in recs:
                        f0, f1 = qubit_alarms(rec, 0, c), qubit_alarms(rec, 1, c)
                        pre_false.append(first_true(f0, rec["i"], 0, shift) is not None or any(f1))
                        i = first_true(f0, rec["i"], shift)
                        delays.append(None if i is None else i - shift)
                        det6.append(i is not None and i - shift <= 6)
                        if arch == "v03":
                            j = first_true(qubit_alarms(rec, 0, c, [RO]), rec["i"], shift)
                            det6_ro.append(j is not None and j - shift <= 6)
                    r = {
                        "false_alert": rate_with_ci(pre_false),
                        "q0_detected_within_6": rate_with_ci(det6),
                        "q0_delay": delay_summary(delays),
                    }
                    if det6_ro:
                        r["q0_readout_detected_within_6"] = rate_with_ci(det6_ro)
                elif sc == "G8":
                    early, lead, q1 = [], [], []
                    for rec in recs:
                        i = first_true(qubit_alarms(rec, 0, c), rec["i"])
                        early.append(i is not None and i < i_cross)
                        if i is not None:
                            lead.append((i_cross - i) * minutes)
                        q1.append(any(qubit_alarms(rec, 1, c)))
                    r = {
                        "early_detection": rate_with_ci(early),
                        "median_lead_min": float(np.median(lead)) if lead else None,
                        "detect_rate": len(lead) / len(recs),
                        "q1_false_alert": rate_with_ci(q1),
                    }
                else:
                    run_fa, post, by_metric, by_channel = [], [], {}, {}
                    for rec in recs:
                        flags = [qubit_alarms(rec, q, c) for q in (0, 1)]
                        run_fa.append(any(any(f) for f in flags))
                        post.append(any(first_true(f, rec["i"], shift) is not None for f in flags))
                        for metric in (EF, RO):
                            fm = [qubit_alarms(rec, q, c, [metric]) for q in (0, 1)]
                            by_metric.setdefault(metric, []).append(any(any(f) for f in fm))
                        for ch in ("drift", "threshold", "forecast"):
                            hit = any(any(group_channel_alarms(rec, k, c, ch)) for k in rec["g"])
                            by_channel.setdefault(ch, []).append(hit)
                    r = {
                        "run_false_alert": rate_with_ci(run_fa),
                        "post_shift_false_alert": rate_with_ci(post),
                        "run_false_alert_by_metric": {k: rate_with_ci(v)["rate"] for k, v in by_metric.items()},
                        "run_false_alert_by_channel": {k: rate_with_ci(v) for k, v in by_channel.items()},
                    }
                r_arch[m] = r
            res[arch] = r_arch
        res["contexts_q0_after_shift"] = {
            arch: sorted({c for t in ts for c in t["contexts_q0"][arch]["after"]})[:12] for arch in ("v02", "v03")
        }
        out[sc] = res
    pooled = [
        any(any(qubit_alarms(t["v03"], q, 0.0)) for q in (0, 1))
        for t in trials
        if t["scenario"] in ("G0", "G1", "G2", "G3", "G4", "G5", "G6")
    ]
    out["pooled_G0_G6_v03_anytime_run_false_alert"] = rate_with_ci(pooled)
    return out


def exp_g_criteria(s):
    crit = []
    for sc in ("G1", "G2", "G3", "G4", "G5", "G6"):
        crit.append(
            (
                f"G.C1/{sc}",
                f"v0.3 calibrated, workload change {sc} on unchanged hardware: run-level false-alert rate",
                0.10,
                s[sc]["v03"]["cal"]["run_false_alert"]["rate"],
                "<=",
            )
        )
    crit.append(
        (
            "G.C2",
            "v0.3 calibrated, stable control G0: run-level false-alert rate",
            0.10,
            s["G0"]["v03"]["cal"]["run_false_alert"]["rate"],
            "<=",
        )
    )
    crit.append(
        (
            "G.C3",
            "v0.3 anytime-valid, G0-G6 pooled: Wilson upper 95% bound of the run-level false-alert rate",
            0.10,
            s["pooled_G0_G6_v03_anytime_run_false_alert"]["ci95"][1],
            "<=",
        )
    )
    crit.append(
        (
            "G.C4",
            "v0.3 calibrated, G7: q0 readout x1.5 at the workload change detected by its readout probes within 6 batches",
            0.90,
            s["G7"]["v03"]["cal"]["q0_readout_detected_within_6"]["rate"],
            ">=",
        )
    )
    crit.append(
        (
            "G.C5",
            "v0.3 calibrated, G8 ramp: early-detection fraction",
            0.80,
            s["G8"]["v03"]["cal"]["early_detection"]["rate"],
            ">=",
        )
    )
    v3, v2 = s["G8"]["v03"]["cal"]["median_lead_min"], s["G8"]["v02"]["cal"]["median_lead_min"]
    crit.append(
        (
            "G.C6",
            "G8 ramp: v0.3 calibrated median lead minus v0.2-architecture calibrated median lead (min)",
            -30.0,
            (v3 if v3 is not None else -1e9) - (v2 if v2 is not None else -1e9),
            ">=",
        )
    )
    crit.append(
        (
            "G.M1",
            "manipulation check: v0.2 architecture (calibrated) still alarms on G5 (idle-time workload)",
            0.50,
            s["G5"]["v02"]["cal"]["run_false_alert"]["rate"],
            ">=",
        )
    )
    return crit


# --------------------------------------------------------------------------- Experiment H


def exp_h_summary(trials, config):
    out: dict = {}
    for sc, spec in config["scenarios"].items():
        truth = spec.get("truth")
        for design in config["designs"]:
            ts = [t for t in trials if t["scenario"] == sc and t["design"] == design]
            if not ts:
                continue
            st = [t["status"] for t in ts]
            ok = [t for t in ts if t["status"] == "ok"]
            res = {
                "n": len(ts),
                "ok": st.count("ok"),
                "insufficient_evidence": st.count("insufficient_evidence"),
                "model_misspecification": st.count("model_misspecification"),
                "not_ok_rate": 1 - len(ok) / len(ts),
            }
            if truth is not None:
                cov = [t["ci_low"] <= truth <= t["ci_high"] for t in ok]
                res["coverage_among_ok"] = float(np.mean(cov)) if cov else None
                res["covered"] = int(sum(cov))
                res["false_confidence_rate"] = (len(ok) - sum(cov)) / len(ts)
            else:
                res["coverage_among_ok"] = None
                res["false_confidence_rate"] = len(ok) / len(ts)
            nok = [t for t in ts if t["status"] != "ok"]
            res["frac_insufficient_among_not_ok"] = (
                sum(t["status"] == "insufficient_evidence" for t in nok) / len(nok) if nok else None
            )
            res["frac_misspec_among_not_ok"] = (
                sum(t["status"] == "model_misspecification" for t in nok) / len(nok) if nok else None
            )
            codes: dict = {}
            for t in ts:
                for c in t["codes"]:
                    codes[c] = codes.get(c, 0) + 1
            res["reason_codes"] = dict(sorted(codes.items()))
            if ok:
                res["median_reported_us"] = float(np.median([t["value"] for t in ok]) * 1e6)
            out[f"{sc}/{design}"] = res
    for design in config["designs"]:
        keys = [f"{sc}/{design}" for sc in ("H1", "H2", "H3") if f"{sc}/{design}" in out]
        n_ok = sum(out[k]["ok"] for k in keys)
        out[f"valid_pooled/{design}"] = {
            "ok": n_ok,
            "covered": sum(out[k]["covered"] for k in keys),
            "coverage_among_ok": (sum(out[k]["covered"] for k in keys) / n_ok) if n_ok else None,
        }
    return out


def exp_h_criteria(s):
    d = "interleaved"
    crit = [
        (
            "H.C1",
            "interleaved design, H11 (v0.2 D11 drift in acquisition order): false-confidence rate",
            0.10,
            s[f"H11/{d}"]["false_confidence_rate"],
            "<=",
        )
    ]
    for sc, what in (("H11s", "slow AR(1) drift"), ("H11l", "linear drift")):
        crit.append(
            (
                f"H.C2/{sc}",
                f"interleaved design, {sc} ({what}): false-confidence rate",
                0.10,
                s[f"{sc}/{d}"]["false_confidence_rate"],
                "<=",
            )
        )
    for sc in ("H1", "H2", "H3"):
        crit.append(
            (
                f"H.C3/{sc}",
                f"interleaved design, {sc} valid single exponential: loss of valid estimates",
                0.10,
                s[f"{sc}/{d}"]["not_ok_rate"],
                "<=",
            )
        )
    crit.append(
        (
            "H.C4",
            "interleaved design, H1-H3 pooled: coverage among OK",
            0.90,
            s[f"valid_pooled/{d}"]["coverage_among_ok"] or 0.0,
            ">=",
        )
    )
    for sc in ("H1", "H2", "H3"):
        crit.append(
            (
                f"H.C4b/{sc}",
                f"interleaved design, {sc}: coverage among OK",
                0.85,
                s[f"{sc}/{d}"]["coverage_among_ok"] or 0.0,
                ">=",
            )
        )
    crit.append(
        (
            "H.C5/fc",
            "interleaved design: max false-confidence rate over H4, H5, H6, H10, H12",
            0.10,
            max(s[f"{sc}/{d}"]["false_confidence_rate"] for sc in ("H4", "H5", "H6", "H10", "H12")),
            "<=",
        )
    )
    crit.append(
        ("H.C5/abst", "interleaved design, H8 bi-exponential: abstention rate", 0.50, s[f"H8/{d}"]["not_ok_rate"], ">=")
    )
    for sc in ("H4", "H5"):
        v = s[f"{sc}/{d}"]["frac_insufficient_among_not_ok"]
        crit.append(
            (
                f"H.C5/{sc}",
                f"interleaved design, {sc}: non-OK labelled INSUFFICIENT_EVIDENCE",
                0.90,
                1.0 if v is None else v,
                ">=",
            )
        )
    for sc in ("H6", "H8"):
        v = s[f"{sc}/{d}"]["frac_misspec_among_not_ok"]
        crit.append(
            (
                f"H.C5/{sc}",
                f"interleaved design, {sc}: non-OK labelled MODEL_MISSPECIFICATION",
                0.90,
                0.0 if v is None else v,
                ">=",
            )
        )
    crit.append(
        (
            "H.C6/coverage",
            "interleaved design, H13 Aer thermal relaxation: coverage among OK",
            0.90,
            s[f"H13/{d}"]["coverage_among_ok"] or 0.0,
            ">=",
        )
    )
    crit.append(
        (
            "H.C6/loss",
            "interleaved design, H13 Aer thermal relaxation: not-OK rate",
            0.10,
            s[f"H13/{d}"]["not_ok_rate"],
            "<=",
        )
    )
    crit.append(
        (
            "H.M1",
            "manipulation check: v0.2 sequential design, H11: false-confidence rate (expected > 0.10)",
            0.10,
            s["H11/sequential"]["false_confidence_rate"],
            ">=",
        )
    )
    return crit


# --------------------------------------------------------------------------- Experiment I


def _pool(outs: list[dict], days: float, n_qubits: int) -> dict:
    jobs = sum(o["jobs"] for o in outs)
    qd = len(outs) * n_qubits * days
    return {
        "failed": sum(o["failed"] for o in outs) / jobs,
        "cal_per_qday": sum(o["calibrations"] for o in outs) / qd,
        "triggered_per_qday": sum(o["triggered"] for o in outs) / qd,
        "triggered_above_per_qday": sum(o["triggered_above"] for o in outs) / qd,
        "triggered_degraded_per_qday": sum(o["triggered_degraded"] for o in outs) / qd,
        "triggered_false_per_qday": sum(o["triggered_false"] for o in outs) / qd,
        "downtime_fraction": sum(o["downtime"] for o in outs) / (jobs + sum(o["downtime"] for o in outs)),
        "excess_per_job": sum(o["excess"] for o in outs) / jobs,
    }


def _frontier(pooled: dict, fixed: list[str]) -> list[tuple[float, float]]:
    return [(pooled[p]["cal_per_qday"], pooled[p]["failed"]) for p in fixed]


def _interp(points, x):
    pts = sorted(points)
    xs = [p[0] for p in pts]
    if x < xs[0] - 1e-12 or x > xs[-1] + 1e-12:
        return None
    return float(np.interp(x, xs, [p[1] for p in pts]))


def _interp_inv(points, y):
    """Smallest calibration rate at which the (time-shared) fixed schedules
    reach failed fraction ``y``. If ``y`` is below every schedule's failed
    fraction, returns the largest schedule rate with ``bounded=True``: a fixed
    schedule would need at least that many calibrations (a conservative value
    for the savings). None if ``y`` is above every schedule's failed fraction."""
    pts = sorted(points)
    ys = [p[1] for p in pts]
    if y > max(ys) + 1e-12:
        return None, False
    if y < min(ys) - 1e-12:
        return pts[-1][0], True
    best = None
    for (x0, y0), (x1, y1) in itertools.pairwise(pts):
        lo, hi = min(y0, y1), max(y0, y1)
        if lo - 1e-12 <= y <= hi + 1e-12:
            x = x0 if y0 == y1 else x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            best = x if best is None else min(best, x)
    if best is None:  # y equals a schedule's failed fraction at a single point
        best = min(x for x, yy in pts if abs(yy - y) <= 1e-12)
    return best, False


def _contrasts(pooled: dict, fixed: list[str], policy: str) -> dict:
    pts = _frontier(pooled, fixed)
    p = pooled[policy]
    f = _interp(pts, p["cal_per_qday"])
    x, bounded = _interp_inv(pts, p["failed"])
    return {
        "frontier_failed_at_same_calibrations": f,
        "failed_minus_frontier": None if f is None else p["failed"] - f,
        "frontier_calibrations_at_same_failed": x,
        "calibrations_saved_per_qday": None if x is None else x - p["cal_per_qday"],
        "savings_is_lower_bound": bounded,
    }


def _paired(pooled_a: dict, pooled_b: dict) -> dict:
    return {
        "failed_diff": pooled_a["failed"] - pooled_b["failed"],
        "cal_diff": pooled_a["cal_per_qday"] - pooled_b["cal_per_qday"],
    }


def exp_i_summary(trials, config):
    days, nq = config["days"], config["n_qubits"]
    fixed = config["frontier_policies"]
    monitors = config["monitor_policies"]
    rng_seed = config["bootstrap_seed"]
    B = config["bootstrap_samples"]
    out: dict = {}
    for sc in config["scenarios"]:
        ts = [t for t in trials if t["scenario"] == sc]
        pols = list(ts[0]["outcomes"])
        pooled = {p: _pool([t["outcomes"][p] for t in ts], days, nq) for p in pols}
        res: dict = {"n_runs": len(ts), "policies": pooled, "contrasts": {}}
        rng = np.random.default_rng([rng_seed, config["scenarios"].index(sc)])
        idx = rng.integers(0, len(ts), size=(B, len(ts)))
        pairs = config["paired_comparisons"]
        boot: dict = {m: {"f": [], "x": []} for m in monitors}
        boot_pairs: dict = {f"{a} - {b}": {"failed_diff": [], "cal_diff": []} for a, b in pairs}
        needed = sorted({*fixed, *monitors, *(p for ab in pairs for p in ab)})
        for b in range(B):
            sample = [ts[i] for i in idx[b]]
            pb = {p: _pool([t["outcomes"][p] for t in sample], days, nq) for p in needed}
            for m in monitors:
                cb = _contrasts(pb, fixed, m)
                boot[m]["f"].append(cb["failed_minus_frontier"])
                boot[m]["x"].append(cb["calibrations_saved_per_qday"])
            for a, bb in pairs:
                d = _paired(pb[a], pb[bb])
                for k in ("failed_diff", "cal_diff"):
                    boot_pairs[f"{a} - {bb}"][k].append(d[k])

        def ci(v):
            v = [x for x in v if x is not None]
            if len(v) < 0.95 * B:
                return None
            return [float(np.quantile(v, 0.025)), float(np.quantile(v, 0.975))]

        for m in monitors:
            point = _contrasts(pooled, fixed, m)
            point["failed_minus_frontier_ci95"] = ci(boot[m]["f"])
            point["calibrations_saved_ci95"] = ci(boot[m]["x"])
            res["contrasts"][m] = point
        res["paired"] = {}
        for a, bb in pairs:
            d = _paired(pooled[a], pooled[bb])
            key = f"{a} - {bb}"
            res["paired"][key] = {
                **d,
                "failed_diff_ci95": ci(boot_pairs[key]["failed_diff"]),
                "cal_diff_ci95": ci(boot_pairs[key]["cal_diff"]),
            }
        oracle_gain = pooled["fixed24"]["failed"] - pooled["oracle+24"]["failed"]
        res["fraction_of_oracle_gain"] = {
            m: (pooled["fixed24"]["failed"] - pooled[m]["failed"]) / oracle_gain if oracle_gain > 0 else None
            for m in [*monitors, "cusum+24", "naive+24", "shewhart+24"]
            if m in pooled and m.endswith("+24")
        }
        out[sc] = res
    return out


def exp_i_criteria(s):
    crit = []
    for sc in ("I1", "I2", "I3", "I4"):
        c = s[sc]["contrasts"]["eng_any+24"]
        hi = (c["failed_minus_frontier_ci95"] or [None, 1.0])[1]
        crit.append(
            (
                f"I.C1/{sc}",
                f"{sc}: v0.3 warnings + daily calibration, failed-job fraction minus the fixed-schedule frontier at the "
                "same calibration rate (upper 95% bootstrap bound)",
                0.0,
                hi if hi is not None else 1.0,
                "<=",
            )
        )
    for sc in ("I1", "I2", "I3", "I4"):
        c = s[sc]["contrasts"]["eng_any_only"]
        lo = (c["calibrations_saved_ci95"] or [-1.0, None])[0]
        crit.append(
            (
                f"I.C2/{sc}",
                f"{sc}: v0.3 warnings only (no schedule), calibrations per qubit-day saved against the fixed-schedule "
                "frontier at the same failed-job fraction (lower 95% bootstrap bound)",
                0.0,
                lo if lo is not None else -1.0,
                ">=",
            )
        )
    crit.append(
        (
            "I.C3",
            "I0 stable device: v0.3 warnings only (no schedule), calibrations per qubit-day minus the daily schedule's",
            0.0,
            s["I0"]["policies"]["eng_any_only"]["cal_per_qday"] - s["I0"]["policies"]["fixed24"]["cal_per_qday"],
            "<=",
        )
    )
    return crit


SUMMARY = {
    "V03_G_workload_probes": exp_g_summary,
    "V03_H_sweep_drift": exp_h_summary,
    "V03_I_operational": exp_i_summary,
}
CRITERIA = {
    "V03_G_workload_probes": exp_g_criteria,
    "V03_H_sweep_drift": exp_h_criteria,
    "V03_I_operational": exp_i_criteria,
}

__all__ = ["CRITERIA", "SUMMARY"]
