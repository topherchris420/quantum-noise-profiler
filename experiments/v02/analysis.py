"""Summaries and criteria for the v0.2 study, as pure functions of the
stored per-run records and the run config (re-used by tools/verify_results.py)."""

from __future__ import annotations

import math

import numpy as np

from .compact import first_true, method_alarms, v02_alarms, v02_channel_alarms
from .stats_utils import delay_summary, rate_with_ci, wilson

C_GRID = [round(0.25 * i, 2) for i in range(15)]  # 0 .. 3.5
K_GRID = [round(2.0 + 0.05 * i, 2) for i in range(81)]  # 2.00 .. 6.00
H_GRID = [round(1.0 + 0.5 * i, 1) for i in range(79)]  # 1.0 .. 40.0
B_GRID = [0.95, 0.96, 0.97, 0.98, 0.99, 0.995, 0.998, 0.999, 0.9995, 0.9999, 0.99999]
CAL_TARGET = 0.08


def _qubits(rec) -> list[int]:
    return sorted(int(q) for q in rec["v02"]["q"])


def _any_alarm(rec, method, params, qubits=None, start=0, end=None) -> bool:
    qs = qubits if qubits is not None else _qubits(rec)
    idx = rec["v02"]["i"]
    return any(first_true(method_alarms(rec, q, method, params), start, end, idx) is not None for q in qs)


# --------------------------------------------------------------------------- calibration


def calibration_summary(trials, config):
    spb = config["shots_per_batch"]
    ref = config["ref"]
    conds = config["conditions"]
    by = {c: [t for t in trials if t["cond"] == c] for c in conds}
    out: dict = {
        "n_runs": {c: len(v) for c, v in by.items()},
        "n_runs_v01": {c: sum(t.get("v01") is not None for t in v) for c, v in by.items()},
    }

    def fa_curve(method, grid, key):
        curve = {}
        for g in grid:
            params = {"shots_per_batch": spb, "ref": ref, key: g}
            row = {}
            for c, ts in by.items():
                ts2 = [t for t in ts if method not in ("v01cal",) or t.get("v01") is not None]
                row[c] = float(np.mean([_any_alarm(t, method, params) for t in ts2]))
            curve[str(g)] = row
        return curve

    curves = {
        "v02cal": fa_curve("v02cal", C_GRID, "c_star"),
        "shewhart": fa_curve("shewhart", K_GRID, "k_star"),
        "cusum": fa_curve("cusum", H_GRID, "h_star"),
        "v01cal": fa_curve("v01cal", B_GRID, "b_star"),
    }
    out["fa_curves"] = curves

    def choose(curve, grid, prefer):
        ok = [g for g in grid if max(curve[str(g)].values()) <= CAL_TARGET]
        if not ok:
            return None
        return max(ok) if prefer == "max" else min(ok)

    out["chosen"] = {
        "c_star": choose(curves["v02cal"], C_GRID, "max"),
        "k_star": choose(curves["shewhart"], K_GRID, "min"),
        "h_star": choose(curves["cusum"], H_GRID, "min"),
        "b_star": choose(curves["v01cal"], B_GRID, "min"),
    }
    out["chosen_max_fa"] = {
        m: (None if out["chosen"][p] is None else max(curves[m][str(out["chosen"][p])].values()))
        for m, p in (("v02cal", "c_star"), ("shewhart", "k_star"), ("cusum", "h_star"), ("v01cal", "b_star"))
    }
    out["v02_nominal_fa"] = curves["v02cal"]["0.0"]
    return out


# --------------------------------------------------------------------------- helpers


def _params(config):
    p = dict(config["calibrated"])
    p.update(shots_per_batch=config["shots_per_batch"], ref=config["ref"], threshold=config.get("threshold", 0.05))
    return p


def _methods(ts):
    m = ["v02", "v02cal", "shewhart", "cusum"]
    if ts and all(t.get("v01") is not None for t in ts):
        m += ["v01", "v01cal"]
    return m


# --------------------------------------------------------------------------- Experiment A


