"""Experiment 1 -- gradual drift. See PREREGISTRATION.md (E1)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone

import numpy as np
from common import BATCH_INTERVAL, Criterion, first_index, print_entry, record, stream

N_SEEDS = int(sys.argv[1]) if len(sys.argv) > 1 else 50
N_BATCHES, SHOTS, THR = 48, 2000, 0.05
RAMP = np.linspace(0.02, 0.06, N_BATCHES)  # q0 readout error, crosses 5% at i = 35.25
I_CROSS = (THR - 0.02) / (0.04 / (N_BATCHES - 1))
CONTROL = np.full(N_BATCHES, 0.045)  # stable just below threshold
Q1 = np.full(N_BATCHES, 0.02)
MIN = BATCH_INTERVAL.total_seconds() / 60


def q0(kinds, levels=None):
    return lambda a: a["qubit"] == 0 and a["kind"] in kinds and (levels is None or a["level"] in levels)


def main():
    started = datetime.now(timezone.utc)
    trials, prof_lead, naive_lead, early = [], [], [], []
    ctrl_prof_any, ctrl_prof_warn, ctrl_naive = [], [], []
    for seed in range(N_SEEDS):
        ramp = stream(RAMP, Q1, seed, SHOTS)
        ctrl = stream(CONTROL, Q1, 100_000 + seed, SHOTS)
        i_prof = first_index(ramp, q0({"forecast", "threshold"}))
        i_naive = next((b["i"] for b in ramp if b["naive"][0] > THR), None)
        lead = lambda i: None if i is None else (I_CROSS - i) * MIN
        prof_lead.append(lead(i_prof))
        naive_lead.append(lead(i_naive))
        early.append(i_prof is not None and i_prof < I_CROSS)
        ctrl_prof_any.append(first_index(ctrl, q0({"forecast", "threshold", "drift"})) is not None)
        ctrl_prof_warn.append(
            first_index(ctrl, q0({"forecast", "threshold", "drift"}, {"WARNING", "CRITICAL"})) is not None
        )
        ctrl_naive.append(any(b["naive"][0] > THR for b in ctrl))
        trials.append({"seed": seed, "ramp": ramp, "control": ctrl, "i_profiler": i_prof, "i_naive": i_naive})
        print(
            f"seed {seed}: profiler i={i_prof} naive i={i_naive} "
            f"control any={ctrl_prof_any[-1]} naive_ctrl={ctrl_naive[-1]}",
            flush=True,
        )

    finite = lambda xs: [x for x in xs if x is not None]
    med = lambda xs: float(np.median(finite(xs))) if finite(xs) else float("nan")
    summary = {
        "n_seeds": N_SEEDS,
        "true_crossing_minutes": I_CROSS * MIN,
        "profiler_early_fraction": float(np.mean(early)),
        "profiler_median_lead_min": med(prof_lead),
        "naive_median_lead_min": med(naive_lead),
        "profiler_never_alerted": sum(x is None for x in prof_lead),
        "control_profiler_any_alert_rate": float(np.mean(ctrl_prof_any)),
        "control_profiler_warning_rate": float(np.mean(ctrl_prof_warn)),
        "control_naive_false_alarm_rate": float(np.mean(ctrl_naive)),
    }
    criteria = [
        Criterion("E1.C1", "profiler alerts before true crossing", 0.80, summary["profiler_early_fraction"], ">="),
        Criterion(
            "E1.C2",
            "median lead over naive (min)",
            30.0,
            summary["profiler_median_lead_min"] - summary["naive_median_lead_min"],
            ">=",
        ),
        Criterion(
            "E1.C3",
            "control: runs with any profiler alert on q0",
            0.10,
            summary["control_profiler_any_alert_rate"],
            "<=",
        ),
    ]
    entry = record(
        "E1_gradual_drift",
        {
            "n_batches": N_BATCHES,
            "shots": SHOTS,
            "threshold": THR,
            "ramp": [0.02, 0.06],
            "control_level": 0.045,
            "q1_level": 0.02,
            "batch_minutes": MIN,
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
