# Preregistration — Quantum Noise Profiler v0.3 study

**Status:** committed before any confirmatory run of Experiments G, H and I
and before any hardware job. The git commit that adds this file is the
preregistration timestamp; it is pushed before the first confirmatory run.
Results are appended to `results/runs.jsonl`; the v0.1 and v0.2 entries and
their protocols are never edited. Any deviation is recorded in
`results/V03_DEVIATIONS.md` with its reason, before the affected results are
reported. The analysis code that computes every summary and criterion
(`experiments/v03/analysis.py`, `experiments/v03/pilot.py`) is committed with
this file.

**Scope:** Experiments G, H and I use simulated data only. Experiment P is a
hardware pilot that this protocol fixes in advance; it runs only when an IBM
Quantum account is available and is reported whenever it runs.

## 0. What v0.3 changes, and what is tested

v0.2 left three release blockers that this study addresses
(`results/V02_SUMMARY.md` §8) and one open question:

| v0.2 finding | v0.3 change (method under test) | Experiment |
|---|---|---|
| An absolute 5% threshold on workload-dependent effective flip rates fires when the workload changes on unchanged hardware (E5: 1.00, E6: 0.44) | **Readout probes.** Prepare-and-measure circuits added to a job become MEASURED `readout_error` series (contexts `p(1\|0)`, `p(0\|1)`); the absolute threshold applies to them. Workload effective flip rates get no absolute threshold and no crossing forecast (relative drift monitoring only); exact contexts are the ingestion default. | G |
| Slow correlated readout drift during a T1 sweep passes the model checks (D11: 28.5% confidently wrong) | **Drift-robust sweep design.** Delays acquired in random order with 5 ground references (prepare \|0⟩, measure) spread over the acquisition; a G-test of reference homogeneity (α = 0.01) reports `READOUT_DRIFT` as model misspecification. | H |
| Whether earlier warnings save failed jobs or calibration time was unknown | **Closed-loop operational simulation** of calibration policies on degrading qubits. | I |
| No hardware data | **Pilot protocol** on an IBM Quantum device, checking the method's assumptions. | P |

Development work that led to these choices used seeds below 20 000 and is
documented in `experiments/v03/DEVELOPMENT_NOTES.md`.

## 1. Data separation and seeds

| Purpose | Seeds | Used for |
|---|---|---|
| Development | 10 000 – 19 999 | design choices, `experiments/v03/DEVELOPMENT_NOTES.md` |
| Calibration | none new | the v0.2 calibration run `V02_calibration-20261012T205435-055ad8` is reused: c\* = 2.0 (v0.2/v0.3 engine), h\* = 10 (CUSUM), k\* = 3.65 (Shewhart) |
| Confirmatory G, I | 60 000 – 69 999 | `seed_for(60000, e, j, r)` = 60 000 + 1000·e + 200·j + r; G: e = 0 (G0–G4, j = 0–4), e = 1 (G5–G8, j = 0–3); I: e = 2 (I0–I3, j = 0–3) |
| Confirmatory H | 70 000 – 84 999 | 70 000 + 1000·k + 200·d + r, k = scenario index (H1 … H13 in table order, 0-based), d = design index (sequential 0, randomized 1, interleaved 2) |
| Pilot | 90 000 – 90 001 | random acquisition order of the two T1 sweeps |

No method, threshold, grid or criterion is changed after confirmatory data
are generated. A software defect found in a confirmatory run is recorded as a
deviation; both runs are kept.

"Calibrated" below means every e-value threshold divided by e^c\* with
c\* = 2.0 from the v0.2 calibration (an empirical guarantee, as in v0.2);
"anytime-valid" means c = 0.

## 2. Experiment G — workload changes with readout probes

*Question:* with the absolute threshold moved from workload effective flip
rates to readout probes, do workload changes on unchanged hardware stop
raising alerts, while hardware changes are still detected?

Device and workloads: the v0.2 Experiment E device (T1 = 100 µs, T2 = 80 µs,
readout 2%, 1q depolarizing 0.002 with x 3× noisier, 2q depolarizing 0.01;
`qnp.sim`) and its workloads, simulated with Qiskit Aer; **two readout probe
circuits** (prepare \|00⟩ and \|11⟩, measure both qubits;
`qnp.measured.readout_probe_circuits`) are added to every batch with the
batch's shot count. 48 batches, 10 minutes apart (G4: 30 minutes after the
change). 100 runs per scenario.

| Scenario | Change at batch 24 |
|---|---|
| G0 | none (stable control) |
| G1 – G6 | the v0.2 workload changes E1 – E6 (depth, gate composition, circuit frequencies, shots and interval, 2 µs idle, extra two-qubit gates); hardware unchanged |
| G7 | E2 workload change **and** q0 readout 2% → 3% (×1.5) at the same batch |
| G8 | no workload change; q0 readout ramps linearly 2% → 6% over the 48 batches (crosses 5% at batch 35.25) |