def exp_a_summary(trials, config):
    params = _params(config)
    out: dict = {}
    for cond in config["conditions"]:
        ts = [t for t in trials if t["cond"] == cond]
        n_b = ts[0]["n_batches"]
        hours = n_b * config["batch_minutes"] / 60
        res: dict = {"n_runs": len(ts), "n_batches": n_b}
        sub = [t for t in ts if t.get("v01") is not None]
        for m in ["v02", "v02cal", "shewhart", "cusum", "v01", "v01cal"]:
            pool = sub if m.startswith("v01") else ts
            if not pool:
                continue
            run_flags, qubit_flags, n_alarm_batches = [], [], []
            for t in pool:
                per_q = [method_alarms(t, q, m, params) for q in _qubits(t)]
                qubit_flags += [any(f) for f in per_q]
                run_flags.append(any(any(f) for f in per_q))
                n_alarm_batches.append(sum(sum(f) for f in per_q))
            res[m] = {
                "run_false_alert": rate_with_ci(run_flags),
                "qubit_false_alert": rate_with_ci(qubit_flags),
                "false_alert_batches_per_run": float(np.mean(n_alarm_batches)),
                "false_alert_batches_per_hour": float(np.mean(n_alarm_batches) / hours),
                "n_runs": len(pool),
            }
        for m, c in (("v02", 0.0), ("v02cal", params["c_star"])):
            res[m]["per_channel_run_false_alert"] = {
                ch: rate_with_ci([any(any(v02_channel_alarms(t, q, c, ch)) for q in _qubits(t)) for t in ts])["rate"]
                for ch in ("drift", "threshold", "forecast")
            }
        out[cond] = res
    return out


def exp_a_criteria(s):
    crit = []
    for cond in ("A1", "A2", "A3", "A4"):
        crit.append(
            (
                "A.C1/" + cond,
                f"v02 run-level false-alert rate, {cond}: Wilson upper 95% bound",
                0.10,
                s[cond]["v02"]["run_false_alert"]["ci95"][1],
                "<=",
            )
        )
    for cond in ("A1", "A2", "A3", "A4"):
        r = s[cond]["v02cal"]["run_false_alert"]
        crit.append(("A.C2/" + cond + "/point", f"v02cal run-level false-alert rate, {cond}", 0.10, r["rate"], "<="))
        crit.append(("A.C2/" + cond + "/upper", f"v02cal Wilson upper bound, {cond}", 0.13, r["ci95"][1], "<="))
    crit.append(
        ("A.C3", "v02 24 h session (A5): Wilson upper bound", 0.10, s["A5"]["v02"]["run_false_alert"]["ci95"][1], "<=")
    )
    crit.append(
        (
            "A.C4",
            "v02cal 24 h session (A5): run-level false-alert rate",
            0.10,
            s["A5"]["v02cal"]["run_false_alert"]["rate"],
            "<=",
        )
    )
    return crit


# --------------------------------------------------------------------------- Experiment B


def exp_b_summary(trials, config):
    params = _params(config)
    out: dict = {}
    pooled_cov = {"v02": [], "v02cal": []}
    for cond, spec in config["conditions"].items():
        ts = [t for t in trials if t["cond"] == cond]
        i_cross = spec["i_cross"]
        hours = ts[0]["n_batches"] * config["batch_minutes"] / 60
        res: dict = {"n_runs": len(ts), "i_cross": i_cross}
        for m in [*_methods(ts), "naive"]:
            first, early, lead, q1_any, q1_batches = [], [], [], [], []
            for t in ts:
                i = first_true(method_alarms(t, 0, m, params), 0, None, t["v02"]["i"])
                first.append(i)
                early.append(i is not None and i < i_cross)
                if i is not None:
                    lead.append((i_cross - i) * config["batch_minutes"])
                f1 = method_alarms(t, 1, m, params)
                q1_any.append(any(f1))
                q1_batches.append(sum(f1))
            res[m] = {
                "detect_rate": float(np.mean([x is not None for x in first])),
                "early_detection": rate_with_ci(early),
                "median_lead_min": float(np.median(lead)) if lead else None,
                "lead_q25_min": float(np.quantile(lead, 0.25)) if lead else None,
                "lead_q75_min": float(np.quantile(lead, 0.75)) if lead else None,
                "first_alert_batch": delay_summary(first),
                "q1_run_false_alert": rate_with_ci(q1_any),
                "q1_false_alert_batches_per_run": float(np.mean(q1_batches)),
                "q1_false_alert_batches_per_hour": float(np.mean(q1_batches) / hours),
            }
        for m, c in (("v02", 0.0), ("v02cal", params["c_star"])):
            cov, n = 0, 0
            for t in ts:
                for i, log_e, _med, p10, p90, fb in t["v02"]["fc"]:
                    if log_e is None or log_e < fb - c or i >= i_cross or p10 is None:
                        continue
                    truth = (i_cross - i) * config["batch_minutes"] / 60
                    hi = math.inf if p90 is None else p90
                    cov += p10 <= truth <= hi
                    n += 1
                    pooled_cov[m].append(bool(p10 <= truth <= hi))
            res[m]["forecast_interval_coverage_80"] = {"covered": cov, "n": n, "rate": cov / n if n else None}
        out[cond] = res
    out["pooled_forecast_coverage_80"] = {m: rate_with_ci(v) if v else None for m, v in pooled_cov.items()}
    ts_all = trials
    out["pooled_q1_run_false_alert_v02cal"] = rate_with_ci([any(method_alarms(t, 1, "v02cal", params)) for t in ts_all])
    return out


