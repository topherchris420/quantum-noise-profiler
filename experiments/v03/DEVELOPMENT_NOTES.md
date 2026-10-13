# v0.3 development notes (not evidence)

Everything here used **development seeds below 20 000** (10 000–19 999,
`experiments/v03/dev_sweeps.py`). It informed design choices made *before*
`experiments/V03_PREREGISTRATION.md` was committed. None of it is evidence for
or against any v0.3 hypothesis, and none of these seeds is reused for a
confirmatory run.

Reproduce: `python experiments/v03/dev_sweeps.py h --reps 100`,
`python experiments/v03/dev_sweeps.py hv <out.json>`,
`python experiments/v03/dev_sweeps.py g --reps 12`,
`python experiments/v03/dev_sweeps.py i --reps 8 --days 4`.

## H: T1 sweeps under measurement drift (100 fits per cell)

Rates are fractions of all fits. False confidence = status OK and the truth
outside the 95% interval. Designs: `sequential` (v0.2: delays in order, no
references), `randomized` (random order), `interleaved` (random order + 5
ground references, G-test at α = 0.01). At this stage the acquisition-order
runs test was also a rejection rule (α = 0.01).

| Scenario | sequential: not OK / false conf. | randomized | interleaved |
|---|---|---|---|
| H1 valid, r = 3 | 0.04 / 0.06 | 0.02 / 0.03 | 0.01 / 0.05 |
| H2 valid, r = 1 | 0.03 / 0.04 | 0.00 / 0.10 | 0.06 / 0.12 |
| H3 valid, r = 10 | 0.00 / 0.12 | 0.03 / 0.10 | 0.06 / 0.07 |
| H11 AR(1) offset (D11 parameters) | 0.36 / **0.26** | 0.48 / 0.09 | 0.92 / **0.02** |
| H11s slow AR(1) offset, same sd | 0.08 / 0.26 | 0.18 / 0.18 | 0.70 / 0.08 |
| H11l linear offset −1.5% → +1.5% | 0.03 / 0.25 | 0.29 / 0.07 | 0.99 / 0.00 |
| H12 T1 120 → 80 µs during the sweep | 0.96 / 0.00 | 1.00 / 0.00 | 1.00 / 0.00 |
| H6, H8 (misfit), H10 (heavy tail) | ≥ 0.95 rejected, false conf. ≤ 0.01 in every design | | |
| H4, H5 (short ranges) | all INSUFFICIENT_EVIDENCE in every design | | |

1. The sequential design reproduces v0.2's D11 failure (0.26 vs 0.285
   recorded). Randomizing the order alone helps against fast drift (0.09) but
   not against slow drift (0.18). Interleaved references catch both.
2. Valid fits: the drift checks reject 1–2% (reference G-test: 5 of 300 fits
   at α = 0.01).

### Variants of the reference check (200 fits per cell, all tests computed with α = 0 and decided offline)

| Variant | H1/H2/H3 not OK | H2, H3 coverage among OK | H11 / H11s / H11l false conf. |
|---|---|---|---|
| K = 5, G-test only | 0.045 / 0.045 / 0.040 | 0.874 / 0.870 | 0.020 / 0.045 / 0.000 |
| K = 5, G-test + acquisition runs | 0.055 / 0.050 / 0.045 | 0.874 / 0.874 | 0.020 / 0.045 / 0.000 |
| K = 5, G-test + trend test (α/2 each) | 0.040 / 0.035 / 0.035 | 0.881 / 0.870 | 0.020 / 0.045 / 0.000 |
| K = 7, G-test only | 0.020 / 0.035 / 0.045 | 0.922 / 0.916 | 0.000 / 0.040 / 0.000 |

(K = 5 and K = 7 rows are different simulations; the trend and
acquisition-runs rows reuse the K = 5 data.)

3. A trend test on the references and the acquisition-order runs test add
   no drift detection beyond the G-test; the runs test only adds false
   rejections. **Choice:** K = 5 references, G-test at α = 0.01; the
   acquisition-order runs test is reported in the diagnostics but is not a
   rejection rule (`FitDiagnosticsConfig.acquisition_runs_alpha = 0`).
   K = 7 was not chosen: similar detection, two more circuits per sweep.
4. **Pre-existing, not changed by v0.3:** coverage of the 95% credible
   interval among accepted *valid* fits is marginal at r = 1 and r = 10
   (0.87–0.92 across these development runs; v0.2 recorded 0.903 and 0.918
   for D2, D3). The design change does not touch the fit on valid data, so
   v0.3 cannot fix or worsen it; the preregistration tests pooled coverage
   (H1–H3) and a looser per-scenario floor, and reports this as an open issue.

## G: workload shift with readout probes (12 runs per scenario)

Run-level false-alert rates (calibrated, c* = 2.0) on the Experiment E device
with two readout probe circuits per batch:

| Scenario | v0.2 architecture | v0.3 architecture |
|---|---|---|
| G0 stable | 0.08 | 0.17 (2/12, both drift alerts on effective flip rates) |
| G1–G4 | 0.00–0.17 | 0.00–0.08 |
| G5 idle time | **1.00** | **0.00** |
| G6 extra 2q gates | 0.33 | 0.08 (1/12, readout probe) |
| G7 readout ×1.5 at the workload change: q0 detected within 6 batches | 1.00 | 1.00 (readout probes: 1.00) |
| G8 ramp 2 → 6%: early detection / median lead | 1.00 / 272.5 min | 1.00 / 252.5 min |

