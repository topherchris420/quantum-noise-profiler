"""E2 methodological correction: matched re-evaluation of the recorded v0.1
E2 raw data (profiler vs Shewhart). No new simulation; see v02/e2_matched.py.

    python experiments/exp2_matched_comparison.py

Appends a run ``E2_matched_comparison`` to results/runs.jsonl whose raw file
holds, per run and method, the first-alarm indices and derived flags, so the
summary can be recomputed by tools/verify_results.py.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from common import ROOT, Criterion, environment, print_entry, record
from v02 import e2_matched

SOURCE_RUN = "E2_sudden_degradation-20261012T180942-ea7ff1"


def load_source():
    entries = [json.loads(line) for line in (ROOT / "results" / "runs.jsonl").read_text().splitlines() if line.strip()]
    (entry,) = [e for e in entries if e["run_id"] == SOURCE_RUN]
    trials = [json.loads(line) for line in Path(ROOT / entry["raw"]).read_text().splitlines() if line.strip()]
    return entry, trials


def main():
    started = datetime.now(timezone.utc)
    env0 = environment()
    source, trials = load_source()
    config = {
        "source_run_id": SOURCE_RUN,
        "n_batches": source["config"]["n_batches"],
        "step_at": source["config"]["step_at"],
        "shots": source["config"]["shots"],
        "deterministic_per_batch": source["config"]["deterministic_per_batch"],
        "ratios": source["config"]["ratios"],
        "window_start": 10,
        "shewhart_ref": 10,
        "monitored_qubits": [0, 1],
        "k_grid": e2_matched.K_GRID,
        "profiler_variants": {k: {**v, "levels": sorted(v["levels"])} for k, v in e2_matched.PROFILER_VARIANTS.items()},
        "recorded_profiler_false_alarm_run_rate": source["summary"]["false_alarm_run_rate"],
        "recorded_shewhart_false_alarm_run_rate": source["summary"]["shewhart_false_alarm_run_rate"],
    }
    summary, rows_by_method = e2_matched.analyze(trials, config)
    raw = [{"method": m, **r} for m, rows in rows_by_method.items() for r in rows]
    # Post-hoc re-evaluation of the preregistered E2.C3 bar under matched rules.
    # These are informational: E2.C3 was preregistered for the profiler only.
    criteria = [
        Criterion(
            "E2.C3-matched/profiler",
            "profiler WARNING/CRITICAL: runs with any false alarm, matched rules",
            0.10,
            summary["profiler_v01_warn"]["run_false_alarm"]["rate"],
            "<=",
        ),
        Criterion(
            "E2.C3-matched/shewhart3",
            "Shewhart 3-sigma, both qubits: runs with any false alarm, matched rules",
            0.10,
            summary["shewhart_k3.00"]["run_false_alarm"]["rate"],
            "<=",
        ),
    ]
    notes = (
        "Re-analysis of recorded raw data only (no new simulation). Corrects the evaluation asymmetries "
        "in docs/V01_AUDIT.md D1. Criteria are post-hoc applications of the E2.C3 bar to both methods "
        "under matched rules and were not preregistered."
    )
    entry = record(
        "E2_matched_comparison",
        config,
        summary,
        criteria,
        raw,
        started,
        notes,
        env_at_start=env0,
        protocol="docs/V01_AUDIT.md D1; results/E2_CORRECTION.md",
    )
    print_entry(entry)
    h = summary["headline"]
    rec_p, rec_s = h["recorded_profiler_false_alarm_run_rate"], h["recorded_shewhart_false_alarm_run_rate"]
    print(f"\nrecorded: profiler {rec_p:.3f} vs shewhart {rec_s:.3f}")
    print(
        f"matched : profiler {h['matched_profiler_warn_run_false_alarm']:.3f} vs "
        f"shewhart-3s {h['matched_shewhart_3sigma_run_false_alarm']:.3f}; "
        f"Shewhart k at profiler FA = {h['shewhart_k_at_profiler_false_alarm']}"
    )
    for name, m in summary["matched_false_alarm"].items():
        cells = " ".join(
            f"{c}: P{m[c]['profiler_detect_rate']:.2f}/S{m[c]['shewhart_detect_rate']:.2f} "
            f"med P{m[c]['profiler_median_delay']}/S{m[c]['shewhart_median_delay']}"
            for c in ("x1.5", "x1.2", "x1.1")
        )
        print(
            f"  {name}: FA {m['profiler_run_false_alarm']:.3f} ~ shewhart k={m['matched_k']} "
            f"FA {m['shewhart_run_false_alarm']:.3f} | {cells}"
        )


if __name__ == "__main__":
    main()