def exp_b_criteria(s):
    b1 = s["B1"]
    crit = [
        ("B.C1/B1", "v02cal early-detection fraction, B1", 0.80, b1["v02cal"]["early_detection"]["rate"], ">="),
        ("B.C1/B2", "v02cal early-detection fraction, B2", 0.80, s["B2"]["v02cal"]["early_detection"]["rate"], ">="),
    ]
    best_chart = max(b1[m]["median_lead_min"] or -1e9 for m in ("shewhart", "cusum"))
    crit.append(
        (
            "B.C2",
            "v02cal median lead minus best chart median lead, B1 (min)",
            -30.0,
            (b1["v02cal"]["median_lead_min"] or -1e9) - best_chart,
            ">=",
        )
    )
    if "v01cal" in b1:
        crit.append(
            (
                "B.C3",
                "v02cal median lead minus v01cal median lead, B1 (min)",
                0.0,
                (b1["v02cal"]["median_lead_min"] or -1e9) - (b1["v01cal"]["median_lead_min"] or -1e9),
                ">=",
            )
        )
    cov = s["pooled_forecast_coverage_80"]["v02"]
    crit.append(
        ("B.C4/low", "coverage of v02 80% predictive crossing intervals", 0.70, cov["rate"] if cov else 0.0, ">=")
    )
    crit.append(
        ("B.C4/high", "coverage of v02 80% predictive crossing intervals", 0.90, cov["rate"] if cov else 1.0, "<=")
    )
    crit.append(
        (
            "B.C5",
            "v02cal run-level q1 false-alert rate, B1+B2",
            0.10,
            s["pooled_q1_run_false_alert_v02cal"]["rate"],
            "<=",
        )
    )
    return crit


# --------------------------------------------------------------------------- Experiment C


def exp_c_summary(trials, config):
    params = _params(config)
    step = config["step_at"]
    out: dict = {}
    all_false = {}
    for cond in config["conditions"]:
        ts = [t for t in trials if t["cond"] == cond]
        ratio = config["conditions"][cond]
        res: dict = {"n_runs": len(ts)}
        for m in _methods(ts):
            pre, q1, delays, clean_det = [], [], [], []
            for t in ts:
                idx = t["v02"]["i"]
                f0 = method_alarms(t, 0, m, params)
                end0 = step if ratio != 1.0 else None
                pre_false = first_true(f0, 0, end0, idx) is not None
                q1_false = any(method_alarms(t, 1, m, params))
                pre.append(pre_false)
                q1.append(q1_false)
                all_false.setdefault(m, []).append(pre_false or q1_false)
                if ratio != 1.0:
                    i = first_true(f0, step, None, idx)
                    d = None if i is None else i - step
                    delays.append(d)
                    if not pre_false:
                        clean_det.append(d is not None)
            r = {
                "q0_prestep_false_alert": rate_with_ci(pre),
                "q1_false_alert": rate_with_ci(q1),
                "run_false_alert": rate_with_ci([a or b for a, b in zip(pre, q1)]),
            }
            if ratio != 1.0:
                r["delay"] = delay_summary(delays)
                for w in (5, 6, 24):
                    r[f"within_{w}"] = rate_with_ci([d is not None and d <= w for d in delays])
                r["detect_rate_given_clean_prestep"] = float(np.mean(clean_det)) if clean_det else None
            res[m] = r
        out[cond] = res
    out["pooled_run_false_alert"] = {m: rate_with_ci(v) for m, v in all_false.items()}
    return out


