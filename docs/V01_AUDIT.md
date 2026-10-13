# Audit of the v0.1 research baseline

Date: 2026-10-12. Auditor environment: Linux x86-64, Python 3.13.16, numpy
2.5.4, scipy 1.18.1, qiskit 2.5.2, qiskit-aer 0.17.2, cirq-core 1.7.0.

The v0.1 baseline is commit `0e8e41d`, tagged `v0.1-baseline`. Nothing in
that history is rewritten. Every statement below is either verified by a
command that can be re-run, or marked as an inference.

## 1. What was preserved

| Artifact | Location | Status |
|---|---|---|
| Source at the time of the runs | commits `4ba70c2` … `0e8e41d`, tag `v0.1-baseline` | unchanged |
| Preregistration | `experiments/PREREGISTRATION.md` | unchanged |
| Run log | `results/runs.jsonl` (3 entries) | unchanged; append-only from here on |
| Raw per-trial data | `results/raw/*.jsonl` (50 + 200 + 1714 lines) | unchanged |
| Original summary | `results/SUMMARY.md` | unchanged; corrections are published separately |

`results/MANIFEST.sha256` records the SHA-256 of every raw file and of every
`runs.jsonl` entry as of the baseline. `tools/verify_results.py` checks them
and fails if any recorded artifact changes.

## 2. Integrity verification of the v0.1 results

`python tools/verify_results.py` recomputes every summary statistic from the
raw trial logs with code written independently of `experiments/` and compares
it to the recorded value:

| Run | Raw trials | Summary values recomputed | Mismatches |
|---|---|---|---|
| E1_gradual_drift-20261012T180942-0c02af | 50 | 9 | 0 |
| E2_sudden_degradation-20261012T180942-ea7ff1 | 200 | 18 | 0 |
| E3_insufficient_evidence-20261012T180942-38b4b8 | 1714 | 79 | 0 |

All 14 pass/fail flags are consistent with their recorded observed values
and thresholds. The headline "8 of 14 criteria passed" is correct.

Code identity: `git diff 4ba70c2 0e8e41d -- src experiments tests
pyproject.toml` is empty, so the code that produced the results is the code
in the preregistration commit. All 26 unit tests pass in the audit
environment (`pytest`, 11.7 s).

**Verdict: the v0.1 results are internally consistent and reproducible from
the recorded raw data. They are not altered.**

## 3. Confirmed defects

Each item names the evidence. "Statistical" means the number is right but
the inference drawn from it is not; "methodological" means the comparison
was not like-for-like; "software" means a code defect.

### D1 (methodological) — E2 comparator was not evaluated under the profiler's rules

`experiments/exp2_sudden_degradation.py`, lines 41–47 and 23–28:

1. **Monitored qubits.** The profiler's false-alarm flag counts qubit 0
   before the step *and* qubit 1 anywhere. The Shewhart chart is evaluated
   on qubit 0 only (`shewhart_first(log)` with default `qubit=0`).
2. **Observation window.** Shewhart's first test is at batch 10 (after its
   10-batch reference window). The profiler's first possible alarm is at
   batch 5 (3 baseline + 3 recent batches); the earliest alarm in the raw
   data is at batch 5.
3. **Detection consumed by a prior false alarm.** For Shewhart, only the
   first exceedance is recorded; if it falls before the step the run counts
   as "never detected". The profiler's detection is read from post-step
   batches regardless of pre-step alarms.
4. **Partitioning of the same shots.** Both methods see the same 2 × 2000
   deterministic shots per qubit per batch. The profiler tests two context
   series per qubit (`ideal=0`, `ideal=1`), the Shewhart chart one pooled
   series. The profiler therefore runs twice as many tests per qubit per
   batch on the same data.
5. **Severity.** The profiler's false alarms count WARNING/CRITICAL drift
   and threshold alerts and exclude INFO forecasts; Shewhart has one
   severity.

Recomputed from the raw E2 data with identical qubit sets (both qubits),
identical window (batches ≥ 10), and detection measured as the first alarm
at or after the step for both methods:

| Method | Run-level false-alarm rate (Wilson 95%) | ×1.2 detected | ×1.1 detected | ×1.1 median delay |
|---|---|---|---|---|
| Profiler WARNING/CRITICAL (recorded definition) | 0.37 (0.31–0.44) | 0.96 | 0.60 | 7 |
| Profiler WARNING/CRITICAL, window ≥ 10 | 0.305 (0.245–0.372) | 0.96 | 0.60 | 7 |
| Shewhart 3σ, qubit 0 only (recorded) | 0.07 (0.04–0.11) | 0.80 | 0.40 | 9 |
| Shewhart 3σ, both qubits, window ≥ 10 | 0.185 (0.137–0.245) | 0.88 | 0.44 | 9 |
| Shewhart 2.7σ, both qubits (run FA matched to 0.305) | 0.315 | 0.96 | 0.68 | 8.5 |