Two architectures run on identical simulated counts:

| ID | Estimates | Thresholds | Family |
|---|---|---|---|
| `v02` | every circuit (probes included) → INFERRED effective flip rates, exact contexts | 5% on every effective-flip context (v0.2 defaults) | 2 qubits × 1 metric |
| `v03` | workload → INFERRED effective flip rates (exact contexts); probes → MEASURED readout_error | 5% on readout_error only (v0.3 defaults) | 2 qubits × 2 metrics |

Each architecture is evaluated anytime-valid (c = 0) and calibrated
(c = c\*). A false alert is any alert of any kind on any qubit (G0–G6); in G7,
any q0 alert before batch 24 or any q1 alert; in G8, any q1 alert.

| ID | Criterion | Pass if |
|---|---|---|
| G.C1 | `v03` calibrated: run-level false-alert rate, each of G1–G6 | ≤ 0.10 |
| G.C2 | `v03` calibrated: run-level false-alert rate, G0 | ≤ 0.10 |
| G.C3 | `v03` anytime-valid: run-level false-alert rate, G0–G6 pooled | Wilson upper 95% bound ≤ 0.10 |
| G.C4 | `v03` calibrated, G7: q0 change detected by the q0 readout-probe series within 6 batches | ≥ 0.90 |
| G.C5 | `v03` calibrated, G8: first q0 alert before the true crossing | ≥ 0.80 of runs |
| G.C6 | G8: `v03` calibrated median lead − `v02` calibrated median lead | ≥ −30 min (non-inferiority) |
| G.M1 | manipulation check: `v02` calibrated run-level false-alert rate in G5 | ≥ 0.50 |

G.M1 checks that the scenario still provokes the v0.2 failure, so that a
pass of G.C1/G5 can be attributed to the change. Also reported: per-channel
and per-metric breakdowns of every false-alert rate, post-change rates,
detection delays, and the contexts seen after the change.

*Predictions from development (12 runs per scenario, 48 for G0 and G8; not
evidence):* G5 falls from 1.00 (`v02`) to 0.00 (`v03`); the residual false
alerts of both architectures come mostly from the drift channel on effective
flip rates and can lie near 0.10 (as in v0.2 E with exact contexts:
0.03–0.10), so a G.C1 failure would not by itself implicate the threshold
change (the per-channel breakdown will show which channel fired); G0 about
0.04; `v03` warns 10–20 minutes later on the ramp (each per-series α is
halved by the second metric), so G.C6 is uncertain.

## 3. Experiment H — T1 sweeps under measurement drift

*Question:* does the drift-robust sweep design stop slow readout drift from
producing confidently wrong T1 values, without losing valid estimates or
mislabelling the v0.2 misspecification scenarios?

Synthetic binomial data as in v0.2 Experiment D (T1 = 100 µs, symmetric 2%
readout, 15 equally spaced delays on [0, r·T1], 1000 shots per circuit), but
every disturbance is defined on the **acquisition** axis: slot j of the
acquisition plan (references included) gets measurement offset x_j added to
P(1), or (H12) the T1 of slot j. A ground reference in slot j has
P(1) = 0.02 + x_j. Measurement-level disturbances (H10, H11*) affect
references; qubit-level ones (H6, H8, H12) do not.

| Scenario | Data (v0.2 analogue) |
|---|---|
| H1, H2, H3 | single exponential, r = 3, 1, 10 (D1–D3) |
| H4, H5 | single exponential, r = 0.2, 0.05 (D4–D5) |
| H6 | T1 fluctuating per circuit, lognormal σ = 0.3 (D6) |
| H8 | 0.7·e^(−t/100 µs) + 0.3·e^(−t/15 µs) (D8) |
| H10 | heavy-tailed disturbance 0.02·t₃ per circuit (D10) |
| H11 | AR(1) offset along the acquisition, φ = 0.8, innovation sd 0.01 (D11) |
| H11s | slower AR(1) offset, φ = 0.95, same stationary sd (0.0167) |
| H11l | linear offset −0.015 → +0.015 across the acquisition |
| H12 | T1 changing linearly 120 → 80 µs across the acquisition (D12) |
| H13 | Qiskit Aer thermal relaxation (T1 = 100 µs, T2 = 80 µs), 2% readout, r = 3, circuits from `decay_plan_circuits` (D13) |

Designs (`qnp.measured.decay_sweep_plan`): `sequential` (v0.2: delay order,
no references), `randomized` (random order, no references), `interleaved`
(random order + 5 ground references; the v0.3 default). H1–H12: 200 fits per
scenario and design. H13: `interleaved` only, 100 fits. False confidence =
status OK and the truth outside the 95% interval (H8: status OK at all).