def exp_c_criteria(s):
    x12 = s["x1.2"]
    crit = [
        ("C.C1", "v02cal x1.5 detected within 6 batches", 0.90, s["x1.5"]["v02cal"]["within_6"]["rate"], ">="),
        ("C.C2", "v02cal x1.2 detected within 24 batches", 0.50, x12["v02cal"]["within_24"]["rate"], ">="),
        (
            "C.C3",
            "v02cal x1.1 detected within 5 batches (20 circuits)",
            0.80,
            s["x1.1"]["v02cal"]["within_5"]["rate"],
            ">=",
        ),
        (
            "C.C4",
            "v02cal minus best chart: x1.2 within 24",
            -0.10,
            x12["v02cal"]["within_24"]["rate"] - max(x12[m]["within_24"]["rate"] for m in ("shewhart", "cusum")),
            ">=",
        ),
    ]
    if "v01cal" in x12:
        crit.append(
            (
                "C.C5",
                "v02cal minus v01cal: x1.2 within 24",
                0.0,
                x12["v02cal"]["within_24"]["rate"] - x12["v01cal"]["within_24"]["rate"],
                ">=",
            )
        )
    crit.append(
        (
            "C.C6",
            "v02cal run-level false-alert rate, all conditions",
            0.10,
            s["pooled_run_false_alert"]["v02cal"]["rate"],
            "<=",
        )
    )
    return crit


# --------------------------------------------------------------------------- Experiment D


def exp_d_summary(trials, config):
    out: dict = {}
    for sc, spec in config["scenarios"].items():
        ts = [t for t in trials if t["scenario"] == sc]
        truth = spec.get("truth")
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
            res["false_confidence_rate"] = (len(ok) - sum(cov)) / len(ts)
        else:
            res["coverage_among_ok"] = None
            res["false_confidence_rate"] = len(ok) / len(ts)
        nok = [t for t in ts if t["status"] != "ok"]
        res["frac_insufficient_among_not_ok"] = (
            (sum(t["status"] == "insufficient_evidence" for t in nok) / len(nok)) if nok else None
        )
        res["frac_misspec_among_not_ok"] = (
            (sum(t["status"] == "model_misspecification" for t in nok) / len(nok)) if nok else None
        )
        codes: dict = {}
        for t in ts:
            for c in t["codes"]:
                codes[c] = codes.get(c, 0) + 1
        res["reason_codes"] = dict(sorted(codes.items()))
        if ok:
            res["median_reported_us"] = float(np.median([t["value"] for t in ok]) * 1e6)
        out[sc] = res
    return out


def exp_d_criteria(s):
    crit = []
    for sc in ("D1", "D2", "D3"):
        crit.append((f"D.C1/{sc}", f"{sc} coverage among OK", 0.90, s[sc]["coverage_among_ok"] or 0.0, ">="))
    for sc in ("D1", "D2", "D3"):
        crit.append((f"D.C2/{sc}", f"{sc} loss of valid estimates", 0.10, s[sc]["not_ok_rate"], "<="))
    crit.append(
        (
            "D.C3",
            "D1-D5 max false-confidence rate",
            0.10,
            max(s[sc]["false_confidence_rate"] for sc in ("D1", "D2", "D3", "D4", "D5")),
            "<=",
        )
    )
    crit.append(("D.C4", "D6 fluctuating T1 false-confidence rate", 0.10, s["D6"]["false_confidence_rate"], "<="))
    crit.append(("D.C5", "D8 bi-exponential abstention rate", 0.50, s["D8"]["not_ok_rate"], ">="))
    for sc in ("D10", "D11", "D12"):
        crit.append((f"D.C6/{sc}", f"{sc} false-confidence rate", 0.10, s[sc]["false_confidence_rate"], "<="))
    for sc in ("D4", "D5"):
        v = s[sc]["frac_insufficient_among_not_ok"]
        crit.append((f"D.C7/{sc}", f"{sc} non-OK labelled INSUFFICIENT_EVIDENCE", 0.90, 1.0 if v is None else v, ">="))
    for sc in ("D6", "D8"):
        v = s[sc]["frac_misspec_among_not_ok"]
        crit.append((f"D.C8/{sc}", f"{sc} non-OK labelled MODEL_MISSPECIFICATION", 0.90, 0.0 if v is None else v, ">="))
    crit.append(("D.C9/coverage", "D13 Aer coverage among OK", 0.90, s["D13"]["coverage_among_ok"] or 0.0, ">="))
    crit.append(("D.C9/loss", "D13 Aer not-OK rate", 0.10, s["D13"]["not_ok_rate"], "<="))
    return crit


