"""Matched re-evaluation of the v0.1 E2 comparison (profiler vs Shewhart).

This module re-analyses the *recorded* raw trials of
``E2_sudden_degradation-20261012T180942-ea7ff1`` without re-running any
simulation. It fixes the five evaluation asymmetries documented in
``docs/V01_AUDIT.md`` (D1):

* identical monitored qubit set: both qubits, for both methods;
* identical observation window: alarms before batch ``window_start`` are
  ignored for both methods (the Shewhart chart needs its reference window;
  the profiler is given the same handicap);
* identical false-alert definition: any alarm on the stable qubit (q1) in the
  window, or on q0 before the step (step runs) / anywhere in the window
  (control runs);
* detection delay for both methods = first alarm on q0 at or after the step,
  whether or not a false alarm occurred earlier (also reported conditional on
  a clean pre-step window);
* matched severity: the profiler's WARNING/CRITICAL drift and threshold
  alerts are compared with the single-severity Shewhart alarm; the
  "any level, any kind" profiler variant (INFO forecasts included) is reported
  as well.

Both methods consume the same shots: 2 deterministic circuits x 2000 shots
per qubit per batch. The profiler splits them into two context series per
qubit; the Shewhart chart pools them. That difference is algorithmic and is
left as is.

The profiler's per-check bar cannot be *lowered* from recorded data (alerts
below P = 0.95 were never logged), only raised using the logged posterior
probabilities. The Shewhart multiplier k can be varied freely because the
per-batch rates were logged. Matching is therefore done by sweeping k to the
profiler's run-level false-alarm rate, never the other way round.
"""

from __future__ import annotations

import numpy as np

from .stats_utils import delay_summary, rate_with_ci, wilson

ALARM_LEVELS = {"WARNING", "CRITICAL"}
STEP_CONDITIONS = ("x1.5", "x1.2", "x1.1")
K_GRID = [round(x, 2) for x in np.arange(1.5, 4.51, 0.05)]
PROFILER_VARIANTS = {
    "profiler_v01_warn": {"kinds": ("drift", "threshold"), "levels": ALARM_LEVELS, "pmin": None},
    "profiler_v01_any": {"kinds": ("drift", "threshold", "forecast"), "levels": {"INFO", "WARNING", "CRITICAL"}, "pmin": None},
    "profiler_v01_warn_p0.99": {"kinds": ("drift", "threshold"), "levels": ALARM_LEVELS, "pmin": 0.99},
    "profiler_v01_warn_p0.999": {"kinds": ("drift", "threshold"), "levels": ALARM_LEVELS, "pmin": 0.999},
}


def profiler_first(log, qubit, start, kinds, levels, pmin=None):
    for b in log:
        if b["i"] < start:
            continue
        for a in b["alerts"]:
            if a["qubit"] == qubit and a["kind"] in kinds and a["level"] in levels:
                if pmin is None or a.get("probability", 1.0) >= pmin:
                    return b["i"]
    return None


def shewhart_first(log, qubit, start, k, ref, shots_per_batch):
    base = float(np.mean([b["naive"][qubit] for b in log[:ref]]))
    sigma = float(np.sqrt(base * (1 - base) / shots_per_batch))
    limit = base + k * sigma
    return next((b["i"] for b in log if b["i"] >= max(start, ref) and b["naive"][qubit] > limit), None)


def per_run_events(trial, detector, start, step, n_batches, ratio):
    """First-alarm indices for one run and both qubits, plus derived flags."""
    log = trial["log"]
    i0 = detector(log, 0, start)
    i1 = detector(log, 1, start)
    stable_end_q0 = step if ratio != 1.0 else n_batches
    false_q0 = i0 is not None and i0 < stable_end_q0
    false_q1 = i1 is not None
    i_det = detector(log, 0, step) if ratio != 1.0 else None
    return {
        "first_alarm_q0": i0, "first_alarm_q1": i1,
        "false_q0": false_q0, "false_q1": false_q1, "false_run": false_q0 or false_q1,
        "delay": None if i_det is None else i_det - step,
    }


def evaluate_method(trials, detector, config):
    start, step, nb = config["window_start"], config["step_at"], config["n_batches"]
    ratios = config["ratios"]
    rows = []
    for t in trials:
        ev = per_run_events(t, detector, start, step, nb, ratios[t["condition"]])
        rows.append({"condition": t["condition"], "seed": t["seed"], **ev})
    return rows


def summarize_rows(rows, config):
    ratios = config["ratios"]
    s = {
        "run_false_alarm": rate_with_ci([r["false_run"] for r in rows]),
        "control_run_false_alarm": rate_with_ci([r["false_run"] for r in rows if ratios[r["condition"]] == 1.0]),
        "qubit_false_alarm": rate_with_ci([r["false_q0"] for r in rows] + [r["false_q1"] for r in rows]),
        "q0_prestep_false_alarm": rate_with_ci([r["false_q0"] for r in rows]),
        "q1_false_alarm": rate_with_ci([r["false_q1"] for r in rows]),
    }
    for c in STEP_CONDITIONS:
        rs = [r for r in rows if r["condition"] == c]
        d = delay_summary([r["delay"] for r in rs])
        d["within_5"] = float(np.mean([r["delay"] is not None and r["delay"] <= 5 for r in rs]))
        d["within_6"] = float(np.mean([r["delay"] is not None and r["delay"] <= 6 for r in rs]))
        d["within_24"] = float(np.mean([r["delay"] is not None and r["delay"] <= 24 for r in rs]))
        clean = [r for r in rs if not r["false_q0"]]
        d["clean_prestep_runs"] = len(clean)
        d["detect_rate_given_clean_prestep"] = float(np.mean([r["delay"] is not None for r in clean])) if clean else None
        s[c] = d
    return s