| ID | Criterion | Pass if |
|---|---|---|
| H.C1 | `interleaved`, H11: false-confidence rate | ≤ 0.10 |
| H.C2 | `interleaved`, H11s and H11l: false-confidence rate, each | ≤ 0.10 |
| H.C3 | `interleaved`, H1–H3: loss of valid estimates (not OK), each | ≤ 0.10 |
| H.C4 | `interleaved`, H1–H3 pooled: coverage among OK | ≥ 0.90 |
| H.C4b | `interleaved`, H1–H3: coverage among OK, each | ≥ 0.85 |
| H.C5/fc | `interleaved`: max false-confidence rate over H4, H5, H6, H10, H12 | ≤ 0.10 |
| H.C5/abst | `interleaved`, H8: abstention rate | ≥ 0.50 |
| H.C5/H4, H5 | `interleaved`: non-OK labelled INSUFFICIENT_EVIDENCE | ≥ 0.90 each |
| H.C5/H6, H8 | `interleaved`: non-OK labelled MODEL_MISSPECIFICATION | ≥ 0.90 each |
| H.C6 | `interleaved`, H13: coverage among OK ≥ 0.90 and not-OK ≤ 0.10 | both |
| H.M1 | manipulation check: `sequential`, H11 false-confidence rate | ≥ 0.10 |

Coverage of *valid* fits at r = 1 and r = 10 is a pre-existing property of
the fit, which v0.3 does not change on valid data (references do not enter
the fit). Development runs put it at 0.87–0.92, so H.C4 pools H1–H3 and
H.C4b uses a 0.85 floor per scenario; per-scenario coverage is reported with
Wilson intervals and treated as an open issue, not as evidence about the
design change. The `randomized` arm is reported without criteria.

## 4. Experiment I — do earlier warnings reduce failed jobs or calibration overhead?

*Question:* if warnings trigger recalibration, do fewer jobs run on a
degraded qubit at the same calibration cost, and can calibrations be saved at
the same failed-job rate, compared with calibrating on a fixed schedule?

A closed-loop simulation (`experiments/v03/operational.py`). Two qubits, one
job slot per qubit per 10-minute batch, 4 days (576 batches) per run, 40 runs
per scenario. Every batch carries readout probes (2000 shots per
preparation). After each calibration a qubit's readout error starts at a
fresh base value (uniform 1.5–2.5%) and then degrades through random events
until its next calibration: gradual onsets (linear increase 0.2–0.8
percentage points per hour) and abrupt jumps (factor log-uniform in [1.3, 3]),
both Poisson in time; a stationary log-OU fluctuation (σ = 0.05, correlation
time 5 batches) always multiplies it. A calibration costs one batch of
downtime for that qubit and clears every earlier event. A job **fails** when
it runs on a qubit whose true error is above 5%. Event times and sizes, base
values and fluctuation paths are drawn once per run and shared by all
policies (common random numbers); probe counts of (run, qubit, batch) use the
same generator in every policy.

| Scenario | gradual onsets per qubit-day | jumps per qubit-day |
|---|---|---|
| I0 stable | 0 | 0 |
| I1 gradual | 0.5 | 0 |
| I2 abrupt | 0 | 1.0 |
| I3 mixed | 0.5 | 0.5 |
| I4 rare | 0.1 | 0.1 |

These rates are illustrative, not fitted to a device; the answer depends on
them, which is why five are run.

Policies (`experiments/v03/policies.py`). "Engine" policies run the v0.3
engine (calibrated, c\* = 2.0) on the qubit's MEASURED readout probes, with a
fresh profiler after each calibration and the family declared as 2 qubits ×
1 metric:

| Policy | Calibrates when |
|---|---|
| `none`, `fixed48` … `fixed2` | never; every qubit every 48, 24, 12, 8, 6, 4, 3, 2 hours (the fixed-schedule frontier) |
| `eng_any+24` | daily, and when the engine raises any WARNING or CRITICAL alert for the qubit (drift, threshold, forecast) |
| `eng_cross+24` | daily, and on CRITICAL threshold or WARNING forecast alerts only (crossing alerts, no drift warnings) |
| `eng_any_only`, `eng_cross_only` | as above, without the daily schedule |
| `cusum+24`, `cusum_only` | CUSUM on the per-batch pooled probe error (h\* = 10, reference = first 10 batches after a calibration), with / without daily |
| `shewhart+24`, `naive+24` | Shewhart (k\* = 3.65) / per-batch point estimate above 5%, with daily |
| `oracle+24`, `oracle_only` | as soon as the true error exceeds 5% (not realisable; a bound) |