# --------------------------------------------------------------------------- Experiment E


def exp_e_summary(trials, config):
    c_star = config["calibrated"]["c_star"]
    shift = config["shift_at"]
    out: dict = {}
    for sc in config["scenarios"]:
        ts = [t for t in trials if t["scenario"] == sc]
        res: dict = {"n_runs": len(ts)}
        for mode in ("bucket", "exact"):
            r = {}
            for m, c in (("v02", 0.0), ("v02cal", c_star)):
                recs = [{"v02": t["v02"][mode]} for t in ts]
                run_fa, post_fa, q0_det = [], [], []
                for rec in recs:
                    idx = rec["v02"]["i"]
                    flags = {q: v02_alarms(rec, q, c) for q in _qubits(rec)}
                    if sc == "E7":
                        q0_det.append(first_true(flags[0], shift, None, idx) is not None)
                        run_fa.append(first_true(flags[0], 0, shift, idx) is not None or any(flags.get(1, [])))
                    else:
                        run_fa.append(any(any(f) for f in flags.values()))
                        post_fa.append(any(first_true(f, shift, None, idx) is not None for f in flags.values()))
                r[m] = {"run_false_alert": rate_with_ci(run_fa)}
                if post_fa:
                    r[m]["post_shift_false_alert"] = rate_with_ci(post_fa)
                if q0_det:
                    r[m]["q0_detection_after_shift"] = rate_with_ci(q0_det)
            r["contexts_after_shift_q0"] = sorted({ctx for t in ts for ctx in t["contexts"][mode]["after"]})[:8]
            res[mode] = r
        out[sc] = res
    return out


def exp_e_criteria(s):
    crit = []
    for mode, tag in (("exact", "E.C1"), ("bucket", "E.C2")):
        for sc in ("E1", "E2", "E3", "E4", "E5", "E6"):
            crit.append(
                (
                    f"{tag}/{sc}",
                    f"v02cal {mode} contexts: run-level false-alert rate, {sc}",
                    0.10,
                    s[sc][mode]["v02cal"]["run_false_alert"]["rate"],
                    "<=",
                )
            )
    return crit


# --------------------------------------------------------------------------- Experiment F


def _jeffreys_width(k, n):
    from scipy import stats as sps

    return float(sps.beta.ppf(0.975, k + 0.5, n - k + 0.5) - sps.beta.ppf(0.025, k + 0.5, n - k + 0.5))


