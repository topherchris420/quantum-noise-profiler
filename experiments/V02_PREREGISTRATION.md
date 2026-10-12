# Preregistration — Quantum Noise Profiler v0.2 study

**Status:** committed before any calibration or confirmatory run. The git
commit that adds this file is the preregistration timestamp. Results are
appended to `results/runs.jsonl` as new entries; the v0.1 entries and this
protocol are never edited. Any deviation is recorded in
`results/V02_DEVIATIONS.md` with its reason, before the affected results are
reported.

**Scope:** simulated data only (Qiskit Aer, Cirq, numpy). Nothing here is a
claim about real hardware.

## 0. Data separation

| Purpose | Seeds | Used for |
|---|---|---|
| Development | < 20 000 (ad hoc) | algorithm design, unit tests, `experiments/v02/DEVELOPMENT_NOTES.md` |
| Calibration | 20 000 – 21 999 | choosing the calibrated thresholds of §2 (v0.2 offset c\*, Shewhart k\*, CUSUM h\*, v0.1 bar b\*) |
| Confirmatory | 30 000 – 39 999 and 40 000 – 54 999 (Experiment D) | Experiments A–F; never used for any choice |

Seed of run r in condition j of experiment e: `block + 1000·e + 200·j + r`
(r < 200). Experiment D uses `40 000 + 1000·scenario + rep`.
Experiment indices: A = 0 and 6, B = 1, C = 2, E = 4 (scenarios 0–4) and 8
(scenarios 5–6), F = 5. Calibration uses experiment indices 0 and 1 of the
calibration block.

No method, threshold, grid or criterion is changed after confirmatory data
are generated. If a confirmatory run reveals a software defect, the defect,
its fix and the re-run are recorded as a deviation and both runs are kept.

## 1. Common setup (Experiments A–C)

- 2 physical qubits, readout error as the only noise (symmetric), so the
  true effective flip rate equals the injected readout error.
- Per batch: the v0.1 workload (`experiments/common.py::workload`): 2
  deterministic mirror circuits + 2 non-deterministic circuits, 2000 shots
  each. One batch every 10 simulated minutes, 48 batches (8 h) unless
  stated. Data path: Qiskit Aer + the `qnp` Qiskit adapter (confirmatory);
  the numpy surrogate (calibration; equivalence tested in
  `tests/test_v02_harness.py`).
- Monitoring family: 2 qubits × 1 metric × 2 contexts per qubit; threshold
  5%; `alpha_session = 0.10` split drift 0.5 / threshold 0.25 / forecast 0.25.
- **False alert** (run level): any alert of any kind and any level (INFO
  included) on a qubit whose true rate has not changed, at any batch of the
  run. **Qubit level**: the same per (run, stable qubit) pair.
  Wilson 95% intervals are reported for every rate.

### Methods compared (all run on identical data)

| ID | Method | Thresholds |
|---|---|---|
| `v02` | v0.2 sequential engine, default `DriftConfig` | anytime-valid (1/α) — no calibration |
| `v02cal` | v0.2 engine with `log_e_offset = c*` | c\* from §2 |
| `v01` | frozen v0.1 engine (`LegacyDriftConfig`), all alerts | v0.1 defaults |
| `v01cal` | v0.1 WARNING/CRITICAL drift and threshold alerts with recorded posterior probability ≥ b\* (forecasts excluded: they cannot be re-thresholded) | b\* from §2 |
| `shewhart` | 3σ-style chart on per-batch pooled flip rate per qubit, reference = first 10 batches | k\* from §2 |
| `cusum` | one-sided tabular CUSUM on standardised per-batch rates, allowance 0.5σ, reference = first 10 batches | h\* from §2 |
| `naive` | per-batch point estimate > 5% (Experiment B only, as in E1) | none |

Charts can only alarm from batch 10. Both qubits are monitored by every
method.

## 2. Calibration (before any confirmatory run)

Data: surrogate pipeline, calibration seeds, four stable conditions
(K1: both qubits 0.5%; K2: both 2%; K3: q0 4.5%, q1 2%; K4: q0 4.9%, q1 2%),
48 batches, 400 runs per condition (200 for `v01cal`).