def analyze(trials, config):
    """Full matched analysis. Returns (summary, per_run_rows_by_method)."""
    shots_per_batch = config["deterministic_per_batch"] * config["shots"]
    methods = {}
    for name, v in PROFILER_VARIANTS.items():
        methods[name] = lambda log, q, s, v=v: profiler_first(log, q, s, v["kinds"], v["levels"], v["pmin"])
    for k in K_GRID:
        methods[f"shewhart_k{k:.2f}"] = lambda log, q, s, k=k: shewhart_first(log, q, s, k, config["shewhart_ref"], shots_per_batch)
    rows_by_method = {name: evaluate_method(trials, det, config) for name, det in methods.items()}
    summary = {name: summarize_rows(rows, config) for name, rows in rows_by_method.items()}

    # Matched-false-alarm comparison: for each profiler variant, the Shewhart k
    # whose run-level false-alarm rate is closest (ties -> larger k, i.e. the
    # more conservative chart), and the detection statistics at that k.
    matched = {}
    ks = sorted(K_GRID)
    fa_k = np.array([summary[f"shewhart_k{k:.2f}"]["run_false_alarm"]["rate"] for k in ks])
    for name in PROFILER_VARIANTS:
        target = summary[name]["run_false_alarm"]["rate"]
        diff = np.abs(fa_k - target)
        best = max(i for i in range(len(ks)) if diff[i] == diff.min())
        k = ks[best]
        matched[name] = {
            "profiler_run_false_alarm": target,
            "matched_k": k,
            "shewhart_run_false_alarm": float(fa_k[best]),
            **{f"{c}": {"profiler_detect_rate": summary[name][c]["detect_rate"],
                       "shewhart_detect_rate": summary[f"shewhart_k{k:.2f}"][c]["detect_rate"],
                       "profiler_median_delay": summary[name][c]["median"],
                       "shewhart_median_delay": summary[f"shewhart_k{k:.2f}"][c]["median"]}
               for c in STEP_CONDITIONS},
        }
    summary["matched_false_alarm"] = matched
    # Headline numbers used in the correction note.
    summary["headline"] = {
        "recorded_profiler_false_alarm_run_rate": config.get("recorded_profiler_false_alarm_run_rate"),
        "recorded_shewhart_false_alarm_run_rate": config.get("recorded_shewhart_false_alarm_run_rate"),
        "matched_profiler_warn_run_false_alarm": summary["profiler_v01_warn"]["run_false_alarm"]["rate"],
        "matched_shewhart_3sigma_run_false_alarm": summary["shewhart_k3.00"]["run_false_alarm"]["rate"],
        "shewhart_k_at_profiler_false_alarm": matched["profiler_v01_warn"]["matched_k"],
    }
    return summary, rows_by_method


def recompute_summary(trials, config):
    """Verifier hook: recompute the summary from the recorded per-run rows.

    The raw file of this experiment stores, per run and method, the
    first-alarm indices and derived flags; the summary must follow from them.
    """
    by_method: dict[str, list] = {}
    for t in trials:
        by_method.setdefault(t["method"], []).append(t)
    summary = {name: summarize_rows(rows, config) for name, rows in by_method.items()}
    ks = sorted(K_GRID)
    fa_k = np.array([summary[f"shewhart_k{k:.2f}"]["run_false_alarm"]["rate"] for k in ks])
    matched = {}
    for name in PROFILER_VARIANTS:
        target = summary[name]["run_false_alarm"]["rate"]
        diff = np.abs(fa_k - target)
        best = max(i for i in range(len(ks)) if diff[i] == diff.min())
        k = ks[best]
        matched[name] = {
            "profiler_run_false_alarm": target, "matched_k": k, "shewhart_run_false_alarm": float(fa_k[best]),
            **{c: {"profiler_detect_rate": summary[name][c]["detect_rate"],
                   "shewhart_detect_rate": summary[f"shewhart_k{k:.2f}"][c]["detect_rate"],
                   "profiler_median_delay": summary[name][c]["median"],
                   "shewhart_median_delay": summary[f"shewhart_k{k:.2f}"][c]["median"]}
               for c in STEP_CONDITIONS},
        }
    summary["matched_false_alarm"] = matched
    summary["headline"] = {
        "recorded_profiler_false_alarm_run_rate": config.get("recorded_profiler_false_alarm_run_rate"),
        "recorded_shewhart_false_alarm_run_rate": config.get("recorded_shewhart_false_alarm_run_rate"),
        "matched_profiler_warn_run_false_alarm": summary["profiler_v01_warn"]["run_false_alarm"]["rate"],
        "matched_shewhart_3sigma_run_false_alarm": summary["shewhart_k3.00"]["run_false_alarm"]["rate"],
        "shewhart_k_at_profiler_false_alarm": matched["profiler_v01_warn"]["matched_k"],
    }
    return summary


__all__ = ["analyze", "recompute_summary", "wilson", "K_GRID", "PROFILER_VARIANTS"]