def exp_f_summary(trials, config):
    c_star = config["calibrated"]["c_star"]
    step = config["step_at"]
    out: dict = {"frameworks": {}}
    for fw in ("qiskit", "cirq"):
        fwres: dict = {}
        for cond in ("F1", "F2"):
            ts = [t for t in trials if t["framework"] == fw and t["cond"] == cond]
            labels = sorted({int(q) for t in ts for q in t["counts"]})
            ctxs = sorted({f"{q}:{c}" for t in ts for q, cs in t["counts"].items() for c in cs})
            fa, det6, delays = [], [], []
            for t in ts:
                idx = t["v02"]["i"]
                flags = {q: v02_alarms(t, q, c_star) for q in _qubits(t)}
                if cond == "F1":
                    fa.append(any(any(f) for f in flags.values()))
                else:
                    i = first_true(flags[3], step, None, idx)
                    delays.append(None if i is None else i - step)
                    det6.append(i is not None and i - step <= 6)
                    fa.append(first_true(flags[3], 0, step, idx) is not None or any(flags[7]))
            per_ctx = {}
            for qc in ctxs:
                q, c = qc.split(":", 1)
                run_means, widths = [], []
                for t in ts:
                    ks, ns = t["counts"][q][c]
                    rng = range(len(ks)) if cond == "F1" else range(min(step, len(ks)))
                    run_means.append(float(np.mean([ks[i] / ns[i] for i in rng])))
                    widths.append(float(np.mean([_jeffreys_width(ks[i], ns[i]) for i in rng])))
                per_ctx[qc] = {
                    "mean_rate": float(np.mean(run_means)),
                    "se": float(np.std(run_means, ddof=1) / math.sqrt(len(run_means))),
                    "mean_ci95_width": float(np.mean(widths)),
                }
            fwres[cond] = {
                "n_runs": len(ts),
                "qubit_labels": labels,
                "contexts": ctxs,
                "run_false_alert": rate_with_ci(fa),
                "per_context": per_ctx,
            }
            if cond == "F2":
                fwres[cond]["within_6"] = rate_with_ci(det6)
                fwres[cond]["delay"] = delay_summary(delays)
        out["frameworks"][fw] = fwres
    q, c = out["frameworks"]["qiskit"], out["frameworks"]["cirq"]
    comp = {}
    for qc in sorted(set(q["F1"]["per_context"]) & set(c["F1"]["per_context"])):
        a, b = q["F1"]["per_context"][qc], c["F1"]["per_context"][qc]
        se = math.hypot(a["se"], b["se"])
        comp[qc] = {
            "diff": a["mean_rate"] - b["mean_rate"],
            "se": se,
            "z": (a["mean_rate"] - b["mean_rate"]) / se if se > 0 else 0.0,
            "width_ratio": a["mean_ci95_width"] / b["mean_ci95_width"],
        }
    out["comparison"] = {
        "per_context": comp,
        "max_abs_z": max(abs(v["z"]) for v in comp.values()) if comp else None,
        "labels_identical": q["F1"]["qubit_labels"]
        == c["F1"]["qubit_labels"]
        == q["F2"]["qubit_labels"]
        == c["F2"]["qubit_labels"]
        == [3, 7],
        "contexts_identical": q["F1"]["contexts"] == c["F1"]["contexts"] and q["F2"]["contexts"] == c["F2"]["contexts"],
        "f1_false_alert_diff": q["F1"]["run_false_alert"]["rate"] - c["F1"]["run_false_alert"]["rate"],
        "f2_within6_diff": q["F2"]["within_6"]["rate"] - c["F2"]["within_6"]["rate"],
    }
    return out


def exp_f_criteria(s):
    cm = s["comparison"]
    return [
        ("F.C1", "physical qubit labels {3,7} in both frameworks (1 = yes)", 1.0, float(cm["labels_identical"]), ">="),
        ("F.C2", "identical exact context sets (1 = yes)", 1.0, float(cm["contexts_identical"]), ">="),
        (
            "F.C3",
            "max |z| of per-context mean-rate differences, F1",
            3.0,
            cm["max_abs_z"] if cm["max_abs_z"] is not None else 99.0,
            "<=",
        ),
        ("F.C4", "|F1 false-alert rate difference|", 0.10, abs(cm["f1_false_alert_diff"]), "<="),
        ("F.C5", "|F2 within-6 detection difference|", 0.15, abs(cm["f2_within6_diff"]), "<="),
    ]


SUMMARY = {
    "V02_calibration": calibration_summary,
    "V02_A_false_alarm": exp_a_summary,
    "V02_B_gradual": exp_b_summary,
    "V02_C_abrupt": exp_c_summary,
    "V02_D_misspecification": exp_d_summary,
    "V02_E_workload_shift": exp_e_summary,
    "V02_F_cross_framework": exp_f_summary,
}
CRITERIA = {
    "V02_A_false_alarm": exp_a_criteria,
    "V02_B_gradual": exp_b_criteria,
    "V02_C_abrupt": exp_c_criteria,
    "V02_D_misspecification": exp_d_criteria,
    "V02_E_workload_shift": exp_e_criteria,
    "V02_F_cross_framework": exp_f_criteria,
}

__all__ = ["B_GRID", "CAL_TARGET", "CRITERIA", "C_GRID", "H_GRID", "K_GRID", "SUMMARY", "wilson"]
