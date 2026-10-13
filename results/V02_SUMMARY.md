# Results summary: v0.2 preregistered simulation study

**53 of 62 preregistered checks passed** (27 of 31 criterion IDs passed in
full). All numbers come from the run entries listed at the end; every value
is recomputed from raw data by `tools/verify_results.py`, and all seven
runs executed the same source tree (`source_tree_sha256 84960cd8…`, the tree
of commit `0ea0224`). Protocol: `experiments/V02_PREREGISTRATION.md`,
committed before any calibration or confirmatory run. Deviations:
`results/V02_DEVIATIONS.md` (two pre-data clarifications, one interrupted
run that was restarted unchanged). Full tables: `results/V02_TABLES.md`.
Exploratory, not preregistered, breakdowns: `results/V02_EXPLORATORY.md`.

**Scope.** Everything here is simulation (Qiskit Aer, Cirq, numpy). Nothing
here is evidence about real quantum hardware.

## The eight questions

### 1. Did v0.2 reduce the full-run false-alert probability?

Yes, in simulation. Fraction of stable sessions with at least one false
alert (any channel, any level, both qubits):

| Condition | v0.1 | v0.2 anytime-valid | v0.2 calibrated | Shewhart (cal.) | CUSUM (cal.) |
|---|---|---|---|---|---|
| A1: both 0.5%, 8 h | 0.86 | 0.003 | 0.045 | 0.072 | 0.068 |
| A2: both 2%, 8 h | 0.43 | 0.005 | 0.018 | 0.028 | 0.052 |
| A3: q0 4.5%, 8 h | 0.70 | 0.010 | 0.068 | 0.030 | 0.087 |
| A4: q0 4.9%, 8 h | 0.88 | 0.003 | 0.028 | 0.030 | 0.090 |
| A5: both 2%, 24 h | 0.77 | 0.005 | 0.070 | 0.135 | 0.215 |

400 runs per cell for A1–A4 (200 for v0.1), 200 for A5 (100 for v0.1).
The anytime-valid configuration stays at or below 1% for 24 h, as its
guarantee predicts. The calibrated configuration stays at or below 7%. The
control charts were calibrated on 8 h sessions and exceed 10% at 24 h; the
v0.2 calibrated configuration also grows with session length (2%→7% at the
2% condition), because the calibration offset gives up the anytime
guarantee. All of A.C1–A.C4 pass.

**Caveat (exploratory condition A6).** When both qubits fluctuate
stationarily by about 10% (log-OU, σ = 0.1), v0.2 alerts in 52% of runs
(anytime-valid) and 73% (calibrated); the charts in 43–59%. A real device
that fluctuates at the scale of the 10% effect gate will produce alerts.
Whether those count as false is an operational definition the study did not
settle.

### 2. Did detection sensitivity improve or decline at matched false-alert rates?

All "calibrated" methods were tuned on separate seeds to the same rule
(max false-alert rate ≤ 0.08 over four stable conditions).

| | v0.1 re-thresholded | v0.2 calibrated | Shewhart | CUSUM |
|---|---|---|---|---|
| Ramp 2→6% (B1): median warning lead | 203 min | **253 min** | 223 min | 213 min |
| Ramp 2→5.5% (B2): median warning lead | 233 min | **293 min** | 263 min | 253 min |
| ×1.5 step: detected within 6 batches | 1.00 | 1.00 | 1.00 | 1.00 |
| ×1.2 step: within 6 batches | 0.20 | **0.73** | 0.35 | 0.48 |
| ×1.2 step: within 24 batches | 0.30 | 0.985 | 0.685 | **0.995** |
| ×1.1 step: within 24 batches | 0.04 | 0.515 | 0.155 | **0.635** |
| Run-level false alerts, Experiment C pooled | 0.006 | 0.034 | 0.028 | 0.043 |

- **Against v0.1 at matched false-alert rate:** sensitivity improved
  substantially (B.C3, C.C5 pass). v0.1 *as configured* detected sooner, but
  only by raising false alerts in 25–39% of runs.
- **Against calibrated control charts:** v0.2 gives the longest lead on
  gradual drift and the fastest detection of ×1.2 steps, and is
  non-inferior on ×1.2 within 24 batches (B.C2, C.C4 pass). **CUSUM is better
  for the smallest step** (×1.1 within 24 batches: 0.635 vs 0.515).
- **The anytime-valid configuration pays for its guarantee in power:** ×1.1
  within 24 batches 0.265; ×1.2 within 6 batches 0.46.
- **The original spec claim fails for every method** (C.C3: ×1.1 within 5
  batches, 0.09 for v0.2 calibrated, 0.08 for CUSUM). With 2 deterministic
  circuits × 2000 shots per batch, a 10% change cannot be resolved in 5
  batches at this false-alert rate.

