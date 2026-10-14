# Results summary: v0.3 preregistered follow-up

**40 of 40 preregistered simulation criteria passed** (G 12/12, H 19/19,
I 9/9). **The hardware pilot (Experiment P) ran on `ibm_fez` on
2026-10-13/14: P.C2 passed (0 of 10 sweeps) and P.C1 failed (6 of 10 probe
series).** A failed P check is a finding about the device, not a failure of
the pilot (protocol §5): on this device, readout error fluctuated between
batches by more than binomial noise allows. The pilot is a 14-job QPU
experiment, separate from the read-only observation study proposed in
`docs/HARDWARE_VALIDATION.md`. All numbers come from the run entries listed
at the end. `tools/verify_results.py` recomputes every value from raw data.
The three simulation runs executed commit `8ea5b49` from a clean tree
(`source_tree_sha256 b850a691…`). That commit added the protocol
(`experiments/V03_PREREGISTRATION.md`) and was pushed before the first
confirmatory run. The pilot executed commit `1ea9556` from a clean tree
(`src/` and `experiments/` as at `5e4d270`). Deviations from the protocol in
method: none. Two pilot launches were interrupted by the host before
completing; their jobs are listed, unused, in `results/V03_DEVIATIONS.md`.
Three code changes were made after the simulation runs, none affecting a
recorded result: a pre-data fix to the pilot's analysis code, a tighter
readout-probe recognizer and a typing change (`results/V03_DEVIATIONS.md`).
Full tables: `results/V03_TABLES.md`.
Figures: `paper/figures/fig8`–`fig10`.

**Scope.** G, H and I are simulations (Qiskit Aer, numpy); nothing in them is
evidence about real quantum hardware. P is one device, five qubits and two
hours: it checks assumptions, not detection performance. The degradation
model in I is illustrative, not fitted to a device.

## The four questions

### 1. Real-device pilot (Experiment P): P.C2 passes, P.C1 fails

The preregistration fixes the pilot in advance:

- **Sequence:** a T1 sweep, then 12 readout-probe batches 10 minutes apart,
  then a second T1 sweep.
- **Qubits:** five, chosen by a fixed rule from the vendor's readout-error
  ranking.
- **Budget:** at most 14 jobs, 320,000 shots and 420 s of estimated QPU
  time. `JobBudget` enforces it before every job.

The runner sends nothing without `--submit`:

```bash
python experiments/run_v03.py pilot             # dry run
python experiments/run_v03.py pilot --submit    # ~2 h wall clock
```

It needs the environment variables `QISKIT_IBM_TOKEN` (API key) and
`QISKIT_IBM_INSTANCE` (instance CRN), or an account saved with
`tools/ibm_connect.py`, plus network access to `quantum.cloud.ibm.com` and
`iam.cloud.ibm.com` (`docs/HARDWARE_VALIDATION.md`).

The pilot checks two assumptions of the method:

- **P.C1:** readout-probe counts are binomial with a constant rate over two
  hours. This is the drift channel's null hypothesis.
- **P.C2:** readout is stable within one sweep job. This is what the v0.2
  sweep design needed, and what the v0.3 references detect.

**The run** (`V03_P_pilot-20261013T234830-220ff3`):

- **Backend:** `ibm_fez`, the least busy device at launch (no backend was
  named).
- **Qubits:** 54, 108, 127, 59 and 87, chosen by the rule from 155
  candidates.
- **Timing:** 14 jobs; probe batches from 23:49:37 to 01:39:40 UTC with a
  median gap of 10.0 min. The service reported execution timestamps for all
  14 jobs.
- **Cost:** 296,000 shots and 130 s of the instance's QPU time (the pre-run
  estimate was 144 s).

| Check | Observed | Pass if | Result |
|---|---|---|---|
| P.C1 probe series (5 qubits × 2 preparations) rejecting one constant rate across 12 batches (G-test, α = 0.01) | 6 of 10 | ≤ 1 | **FAIL** |
| P.C2 T1 sweeps (5 qubits × 2) whose interleaved ground references disagree (α = 0.01) | 0 of 10 | ≤ 1 | PASS |

**P.C1: readout fluctuates between batches by more than binomial noise.**
Under the null, two or more rejections out of 10 has probability about
0.004; six were observed.