**Frontier comparisons.** Fixed schedules give points (calibrations per
qubit-day, failed-job fraction), pooled over the runs of a scenario. Linear
interpolation between neighbouring schedules (achievable by time-sharing two
schedules) is the frontier. For a policy, *failed − frontier* is its failed
fraction minus the frontier's at the same calibration rate; *calibrations
saved* is the frontier's calibration rate at the policy's failed fraction
minus the policy's own rate (if the policy's failed fraction is below every
schedule's, the largest schedule rate is used, a conservative lower bound).
95% intervals: paired bootstrap over runs (2000 resamples, seed 2026).

| ID | Criterion | Pass if |
|---|---|---|
| I.C1 | `eng_any+24`, each of I1–I4: upper 95% bound of failed − frontier | ≤ 0 |
| I.C2 | `eng_any_only`, each of I1–I4: lower 95% bound of calibrations saved per qubit-day | ≥ 0 |
| I.C3 | I0: `eng_any_only` calibrations per qubit-day − `fixed24`'s | ≤ 0 |

Reported without criteria: every policy's failed fraction, calibration rate,
downtime and triggered calibrations split by the true state at the trigger
(above threshold / degraded by ≥ 10% / neither = false trigger); the share of
the oracle's improvement over `fixed24` each policy captures; paired
differences with bootstrap intervals for early versus crossing-only warnings
(`eng_any` − `eng_cross`), the v0.3 engine versus CUSUM, and the engine
versus the daily schedule.

*Predictions from development (8 runs per scenario, not evidence):* with
daily calibration alone, 8–19% of jobs fail in I1–I3; `eng_any+24` brings
this to 0–0.2%, 4–6 points below the frontier at its calibration rate;
`eng_any_only` reaches the same at fewer calibrations than the daily
schedule. A calibrated CUSUM performs about as well. On the stable device,
drift warnings trigger about 0.3 calibrations per qubit-day (false triggers
from the ±5% fluctuation) — fewer than the daily schedule, but not zero.
I4 (rare degradation) was not run in development.

## 5. Experiment P — hardware pilot (IBM Quantum)

*Question:* do the assumptions the method rests on hold on one real device
over about two hours, and does real data pass through the v0.3 pipeline? A
pilot cannot validate detection performance; it checks assumptions.

- **Backend:** the backend named on the command line, else the least busy
  operational IBM Quantum device with ≥ 5 qubits. Recorded with its version
  and the full read-only snapshot (per-property calibration timestamps).
- **Qubits (rule fixed now):** among qubits with a positive vendor T1 and T2,
  T2 ≤ 2·T1 (physically consistent values), a readout error, and reported
  operational (when the backend reports it), sorted by vendor readout error,
  the five at ranks round(f·(N−1)), f = 0.1, 0.3, 0.5, 0.7, 0.9.
- **Sequence:** T1 sweep (job 1) → 12 probe batches, one every 10 minutes
  (jobs 2–13) → T1 sweep (job 14). Snapshots before and after.
- **T1 sweeps:** per qubit, 15 delays on [0, 3 × vendor T1], interleaved
  design (5 ground references), 1000 shots per circuit, one job for all five
  qubits; acquisition-order seeds 90 000 and 90 001.
- **Probe batches:** two parallel probe circuits (all five qubits prepared in
  \|0⟩, then in \|1⟩), 4000 shots each.
- **Budget (enforced by `qnp.hardware.JobBudget`):** ≤ 14 jobs, ≤ 320 000
  shots, ≤ 420 s estimated QPU time; dry run unless `--submit`.

| ID | Check | Pass if |
|---|---|---|
| P.C1 | probe series (5 qubits × 2 preparations) whose 12 batch counts reject one constant rate (G-test, α = 0.01) | ≤ 1 of 10 |
| P.C2 | T1 sweeps (5 qubits × 2) whose interleaved references disagree (G-test, α = 0.01) | ≤ 1 of 10 |

Under their nulls each series rejects with probability 0.01, so two or more
rejections out of 10 has probability about 0.004. A failed check is a
finding about the device (the binomial constant-rate null of the drift
channel, or the stability of readout within a job, does not hold there), not
a failure of the pilot. Also reported (no criteria): T1 statuses and reason
codes; whether vendor T1 lies in each accepted fit's interval and whether
vendor readout errors lie in the pooled probe intervals (consistency, not
accuracy: vendor values are not ground truth); the v0.3 engine's alerts on
the probe series (family: 5 qubits × 1 metric); execution timestamps
reported by the service; whether calibration history
(`properties(datetime=…)`) is available; whether calibrations changed during
the pilot.

A rehearsal on a `qiskit_ibm_runtime` fake backend (local simulation) tests
the code path; it is recorded outside `results/` and is never evidence.

## 6. Reporting

All criteria are reported, pass or fail, in `results/V03_SUMMARY.md` with
the run IDs; every number is recomputed from raw data by
`tools/verify_results.py`. A failed criterion is not re-run with changed
settings.
