# Methodological correction to the v0.1 E2 comparison

Run: `E2_matched_comparison-20261012T192652-b82408` (re-analysis of the
recorded raw data of `E2_sudden_degradation-20261012T180942-ea7ff1`; no new
simulation). Analysis code: `experiments/v02/e2_matched.py`. The original
run entry and `SUMMARY.md` are unchanged.

## What was wrong

`results/SUMMARY.md` reported the profiler's false-alarm run rate as 37% and
the Shewhart 3σ chart's as 7%, and concluded that the profiler "detected ×1.2
steps in 96% of runs vs 80%". The two methods were evaluated under different
rules (`docs/V01_AUDIT.md`, D1):

| Rule | Profiler (recorded) | Shewhart (recorded) | Matched (this run) |
|---|---|---|---|
| Qubits counted for false alarms | q0 pre-step **and** q1 anywhere | q0 only | both qubits, both methods |
| First batch at which an alarm can count | 5 | 10 | 10, both methods |
| Detection delay | first q0 alarm at/after step, regardless of earlier alarms | first exceedance after batch 10; a pre-step exceedance made the run "never detected" | first q0 alarm at/after step, both methods; also reported conditional on a clean pre-step window |
| Series tested per qubit per batch | 2 contexts | 1 pooled | unchanged (algorithmic) |
| Severity counted | WARNING/CRITICAL drift & threshold | single | WARNING/CRITICAL vs single; "any level, any kind" also reported |
| Shots used | 2 × 2000 per qubit per batch | identical | identical |

## Corrected numbers (200 runs: 50 seeds × {×1.5, ×1.2, ×1.1, none}; window = batches 10–47)

Run-level false-alarm rate = fraction of runs with any alarm on q1 in the
window or on q0 before the step (control: anywhere in the window). Qubit-level
rate = fraction of the 400 (run, qubit) stable segments with an alarm.

| Method | Run-level FA (Wilson 95%) | Control-run FA | Qubit-level FA | ×1.5 det. / median delay | ×1.2 det. / median delay | ×1.1 det. / median delay |
|---|---|---|---|---|---|---|
| Profiler v0.1, WARNING/CRITICAL | **0.305** (0.245–0.372) | 0.38 | 0.168 | 1.00 / 1 | 0.96 / 2 | 0.60 / 7 |
| Profiler v0.1, any level incl. INFO forecasts | 0.305 (0.245–0.372) | 0.38 | 0.168 | 1.00 / 1 | 0.96 / 2 | 0.60 / 7 |
| Shewhart 3σ, both qubits | **0.185** (0.137–0.245) | 0.26 | 0.100 | 1.00 / 0 | 0.88 / 2 | 0.44 / 9 |
| Shewhart 2.7σ (FA matched to profiler) | 0.315 (0.255–0.382) | 0.38 | 0.177 | 1.00 / 0 | 0.96 / 1 | 0.68 / 8.5 |
| Profiler v0.1 with bar raised to P ≥ 0.99 | 0.050 (0.027–0.090) | 0.06 | 0.025 | 1.00 / 1 | 0.56 / 5 | 0.18 / 8 |
| Shewhart 3.5σ (FA matched to the P ≥ 0.99 profiler) | 0.050 (0.027–0.090) | 0.08 | 0.028 | 1.00 / 0 | 0.70 / 5 | 0.28 / 9 |

Delays are in batches of 10 simulated minutes. The full k-sweep
(k = 1.5 … 4.5 in steps of 0.05) and all per-run first-alarm indices are in
the run's raw file.

## What changes

1. **The recorded 37% vs 7% contrast is not a like-for-like comparison.**
   Under matched rules the gap is 30.5% vs 18.5%, and the two 95% intervals
   nearly touch.
2. **At a matched run-level false-alarm rate the Shewhart chart detects at
   least as well as the v0.1 profiler**: ×1.2 steps 0.96 vs 0.96, ×1.1
   steps 0.68 vs 0.60, with a one-batch shorter median delay on ×1.2 steps
   and a 1.5-batch longer one on ×1.1 steps (50 runs per cell; none of these
   differences is statistically distinguishable). The claim of a profiler
   "detection-power advantage" in `SUMMARY.md` is withdrawn.
3. **Raising the profiler's per-check bar does not fix the comparison.** At
   P ≥ 0.99 the profiler reaches a 5% run-level false-alarm rate but detects
   ×1.2 steps in 56% of runs against 70% for the Shewhart chart at the same
   false-alarm rate. Because v0.1 tests every batch against a fixed
   posterior bar, lowering false alarms costs it more power than it costs
   the chart.
4. The preregistered E2.C3 bar (≤ 10% of runs with a false alarm) is failed
   by **both** methods under matched rules (0.305 and 0.185). Those two
   post-hoc criteria are recorded as informational, not preregistered.

## What this does not show

- It does not show that the profiler cannot beat a control chart: it shows
  that the v0.1 per-check design does not. Whether a sequentially calibrated
  design does is the hypothesis of the v0.2 study, tested on fresh seeds
  (`experiments/V02_PREREGISTRATION.md`, Experiments A–C).
- The profiler's bar could only be raised from recorded data, not lowered;
  the matched comparison was therefore made by moving the chart's k. A
  comparison in which both methods are swept over their full operating
  range needs a re-run and is part of Experiment C.
- Both methods were evaluated on readout-only noise with two deterministic
  circuits per batch. Nothing here concerns real hardware.