- **Rejected series:** qubit 54 p(0\|1), 108 p(1\|0), 108 p(0\|1), 127
  p(0\|1), 59 p(1\|0) and 87 p(1\|0).
- **Dispersion:** their G statistic per degree of freedom is 2.3–12.6, where
  binomial noise gives about 1.
- **Largest excursion:** qubit 108's p(0\|1) was about 0.010 in batches 0–5,
  0.028–0.030 in batches 6–7, then 0.012–0.016.
- **Protocol's reading:** on this device, at this time scale, the drift
  channel's null (one constant binomial rate between calibrations) does not
  hold. Before deployment there, the monitor needs a fluctuation model or a
  larger effect gate.

**P.C2: no readout drift within a job.** In all 10 sweeps the interleaved
ground references agree (smallest p = 0.085). The failure mode that the
v0.3 design guards against did not occur in this run.

**Also reported (no criteria):**

- **T1 fits (MEASURED):** 7 of 10 accepted. The other three:
  - qubit 108, first sweep: insufficient evidence (`FEW_INFORMATIVE_DELAYS`);
  - qubit 108, second sweep: model misspecification;
  - qubit 127, first sweep: model misspecification, bi-exponential decay
    preferred.

  Between the two sweeps, about two hours apart, two qubits' T1 changed so
  much that their 95% intervals do not overlap:
  - qubit 87: from 167 µs [150, 189] to 94 µs [88, 101];
  - qubit 54: from 162 µs [151, 174] to 142 µs [134, 150].

  The vendor calibration did not change during the pilot.
- **Vendor values (OBSERVED), consistency only:**
  - vendor T1 lies inside 2 of the 7 accepted T1 intervals;
  - vendor readout errors lie inside the pooled probe interval for 4 of 10
    series;
  - the largest gap is qubit 59's p(0\|1): vendor 0.033, measured 0.0073
    [0.0066, 0.0081].

  Vendor values are not ground truth.
- **The v0.3 engine (P4)** monitored 5 qubits × `readout_error`. It raised 5
  WARNING drift alerts, all on qubit 108, at batches 7–11, after the
  excursion in its p(0\|1) series. Whether they are true or false alarms
  cannot be decided without an independent reference.
- **Metadata (P5):**
  - every property carried its own calibration timestamp;
  - `properties(datetime=…)` returned calibration history on this Open Plan
    account;
  - properties did not change during the pilot.

Rehearsals on the `FakeTorino` and `FakeManilaV2` backends ran the whole code
path. They are local simulations, so they are not evidence. They found two
defects, both fixed before the preregistration commit:

- Delays off a backend's timing grid were rejected; they are now rounded to
  the grid.
- Qubits with vendor T2 > 2·T1 broke the simulation; the selection rule now
  excludes them.

The CI job repeats the rehearsal on every push.

### 2. Do workload changes still trip the absolute threshold? (Experiment G)

No, in simulation. Setup:

- the v0.2 Experiment E device and workload changes;
- two readout-probe circuits added to every batch;
- 100 runs per scenario;
- both architectures evaluated on identical Aer counts.

Run-level false-alert rate, calibrated engine (c\* = 2.0), Wilson 95%
interval:

| Scenario (hardware unchanged) | v0.2 thresholds (every context) | v0.3 thresholds (readout probes) |
|---|---|---|
| G0 no change | 0.09 [0.05, 0.16] | 0.03 [0.01, 0.09] |
| G1 depth | 0.05 [0.02, 0.11] | 0.01 [0.00, 0.05] |
| G2 gate composition | 0.08 [0.04, 0.15] | 0.02 [0.01, 0.07] |
| G3 circuit frequencies | 0.02 [0.01, 0.07] | 0.00 [0.00, 0.04] |
| G4 shots and interval | 0.07 [0.03, 0.14] | 0.04 [0.02, 0.10] |
| **G5 2 µs idle before measurement** | **1.00** [0.96, 1.00] | **0.02** [0.01, 0.07] |
| **G6 extra two-qubit gates** | **0.43** [0.34, 0.53] | **0.05** [0.02, 0.11] |