Rule: for each calibrated method, pick the grid value that makes it as
sensitive as possible subject to **max over K1–K4 of the run-level
false-alert rate ≤ 0.08**:

| Method | Grid | Choice |
|---|---|---|
| `v02cal` | c ∈ {0, 0.25, …, 3.5} | largest c meeting the rule |
| `shewhart` | k ∈ {2.00, 2.05, …, 6.00} | smallest k |
| `cusum` | h ∈ {1.0, 1.5, …, 40.0} | smallest h |
| `v01cal` | b ∈ {0.95, 0.96, 0.97, 0.98, 0.99, 0.995, 0.998, 0.999, 0.9995, 0.9999, 0.99999} | smallest b |

The target 0.08 (not 0.10) leaves room for calibration-sample error. The
chosen values are recorded in a `V02_calibration` run entry before
Experiment A starts.

## 3. Experiment A — sequential false-alarm control

*Question:* is the probability of at least one false alert over a whole
session ≤ 10%?

| Condition | q0 | q1 | Batches | Runs |
|---|---|---|---|---|
| A1 | 0.5% | 0.5% | 48 | 400 |
| A2 | 2% | 2% | 48 | 400 |
| A3 | 4.5% | 2% | 48 | 400 |
| A4 | 4.9% | 2% | 48 | 400 |
| A5 | 2% | 2% | 144 (24 h) | 200 |
| A6 (exploratory) | 2% × exp(OU), σ = 0.1, τ = 5 batches, independent per qubit | same | 48 | 200 |

`v01` and `v01cal` are run on the first 200 runs of A1–A4 and the first
100 of A5. A6 is a stationary fluctuation, not a strict null; it is
reported without a criterion.

| ID | Criterion | Pass if |
|---|---|---|
| A.C1 | `v02`: run-level false-alert rate, each of A1–A4 | Wilson upper 95% bound ≤ 0.10 |
| A.C2 | `v02cal`: run-level false-alert rate, each of A1–A4 | point estimate ≤ 0.10 and Wilson upper bound ≤ 0.13 |
| A.C3 | `v02` over a 24 h session (A5) | Wilson upper bound ≤ 0.10 |
| A.C4 | `v02cal` over a 24 h session (A5) | point estimate ≤ 0.10 |

Also reported: qubit-level rates, per-channel rates, false alerts per
monitoring hour, `v01`/`v01cal`/chart rates.

## 4. Experiment B — gradual degradation

q0 ramps linearly; q1 constant 2% (every q1 alert is false).

| Condition | q0 ramp over 48 batches | True 5% crossing | Runs |
|---|---|---|---|
| B1 | 2% → 6% | batch 35.25 (352.5 min) | 200 |
| B2 | 2% → 5.5% | batch 40.29 (402.9 min) | 200 |

Measured per method: detection probability (any q0 alert in the run),
early-detection probability (first q0 alert before the true crossing),
median warning lead time = (true crossing − first q0 alert) in minutes,
detection-delay distribution (batch of first q0 alert: quartiles),
false alerts per run (number of batches with an alert on q1, mean) and per
monitoring hour (÷ 8), run-level q1 false-alert rate. Forecast calibration:
for every `v02` forecast alert on q0 issued before the true crossing,
whether the 80% predictive interval contains the true time to crossing.

| ID | Criterion | Pass if |
|---|---|---|
| B.C1 | `v02cal` early-detection fraction, B1 and B2 | ≥ 0.80 each |
| B.C2 | `v02cal` median lead − best median lead of `shewhart`/`cusum` (B1) | ≥ −30 min (non-inferiority) |
| B.C3 | `v02cal` median lead − `v01cal` median lead (B1) | ≥ 0 |
| B.C4 | coverage of `v02` 80% predictive crossing intervals (B1 and B2 pooled) | in [0.70, 0.90] |
| B.C5 | `v02cal` run-level q1 false-alert rate (B1 and B2 pooled) | ≤ 0.10 |

