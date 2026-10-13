"""Experiment 2 -- sudden degradation. See PREREGISTRATION.md (E2)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone

import numpy as np
from common import Criterion, first_index, print_entry, record, stream

from qnp import LegacyDriftConfig  # v0.1 protocol: frozen v0.1 decision rules

N_SEEDS = int(sys.argv[1]) if len(sys.argv) > 1 else 50
N_BATCHES, STEP_AT, SHOTS, BASE = 48, 24, 2000, 0.02
RATIOS = {"x1.5": 1.5, "x1.2": 1.2, "x1.1": 1.1, "none": 1.0}
Q1 = np.full(N_BATCHES, BASE)
ALARM = {"WARNING", "CRITICAL"}


def alarm(qubit):
    return lambda a: a["qubit"] == qubit and a["level"] in ALARM and a["kind"] in ("drift", "threshold")


def shewhart_first(log, qubit=0, ref=10):
    """Conventional 3-sigma control chart: baseline from the first ``ref``
    batches, alarm when a batch exceeds mean + 3 binomial sigma."""
    base = np.mean([b["naive"][qubit] for b in log[:ref]])
    sigma = np.sqrt(base * (1 - base) / (2 * SHOTS))  # 2 deterministic circuits / batch
    return next((b["i"] for b in log[ref:] if b["naive"][qubit] > base + 3 * sigma), None)


def main():
    started = datetime.now(timezone.utc)
    trials = []
    delays = {k: [] for k in RATIOS}
    shew_delays = {k: [] for k in RATIOS}
    false_runs, shew_false_runs = [], []
    for name, ratio in RATIOS.items():
        sched = np.where(np.arange(N_BATCHES) < STEP_AT, BASE, BASE * ratio)
        for seed in range(N_SEEDS):
            log = stream(sched, Q1, seed + 1000 * list(RATIOS).index(name), SHOTS, config=LegacyDriftConfig())
            pre = [b for b in log if b["i"] < STEP_AT] if ratio != 1.0 else log
            false = any(alarm(0)(a) for b in pre for a in b["alerts"]) or any(
                alarm(1)(a) for b in log for a in b["alerts"]
            )
            post = [b for b in log if b["i"] >= STEP_AT]
            i_det = first_index(post, alarm(0)) if ratio != 1.0 else None
            i_shew = shewhart_first(log)
            shew_false = i_shew is not None and (ratio == 1.0 or i_shew < STEP_AT)
            false_runs.append(false)
            shew_false_runs.append(shew_false)
            if ratio != 1.0:
                delays[name].append(None if i_det is None else i_det - STEP_AT)
                shew_delays[name].append(None if (i_shew is None or i_shew < STEP_AT) else i_shew - STEP_AT)
            trials.append(
                {
                    "condition": name,
                    "seed": seed,
                    "log": log,
                    "i_detect": i_det,
                    "i_shewhart": i_shew,
                    "false_alarm": false,
                }
            )
            print(
                f"{name} seed {seed}: detect delay={None if i_det is None else i_det - STEP_AT} "
                f"shewhart={i_shew} false={false}",
                flush=True,
            )

    def within(xs, k):
        return float(np.mean([x is not None and x <= k for x in xs])) if xs else float("nan")

    def median_delay(xs):
        f = [x for x in xs if x is not None]
        return float(np.median(f)) if f else None

    summary = {"n_seeds_per_condition": N_SEEDS}
    for name in ("x1.5", "x1.2", "x1.1"):
        summary[f"{name}_detect_rate_any"] = within(delays[name], N_BATCHES)
        summary[f"{name}_median_delay_batches"] = median_delay(delays[name])
        summary[f"{name}_shewhart_detect_rate_any"] = within(shew_delays[name], N_BATCHES)
        summary[f"{name}_shewhart_median_delay_batches"] = median_delay(shew_delays[name])
    summary["x1.5_within_6"] = within(delays["x1.5"], 6)
    summary["x1.2_within_24"] = within(delays["x1.2"], 24)
    # Spec claim: "detects 10% degradation within 20 circuits" = 5 batches of 4 circuits.
    summary["x1.1_within_5"] = within(delays["x1.1"], 5)
    summary["false_alarm_run_rate"] = float(np.mean(false_runs))
    summary["shewhart_false_alarm_run_rate"] = float(np.mean(shew_false_runs))

    criteria = [
        Criterion("E2.C1", "x1.5 step detected within 6 batches", 0.90, summary["x1.5_within_6"], ">="),
        Criterion("E2.C2", "x1.2 step detected within 24 batches", 0.50, summary["x1.2_within_24"], ">="),
        Criterion("E2.C3", "runs with any false WARNING/CRITICAL", 0.10, summary["false_alarm_run_rate"], "<="),
        Criterion("E2.C4", "spec claim: x1.1 detected within 20 circuits", 0.80, summary["x1.1_within_5"], ">="),
    ]
    entry = record(
        "E2_sudden_degradation",
        {
            "n_batches": N_BATCHES,
            "step_at": STEP_AT,
            "shots": SHOTS,
            "base": BASE,
            "ratios": RATIOS,
            "circuits_per_batch": 4,
            "deterministic_per_batch": 2,
        },
        summary,
        criteria,
        trials,
        started,
    )
    print_entry(entry)


if __name__ == "__main__":
    main()