### 3. Does the revised T1 estimator reliably identify the tested misspecifications?

For most tested forms, yes; for two, no.

| Scenario (200 fits each) | not reported (rejected) | false confidence | v0.1 false confidence |
|---|---|---|---|
| D6 T1 fluctuating per delay, σ = 0.3 | 1.00 | 0.000 | 0.72 |
| D7 same, σ = 0.1 (mild) | 0.975 | 0.015 | – |
| D8 bi-exponential 70/30 | 1.00 | – | (0% abstention) |
| D9 bi-exponential 90/10 (mild) | **0.005** | (99.5% reported) | – |
| D10 heavy-tailed disturbance | 0.965 | 0.005 | – |
| D11 time-correlated readout drift along the sweep | **0.26** | **0.285** | – |
| D12 T1 drifting 120→80 µs during the sweep | 0.945 | 0.010 | – |

- **Failure, D.C6/D11.** A slow, correlated offset drift along the sweep
  bends the curve smoothly enough that the deviance, posterior-predictive
  and runs tests (15 points, α = 0.01 each) accept it in 74% of fits, and
  28.5% of all fits report a confidently wrong T1.
- **Not detected, D9 (no criterion attached).** A mild second component
  (10% of amplitude at half the decay time) is statistically
  indistinguishable from a single exponential at this design. The reported
  value (median 92 µs) is a weighted effective decay time, not "the" T1.
- **Insufficient evidence versus misspecification is distinguished
  perfectly in the tested cases.** Short delay ranges (D4, D5) are labelled
  `INSUFFICIENT_EVIDENCE` in 400/400 fits. Misfit models (D6, D8) are labelled
  `MODEL_MISSPECIFICATION` in 400/400.

### 4. Did the method preserve appropriate interval coverage?

Yes, where the model is right; no, where misfit escapes detection.

- Valid single-exponential fits: 95% credible-interval coverage 0.985
  (r = 3), **0.903 (r = 1, close to the 0.90 floor)**, 0.918 (r = 10); Aer
  thermal relaxation 0.909. Valid fits rejected: 1–2%.
- Worst false-confidence rate over delay ranges (re-test of E3.C5): 0.095
  (v0.1: 0.12), just inside the 0.10 bar.
- Forecasts: 80% predictive intervals for the threshold-crossing time
  contained the truth for 0.800 of 14 509 forecasts (95% CI 0.794–0.807). The
  forecasts are repeated within runs and therefore correlated; the interval
  is not a run-level confidence statement.
- Coverage *among accepted* fits is poor when misfit goes undetected (D11:
  0.615).

### 5. Does it distinguish workload changes from hardware changes?

Partly. Hardware was held constant while the workload changed at batch 24
(100 runs per scenario; v0.2 calibrated):

| Workload change | bucketed contexts (v0.1 default) | exact contexts (v0.2 option) |
|---|---|---|
| E1 deeper circuits (same bucket) | 1.00 | 0.08 |
| E2 noisier gate mix (same counts) | 1.00 | 0.10 |
| E3 circuit-frequency shift | 1.00 | 0.03 |
| E4 shots and batch interval | 0.09 | 0.09 |
| E5 2 µs idle before measurement | 1.00 | **1.00** |
| E6 extra two-qubit gates | 0.44 | **0.44** |

Exact contexts, which key each series on the qubit's gate composition and
idle time, remove the false alerts in E1–E3 (E.C1 passes for E1–E4). The
E5 and E6 failures (E.C1/E5, E.C1/E6) come from the **threshold channel**
(exploratory breakdown): the new circuits' effective flip rate is genuinely
above the absolute 5% threshold. The drift detector is not at fault; a
fixed threshold is being applied to a workload-dependent quantity. When a real
hardware change coincides with a workload change (E7), exact contexts start
new series, and the drift channel fired in only 1% of runs. Detection came
only through the absolute threshold. Bucketed contexts fail five of six
scenarios, as predicted.

### 6. Are results reproducible across independent seeds and software environments?

- **Independent seeds:** the calibrated v0.2 false-alert rates on the
  calibration seeds (0.048, 0.033, 0.078, 0.035 for K1–K4) and on the
  disjoint confirmatory seeds (0.045, 0.018, 0.068, 0.028 for A1–A4) agree
  within sampling error.
- **Same seeds:** per-batch logs are bit-identical on re-run on the same
  machine (`tests/test_reproducibility.py`).