## 5. Experiment C — abrupt degradation

q0 = 2% for batches 0–23, then 2% × {1.1, 1.2, 1.5} from batch 24, plus a
no-step condition; q1 = 2%. 200 runs per condition.

Detection delay = (first q0 alert at or after batch 24) − 24, counted
whether or not a pre-step false alert occurred; also reported conditional
on a clean pre-step window. False alert = any q0 alert before batch 24, or
any q1 alert. Detection success definitions are fixed here: "within w
batches" means delay ≤ w.

| ID | Criterion | Pass if |
|---|---|---|
| C.C1 | `v02cal` ×1.5 detected within 6 batches | ≥ 0.90 |
| C.C2 | `v02cal` ×1.2 detected within 24 batches | ≥ 0.50 |
| C.C3 | `v02cal` ×1.1 detected within 5 batches (20 circuits; the original spec claim) | ≥ 0.80 |
| C.C4 | `v02cal` − best of `shewhart`/`cusum`: ×1.2 detected within 24 | ≥ −0.10 (non-inferiority) |
| C.C5 | `v02cal` − `v01cal`: ×1.2 detected within 24 | ≥ 0 |
| C.C6 | `v02cal` run-level false-alert rate, all conditions pooled | ≤ 0.10 |

C.C3 is expected to fail for every method: it is a statistical-power limit
(v0.1 audit). It is recorded to keep the claim honest.

## 6. Experiment D — model misspecification of T1 fits

Synthetic binomial data unless stated: T1 = 100 µs, symmetric 2% readout
error, 15 equally spaced delays on [0, r·T1], 1000 shots per delay,
200 repetitions per scenario. Statuses: OK, INSUFFICIENT_EVIDENCE,
MODEL_MISSPECIFICATION.

| Scenario | Data | Truth used for coverage |
|---|---|---|
| D1 | single exponential, r = 3 | 100 µs |
| D2 | single exponential, r = 1 | 100 µs |
| D3 | single exponential, r = 10 | 100 µs |
| D4 | single exponential, r = 0.2 | 100 µs |
| D5 | single exponential, r = 0.05 | 100 µs |
| D6 | T1 fluctuating per delay, lognormal σ = 0.3 (= E3d-i) | 100 µs (median) |
| D7 | as D6 with σ = 0.1 (mild) | 100 µs |
| D8 | 0.7·e^(−t/100µs) + 0.3·e^(−t/15µs) (= E3d-ii) | none: no single T1 |
| D9 | 0.9·e^(−t/100µs) + 0.1·e^(−t/50µs) (mild) | none |
| D10 | heavy-tailed disturbance: P1 at each delay perturbed by 0.02·t₃ (Student-t, 3 dof), clipped to [0, 1] | 100 µs |
| D11 | time-correlated measurement noise: readout offset follows AR(1) along the sweep, φ = 0.8, innovation sd 0.01 | 100 µs |
| D12 | unmodelled drift: T1 changes linearly from 120 µs to 80 µs during the sweep (acquired in delay order) | 100 µs (sweep mean) |
| D13 | Qiskit Aer thermal relaxation (T1 = 100 µs, T2 = 80 µs), 2% readout, r = 3; 100 repetitions | 100 µs |

False confidence = status OK and truth outside the 95% interval (D8, D9:
status OK at all). Rejection rate = fraction not OK.

| ID | Criterion | Pass if |
|---|---|---|
| D.C1 | D1–D3: coverage among OK | ≥ 0.90 each |
| D.C2 | D1–D3: loss of valid estimates (not OK) | ≤ 0.10 each |
| D.C3 | D1–D5: max false-confidence rate (re-test of E3.C5) | ≤ 0.10 |
| D.C4 | D6: false-confidence rate (re-test of E3.C6) | ≤ 0.10 |
| D.C5 | D8: abstention rate (re-test of E3.C7) | ≥ 0.50 |
| D.C6 | D10, D11, D12: false-confidence rate | ≤ 0.10 each |
| D.C7 | D4–D5: among non-OK, fraction INSUFFICIENT_EVIDENCE | ≥ 0.90 |
| D.C8 | D6, D8: among non-OK, fraction MODEL_MISSPECIFICATION | ≥ 0.90 |
| D.C9 | D13: coverage among OK ≥ 0.90 and not-OK ≤ 0.10 | both |