- **The v0.2 failure reproduces on fresh seeds:** G5 1.00 and G6 0.43,
  against 1.00 and 0.44 in v0.2 E5/E6.
- **It disappears when the threshold moves to the probes.** The v0.3
  threshold channel raised no false alert in any of the 700 runs. The
  remaining 0–5% came from the drift channel (relative change).
- **The stable control also improves** (0.09 → 0.03), because effective flip
  rates no longer get crossing forecasts. In six of the nine G0 runs with a
  v0.2 false alert, the alert was a crossing forecast.
- **Anytime-valid v0.3 engine,** G0–G6 pooled: 2 of 700 runs (0.003, upper
  bound 0.010).
- **Hardware change during a workload change (G7):** q0's readout error rose
  ×1.5 at the same batch as a workload change. The q0 readout-probe series
  detected it within 6 batches in 100/100 runs; the first q0 alert came after
  a median of 1 batch.
  - The v0.2 architecture also detected it here, because the probe circuits
    were in its batches too, as effective-flip contexts that persist across
    the workload change.
  - In v0.2 E7, which had no probes, the drift channel caught it in 1% of
    runs.
  - What fixes this case is having a fixed probe context, not the
    threshold's placement.
- **Gradual readout ramp (G8):** every run warned before the crossing. The
  median lead was 242.5 min, against 252.5 min for the v0.2 architecture on
  the same data. That is 10 min later, inside the preregistered −30 min
  margin. Monitoring a second metric halves each per-series α, and the
  preregistration expected that to cost 10–20 min.
- **12 of 12 criteria pass.** The development predictions were G5 0.00, G0
  about 0.04, and a 10–20 min later warning. Observed: 0.02, 0.03 and 10 min.

### 3. Are T1 fits robust to slowly drifting readout now? (Experiment H)

Yes, in simulation, with the interleaved design: random acquisition order
plus 5 ground references. Setup:

- 200 fits per scenario and design;
- drift defined along the acquisition order, references included.

Fraction of fits that report a confidently wrong T1 (status OK, truth outside
the 95% interval), Wilson 95% interval:

| Scenario | v0.2 sequential | random order only | random order + 5 references (v0.3) |
|---|---|---|---|
| H11 AR(1) offset, the v0.2 D11 conditions | **0.255** [0.200, 0.320] | 0.090 [0.058, 0.138] | **0.005** [0.001, 0.028] |
| H11s slower AR(1), same sd | 0.200 [0.150, 0.261] | 0.130 [0.090, 0.184] | 0.025 [0.011, 0.057] |
| H11l linear offset ±1.5% across the sweep | 0.370 [0.306, 0.439] | 0.110 [0.074, 0.161] | 0.000 [0.000, 0.019] |
| H12 T1 drifting 120 → 80 µs | 0.010 | 0.000 | 0.000 |

- **The sequential design reproduces v0.2's D11 failure on fresh seeds:**
  0.255, against 0.285 recorded (H.M1).
- **Randomizing the order alone removes most of the error but not all.** It
  turns drift into visible scatter, but slow and linear drift still give
  0.13 and 0.11.
- **The interleaved ground references detect the drift directly:**
  `READOUT_DRIFT` fired in 181/200 H11 fits and 145/200 H11s fits.
- **Cost on valid data:** 2.5–4% of valid fits were rejected in H1–H3
  (criterion ≤ 10%), against 1.5–2% with the v0.2 design. The 5 references
  add a third to the shots of a 15-delay sweep.
- **Coverage of valid fits** is a pre-existing property of the unchanged fit.
  - Pooled over H1–H3: 0.917 interleaved, 0.931 sequential, 0.911 random
    order only.
  - Per scenario, interleaved: 0.90–0.93.
  - The r = 1 and r = 10 ranges sit near 0.90 in every design, as v0.2
    recorded (0.903, 0.918).
- **No regression on the v0.2 misspecification scenarios:**
  - Short delay ranges: `INSUFFICIENT_EVIDENCE` in 400/400 fits.
  - Fluctuating T1 and the 70/30 bi-exponential: `MODEL_MISSPECIFICATION` in
    400/400.
  - Heavy-tailed disturbances and T1 drift: rejected in 200/200 each.
  - Aer thermal relaxation through the new circuits (H13): coverage 0.949,
    1% rejected.