The recorded "37% vs 7%" comparison overstated the Shewhart advantage in
false alarms by about 2.6× and understated its detection rate. At matched
run-level false-alarm rate the Shewhart chart detects at least as often as
the v0.1 profiler. The claim in `results/SUMMARY.md` that the profiler had a
"detection-power advantage" is **not supported** once the evaluation rules
are matched. The full correction, with its own run entry, is in
`results/E2_CORRECTION.md`.

### D2 (statistical) — per-check posterior bars with no sequential control

`src/qnp/drift.py` applies P ≥ 0.95 (drift), P ≥ 0.95 (threshold) and
P ≥ 0.9 (trend) at every check. A monitoring run performs 48 checks on 2
contexts × 2 qubits. The run-level false-alert probability is the
probability that *any* of ~190 dependent tests crosses its bar. Observed:
E1.C3 = 0.62, E2.C3 = 0.37; 45 of 200 stable qubit-1 series produced a false
WARNING; first false alarms are spread over batches 8–43 (10th–90th
percentile), i.e. they keep accruing with monitoring length. No run-level
error budget existed.

### D3 (statistical) — forecast alerts were the main false-alert source and their intervals are not predictive

In the E1 control (qubit at a constant 4.5%), the 50 runs produced 270
INFO forecast alert instances, 2 drift WARNINGs and 1 threshold CRITICAL;
28 of the 31 alerting runs had forecasts only. The trend gate is
P(slope > 0) ≥ 0.9 from a weighted linear fit, re-tested at every batch. The
reported "80% interval" for the crossing time is drawn from the posterior of
the fitted (intercept, slope) only (`_forecast`, lines 201–211): it contains
no future process variation and is not a predictive interval.

### D4 (software/provenance) — environment recorded at completion, not at launch

`experiments/common.py::record` calls `environment()` when a run *finishes*.
All three v0.1 runs started at 18:09:42 UTC, 11 s after `4ba70c2` was
committed (18:09:31 UTC), yet they recorded `git_commit` = `e39d39a`,
`7a39f5b`, `700112a` (the HEADs at their respective finish times). The code
that ran was `4ba70c2`. Harmless here (the diff is empty, §2), but the
mechanism cannot prove which code ran. v0.2 records the commit and a hash
of the source tree at launch and again at completion.

### D5 (statistical) — decay fits have no misfit detection and fixed SPAM ranges

Known and preregistered (E3.C6, E3.C7 both failed: 72% false confidence
under fluctuating T1, 0% abstention on bi-exponential decay). In addition
the amplitude/offset prior ranges are hard-coded (T1: A ∈ [0.5, 1],
B ∈ [0, 0.2]); data outside them (readout error > 20%, inverted
population) would be fitted against a clipped prior with no warning. E3.C5
missed narrowly (coverage 0.88 at a 0.2·T1 delay span); the cause is not
established (candidates: the 41 × 41 A/B grid, equal-tailed intervals on a
skewed posterior). Addressed in Phase 4.

### D6 (software, latent) — `_kind()` drops a reported interval when `ci_low == 0.0`

`drift.py` line 77: `all(e.ci_low and e.ci_high and e.ci_low > 0 …)`. A
credible interval with lower bound exactly 0.0 is falsy, so the series is
silently analysed as a *point* series without uncertainty. Not triggered
in v0.1 (binomial series take the first branch). Fixed in v0.2 with explicit
`is not None` checks and a validation error for non-positive bounds on
log-scale metrics.

### D7 (methodological) — the E1 "naive" comparator is not a meaningful baseline

The per-batch point estimate > 5% rule, at a true rate of 4.5% with 4000
shots, exceeds 5% with probability ≈ 0.064 per batch and ≈ 0.96 over 48
batches (observed 0.92). The recorded +170 min lead is measured against a
comparator with a 92% false-alarm rate. Lead time is only meaningful at a
matched false-alarm rate; v0.2 Experiment B reports it that way.

### D8 (software, minor) — Monte Carlo decision noise

`prob_ratio_exceeds` uses 40 000 draws with a fixed seed; the Monte Carlo
standard error at P ≈ 0.95 is ≈ 0.001, so decisions within ±0.002 of the bar
are set by the seed rather than the data. v0.2 uses closed-form or
quadrature e-values.

### D9 (software, performance) — O(N²) store access per session

`Profiler.check()` reloads every estimate from SQLite at every check. A
48-batch run takes 6.4 s, of which Aer simulation is 1.1 s. Cost only.

## 4. What was not a defect

- The three runs started simultaneously (identical `started` timestamps);
  they were launched in parallel. Their `run_id`s carry the launch time.
- `git_dirty` was false for `src` and `experiments` in every run.
- The criteria thresholds in `runs.jsonl` match the preregistration.
- Flip-rate credible-interval coverage (E3.C2, E3.C3) and the abstention
  logic (E3.C1, E3.C4) are sound and are kept unchanged.

## 5. Consequences for v0.2

Defects D1–D3 and D7 mean the v0.1 comparisons cannot support the claim
that the profiler detects degradation earlier than a conventional method at
a defensible false-alert rate. That claim becomes the hypothesis of the v0.2
study (`experiments/V02_PREREGISTRATION.md`), to be tested on seeds disjoint
from everything used during development and calibration.