D7 and D9 are reported as detection-power probes without criteria.

## 7. Experiment E — workload distribution shift

Hardware constant for 48 batches: T1 = 100 µs, T2 = 80 µs on both qubits,
symmetric readout 2%, 1q depolarizing λ = 0.002 with x gates 3× noisier,
2q depolarizing 0.01 (`qnp.sim`). The workload changes at batch 24.
100 runs per scenario, `v02` and `v02cal`, each in two context modes
(`bucket`, the v0.1 default, and `exact`) on identical simulated counts.

| Scenario | Workload change at batch 24 |
|---|---|
| E1 depth | mirror circuits padded with 4 → 8 identity `sx` pairs-of-pairs (same 1q bucket) |
| E2 gate composition | 4 padding `sx` → 4 padding `x` (same count, noisier gate) |
| E3 circuit frequencies | mix of unpadded : 10-`sx`-padded mirrors 3:1 → 1:3 (same bucket) |
| E4 measurement schedule | 2000 → 500 shots per circuit and 10 → 30 min between batches |
| E5 idle duration | 2 µs delay inserted before measurement |
| E6 two-qubit interactions | an extra `cx`·`cx` pair (2q bucket changes) |
| E7 confounded (exploratory) | E2 change **and** a real ×1.5 readout increase on q0 at the same batch |

Every alert in E1–E6 is false.

| ID | Criterion | Pass if |
|---|---|---|
| E.C1 | `v02cal`, exact contexts: run-level false-alert rate, each of E1–E6 | ≤ 0.10 |
| E.C2 | `v02cal`, bucket contexts: run-level false-alert rate, each of E1–E6 | ≤ 0.10 |

Prediction (from the design, before data): E.C2 fails for E1, E2, E3 and
E5, because bucketed contexts pool circuits whose noise differs; E.C1
passes. E7 is reported descriptively: exact contexts start a new series at
the workload change and therefore cannot see a hardware change that
coincides with it.

## 8. Experiment F — cross-framework validation

The same scenario through Qiskit (Aer, ISA-style circuits on physical
qubits 3 and 7 of an 8-qubit register) and Cirq (`DensityMatrixSimulator`,
`LineQubit(3)`, `LineQubit(7)`), with the same `qnp.sim` device noise
(T1/T2, 1q/2q depolarizing, readout 2%). F1: stable; F2: ×1.5 readout step
on qubit 3 at batch 24. 100 runs per condition per framework, `v02cal`,
exact contexts.

| ID | Criterion | Pass if |
|---|---|---|
| F.C1 | reported physical qubit labels | {3, 7} in both frameworks, every run |
| F.C2 | exact context strings | identical sets in both frameworks |
| F.C3 | mean per-batch flip rate per (qubit, context), F1 | difference within 3 standard errors |
| F.C4 | F1 run-level false-alert rate difference | \|Δ\| ≤ 0.10 |
| F.C5 | F2 detection within 6 batches, difference | \|Δ\| ≤ 0.15 |

Also reported: interval widths, delay distributions, every discrepancy found.

## 9. Reproducibility

- Every run entry records the environment and source-tree hash at launch
  and at completion, the seed block and the protocol section.
- R.C1: re-running the first 5 runs of C (×1.2) with the same seeds gives
  identical per-batch logs (bit-for-bit) — checked by
  `tests/test_reproducibility.py` and the CI smoke job.
- Calibration (§2) and confirmatory (A2) false-alert rates of `v02cal` at
  the same condition are compared as an independent-seed replication
  (reported, no criterion).

## 10. Reporting

All criteria are reported, pass or fail, in `results/V02_SUMMARY.md` with
the run IDs. A failed criterion is not re-run with changed settings; if a
later version changes the method, it is a new study with a new
preregistration.