5. The threshold fix behaves as designed (G5: 1.00 → 0.00). The residual
   false alerts in both architectures come from the drift channel on
   effective flip rates, as in v0.2 Experiment E (exact contexts:
   0.03–0.10).
6. The v0.3 architecture warns about 20 min (2 batches) later on the ramp:
   its family has two metrics per qubit, so every per-series α is halved.
7. 12 runs cannot resolve rates near 0.10; see the follow-up below.

### Follow-up: G0 and G8, 36 more runs each (seed offset 12)

| | v0.2 architecture (calibrated) | v0.3 architecture (calibrated) |
|---|---|---|
| G0 stable: run-level false alerts | 1/36 (forecast) | 0/36 |
| G8 ramp: early detection / median lead | 1.00 / 252.5 min | 1.00 / 242.5 min |
| G8: paired lead difference v0.3 − v0.2 (median, quartiles) | | −10 min (−20, 0) |

8. Pooled over both development runs, the v0.3 calibrated false-alert rate
   on the stable control is 2/48 (0.04), and the ramp lead is 10–20 minutes
   shorter than with the v0.2 architecture: G.C2 is likely to pass, G.C6 is
   uncertain (margin −30 min).

## I: operational value (8 runs × 4 days per scenario)

Failed-job fraction (jobs run on a qubit whose true error is above 5%) and
calibrations per qubit-day (4-day runs; the start-of-run calibration is not
counted, so the daily schedule shows 0.75):

| Policy | I0 stable | I1 gradual | I2 abrupt | I3 mixed |
|---|---|---|---|---|
| none | 0 / 0 | 0.391 / 0 | 0.519 / 0 | 0.591 / 0 |
| fixed48 | 0 / 0.25 | 0.204 / 0.25 | 0.274 / 0.25 | 0.410 / 0.25 |
| fixed24 | 0 / 0.75 | 0.078 / 0.75 | 0.124 / 0.75 | 0.194 / 0.75 |
| fixed12 | 0 / 1.75 | 0.024 / 1.75 | 0.066 / 1.75 | 0.066 / 1.75 |
| fixed4 | 0 / 5.75 | 0.000 / 5.75 | 0.023 / 5.75 | 0.012 / 5.75 |
| fixed2 | 0 / 11.75 | 0.000 / 11.75 | 0.005 / 11.75 | 0.005 / 11.75 |
| eng_any+24 | 0 / 1.25 | 0.000 / 1.42 | 0.002 / 2.03 | 0.001 / 2.08 |
| eng_cross+24 | 0 / 0.75 | 0.008 / 0.94 | 0.020 / 1.05 | 0.023 / 1.16 |
| eng_any_only | 0 / 0.30 | 0.000 / 0.61 | 0.002 / 1.42 | 0.001 / 1.31 |
| eng_cross_only | 0 / 0 | 0.022 / 0.28 | 0.021 / 0.44 | 0.054 / 0.56 |
| cusum+24 | 0 / 1.17 | 0.000 / 1.42 | 0.001 / 2.13 | 0.002 / 2.05 |
| cusum_only | 0 / 0.16 | 0.000 / 0.56 | 0.001 / 1.41 | 0.001 / 1.25 |
| oracle_only | 0 / 0 | 0.002 / 0.28 | 0.004 / 0.52 | 0.004 / 0.61 |

9. Warning-triggered recalibration on top of the daily schedule
   (`eng_any+24`) removes almost all failed jobs at about twice the daily
   calibration rate; at that rate the fixed schedules leave 4–6% of jobs
   failing. Without a schedule (`eng_any_only`) the failed fraction stays near
   0.1–0.2% with fewer calibrations than the daily schedule in I0, I1 and I3.
10. Crossing alerts alone (`eng_cross`, no drift warnings) leave 1–5% failed:
    the threshold e-process needs evidence above 5% before it fires, so the
    early (drift) warnings are what prevent failures here.
11. A calibrated CUSUM does about as well as the engine, with fewer false
    triggers on the stable device (0.16 vs 0.30 per qubit-day without a
    schedule). The engine's drift warnings respond to the ±5% stationary
    fluctuation (compare v0.2's exploratory A6).
12. Cost: about 30 s per engine policy per 4-day run, so the confirmatory
    run uses 40 runs per scenario. A rare-degradation scenario (I4: 0.1
    gradual + 0.1 abrupt events per qubit-day) is added because it is the
    regime where monitoring's value is least obvious; it was not run here.
13. Pilot rehearsals on fake backends exposed two hardware-path defects,
    fixed before preregistration: (a) the local simulator of a fake backend
    rejects qubits whose vendor T2 > 2·T1, so the pilot's qubit-selection rule
    excludes physically inconsistent vendor values; (b) backends with timing
    constraints (e.g. 16-dt alignment) reject delays off their grid, so sweep
    delays are now rounded to the backend's delay grid and the fit uses the
    rounded values (`qnp.hardware.align_delays`).