- **19 of 19 criteria pass.**

### 4. Do earlier warnings reduce failed jobs or calibration overhead? (Experiment I)

They reduce failed jobs. Against the daily schedule they do not reduce
calibration overhead, except when degradation is rare or absent. This is a
closed-loop simulation:

- two qubits, 4 days, 40 runs per scenario;
- readout probes in every 10-minute batch;
- a job **fails** if it runs while its qubit's true readout error is above 5%;
- a calibration costs one batch of downtime and resets the qubit;
- all policies see the same degradation events (common random numbers).

Failed jobs and calibrations per qubit-day (the start-of-run calibration is
not counted):

| Policy | I1 gradual (0.5/qubit-day) | I2 abrupt (1/qubit-day) | I3 mixed | I4 rare (0.1 + 0.1) | I0 stable |
|---|---|---|---|---|---|
| daily schedule (`fixed24`) | 14.4% / 0.75 | 13.4% / 0.75 | 20.2% / 0.75 | 3.4% / 0.75 | 0% / 0.75 |
| every 2 h (`fixed2`) | 0% / 11.75 | 1.00% / 11.75 | 0.39% / 11.75 | 0.08% / 11.75 | 0% / 11.75 |
| v0.3 warnings + daily (`eng_any+24`) | 0% / 1.67 | 0.31% / 2.01 | 0.15% / 2.06 | 0.04% / 1.40 | 0% / 1.13 |
| v0.3 warnings only (`eng_any_only`) | 0% / 0.82 | 0.25% / 1.27 | 0.22% / 1.31 | 0.03% / 0.48 | 0% / 0.20 |
| v0.3 crossing alerts only (`eng_cross_only`) | 3.8% / 0.45 | 4.7% / 0.41 | 4.5% / 0.60 | 1.1% / 0.12 | 0% / 0.00 |
| CUSUM only (`cusum_only`) | 0% / 0.81 | 0.41% / 1.29 | 0.25% / 1.24 | 0.02% / 0.45 | 0% / 0.14 |
| oracle: true error > 5% (`oracle_only`) | 0.33% / 0.47 | 0.34% / 0.49 | 0.46% / 0.66 | 0.09% / 0.13 | 0% / 0.00 |

**Failed jobs.** Warnings plus the daily schedule ran 4.7–5.4 percentage
points fewer jobs on a degraded qubit than fixed schedules with the same
calibration count in I1–I3 (I4: 1.8). The upper 95% bounds were all below
zero (I.C1). In I1–I3, 13–20% of jobs failed under the daily schedule;
monitoring cut this to at most 0.31%.

**Calibration overhead depends on what you compare with.**

- **Against fixed schedules that fail as few jobs:** warnings alone saved at
  least 4.9 (I1) to 11.2 (I4) calibrations per qubit-day (lower 95% bounds,
  I.C2).
  - In I2–I4, even a 2-hourly schedule (11.75 per qubit-day) failed more
    jobs than warnings alone at 0.5–1.3. These savings are therefore
    preregistered lower bounds.
- **Against the daily schedule:**
  - I1: warnings alone used about as many calibrations (+0.07 per qubit-day
    [−0.03, +0.17]).
  - I2, I3: about half a calibration more (+0.52, +0.56).
  - I4: fewer (−0.27).
  - I0, the stable device: 0.20, against 0.75 (I.C3). Every one of the 0.20
    was a false trigger.
- **The development prediction was half wrong here.** It said warnings alone
  would reach the failed-job level of warnings plus the daily schedule
  (0–0.2%) with fewer calibrations than the daily schedule.
  - The failed-job part held (0–0.25%).
  - The calibration part held only in I4 and I0. In I1–I3 warnings alone
    cost the same as the daily schedule or more, while failing far fewer
    jobs.

**Earlier warnings beat crossing alerts.** Acting on drift warnings, not only
on threshold crossings and forecasts, cost 0.6–1.0 more calibrations per
qubit-day (with the daily schedule). It removed a further 0.8–3.2 percentage
points of failed jobs. Measured as the share of the oracle's improvement over
the daily schedule, for the policies that keep the daily schedule:

- crossing alerts (threshold and forecast) captured 77–85%;
- all warnings captured 100–102%. They can exceed the oracle because they act
  before the crossing, while the oracle reacts at it.

**What did not hold up:**

- **A calibrated CUSUM on the same probe data did as well as the v0.3
  engine, or slightly better.**
  - Failed-job differences were within 0.16 points. One of ten 95%
    intervals excluded zero, in CUSUM's favour (I4, warnings only: 0.015
    points).
  - The engine used more calibrations in three of ten comparisons (+0.07 to
    +0.09 per qubit-day: I1 with the daily schedule, I3 with and without).
    It never used significantly fewer.
  - The operational gain comes from monitoring readout probes and acting on
    early warnings, not from the e-process.
- **False triggers are a large share of monitor-triggered calibrations.**
  0.27–0.44 per qubit-day were triggered when the qubit was neither above
  threshold nor degraded by 10%. Even on the stable device (I0), warnings
  alone triggered 0.20 per qubit-day. The simulation includes a stationary
  ±5% fluctuation of every qubit's readout error; alarms at that scale are
  the open v0.2 A6 issue.
- **Probe shots are not counted as overhead.** The monitoring policies spend
  2 × 2000 probe shots in every batch; fixed schedules do not. The comparison
  counts calibrations and downtime only.
- **The degradation rates were chosen, not measured.** The size of every
  effect depends on them.

**9 of 9 criteria pass.**

### Criteria

| Experiment | Passed | Failed |
|---|---|---|
| G workload changes with readout probes | 12/12 | – |
| H T1 sweeps under measurement drift | 19/19 | – |
| I operational value | 9/9 | – |
| **Total (simulation)** | **40/40** | |
| P hardware pilot (assumption checks, `ibm_fez`) | 1/2 (P.C2) | P.C1 |

## What remains before deployment on real hardware

This updates `results/V02_SUMMARY.md` §8.

1. **Hardware data: one two-hour pilot on one device (`ibm_fez`).** Of the
   three assumptions:
   - the binomial constant-rate model of probe counts **failed** (P.C1: 6 of
     10 series overdispersed);
   - batch independence was not tested separately: overdispersion can come
     from a changing rate or from correlated batches;
   - readout stability within a job **held** (P.C2: 0 of 10 sweeps).

   One device, five qubits and two hours do not show how general either
   finding is.
2. **Absolute thresholds on workload-dependent rates: addressed in
   simulation (G).** The fix needs readout probes in the monitored jobs
   (two circuits per batch here). Workload series keep only relative drift
   detection.
3. **Stationary fluctuations at the effect-gate scale still alarm (v0.2
   A6).** In I they caused 0.27–0.44 false-trigger calibrations per
   qubit-day. On `ibm_fez`, P.C1 found readout fluctuations well above
   binomial noise (G/dof up to 12.6). The simulated false-trigger rates of I
   are therefore probably optimistic for that device.
4. **Correlated readout drift during a T1 sweep: addressed in simulation
   (H).** P.C2 found none on `ibm_fez` (0 of 10 sweeps). Coverage of valid fits at r = 1 and
   r = 10 stays near 0.90, a pre-existing property.
5. **Operational value is a simulation result** with illustrative
   degradation rates. A calibrated CUSUM achieves the same. Cloud users
   cannot trigger calibrations; for them the intervention is avoiding or
   remapping a degraded qubit, which has not been tested.
6. **Unchanged from v0.2:**
   - small changes are slow to detect;
   - the Bayesian-marginal guarantee is empirical at fixed rates;
   - the full study ran in one computing environment;
   - vendor calibration values are not ground truth.

## Run entries

| Experiment | Run ID |
|---|---|
| G | `V03_G_workload_probes-20261013T053137-2ba66c` |
| H | `V03_H_sweep_drift-20261013T051106-9b540d` |
| I | `V03_I_operational-20261013T070404-7efe4c` |
| P | `V03_P_pilot-20261013T234830-220ff3` |

Calibration constants (c\* = 2.0, h\* = 10, k\* = 3.65) come from the v0.2
calibration run `V02_calibration-20261012T205435-055ad8`; no new calibration
was run. The v0.1 and v0.2 results and their summaries are unchanged.