- **Environments:** the unit, numerical-regression and Qiskit/Cirq
  integration tests and the smoke experiments pass in CI on Ubuntu, macOS
  and Windows with Python 3.10–3.13, and with the lowest allowed dependency
  versions. **The full experiments were run in one environment only**
  (Linux x86-64, Python 3.13.16, qiskit 2.5.2, qiskit-aer 0.17.2, cirq-core
  1.7.0). Bit-identity across machines is not established; Aer parallelises
  with OpenMP (`docs/INVESTIGATION_V02.md`).
- **Across frameworks (F):** Qiskit and Cirq report the same physical qubits
  and identical exact contexts. Their mean flip rates differ by at most
  2.5 standard errors (0.1–0.6% relative), with matching false-alert
  (0.05 vs 0.08) and detection (1.00 vs 1.00) rates. Exact density-matrix
  computation of the same circuits agrees to 1e-7, so the residual
  difference is sampling noise. The same check exposed a simulation bug
  (below).

### 7. Which preregistered criteria passed and which failed?

| Experiment | Passed | Failed |
|---|---|---|
| A false-alarm control | 14/14 | – |
| B gradual degradation | 7/7 | – |
| C abrupt degradation | 5/6 | C.C3 ×1.1 within 5 batches (0.09 vs ≥ 0.80; predicted) |
| D misspecification | 17/18 | D.C6/D11 correlated readout drift (false confidence 0.285 vs ≤ 0.10) |
| E workload shift | 4/12 | E.C1/E5 (1.00), E.C1/E6 (0.44); E.C2/E1, E2, E3, E5 (1.00), E6 (0.44); E.C2 failures predicted |
| F cross-framework | 5/5 | – |
| **Total** | **53/62** | |

The v0.1 criteria that failed in 2026-10-12's runs and were re-tested here:
E1.C3/E2.C3-type false alerts (now A.C1–C4, C.C6: pass), E3.C5 (D.C3:
pass), E3.C6 (D.C4: pass), E3.C7 (D.C5: pass). E2.C4, the spec claim, still
fails (C.C3).

### 8. What remains before deployment on real hardware

1. **No hardware data.** Batch independence, the binomial model of
   per-context counts, and the absence of within-job drift are assumptions,
   not observations. The `qnp.hardware` pathway exists, is read-only by
   default and is tested against fake backends, but has never run on a
   device.
2. **Absolute thresholds on workload-dependent rates misfire** (E5, E6).
   Thresholds should apply to a fixed probe context or be relative to each
   context's own baseline; neither is implemented or tested.
3. **Stationary fluctuations at the effect-gate scale alarm** (A6). A real
   deployment needs a fluctuation model (or a larger effect gate) chosen from
   device data.
4. **Correlated measurement noise during a T1 sweep defeats the misfit
   checks** (D11). Randomising delay order, or interleaving reference points,
   would make such drift visible; not implemented.
5. **Small changes are slow to detect.** A 10% change at 4000 deterministic
   shots per qubit per batch takes 10–15 batches.
6. **The Bayesian-marginal drift guarantee is empirical at fixed rates.** It
   held in every tested condition (A), but it is not a theorem for a fixed
   unknown rate.
7. **One computing environment for the full study**, and cross-machine
   bit-identity is unverified.
8. **Vendor calibration values are not ground truth** (docs/HARDWARE_VALIDATION.md),
   so a hardware study can test consistency, not accuracy, without an
   independent reference.

## Software defect found after the runs (does not affect recorded results)

While investigating the small Qiskit–Cirq difference in F, an exact
density-matrix comparison showed that `qnp.sim.aer_noise_model` omitted
thermal relaxation during two-qubit gates whenever the two-qubit
depolarizing strength was zero, while the Cirq builder applied it. Every
recorded experiment that used `qnp.sim` (D13, E, F) set a non-zero two-qubit
depolarizing strength or had no two-qubit gates, so no recorded result is
affected. Fixed after the study, with a regression test
(`tests/test_sim_noise.py::test_two_qubit_gate_relaxation_without_depolarizing_matches_cirq`).

## Run entries

| Experiment | Run ID |
|---|---|
| Calibration | `V02_calibration-20261012T205435-055ad8` |
| A | `V02_A_false_alarm-20261012T211741-820f36` |
| B | `V02_B_gradual-20261012T224246-88df08` |
| C | `V02_C_abrupt-20261012T225939-3138d2` |
| D | `V02_D_misspecification-20261012T233158-f62a92` |
| E | `V02_E_workload_shift-20261012T233842-e18aeb` |
| F | `V02_F_cross_framework-20261013T003304-0c31fc` |

v0.1 results (`results/SUMMARY.md`) and their correction
(`results/E2_CORRECTION.md`) are unchanged.
