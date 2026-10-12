# Preregistration — Quantum Noise Profiler v0.1 experiments

Committed **before** the first recorded run. The criteria below are fixed; if
the method changes, the experiments are re-run as new entries in
`results/runs.jsonl` and earlier entries (including failures) stay in the log.
Smoke runs used to debug the harness (n ≤ 3) were written outside the repo and
are not evidence.

Simulator: Qiskit Aer with **readout error as the only noise source**, so the
ground-truth effective flip rate equals the injected readout error. This is a
deliberate simplification; it doesn't test gate-noise confounding (see E3d and
the validation plan for what this leaves open).

Common workload per batch (job): 4 two-qubit circuits = 2 deterministic
"mirror" circuits (random layer + its inverse, one with final X on both
qubits) + 2 circuits with non-deterministic output. 2000 shots per circuit.
One batch every 10 simulated minutes. The profiler runs `check()` after every
batch (sequential monitoring, as in deployment). Default `DriftConfig`:
recent window 3 batches, ≥3 baseline batches, 10% minimum effect, P ≥ 0.95,
threshold 5%, forecast extrapolation capped at the observed span.

## E1 — Gradual drift

*Question:* does the profiler warn about a slowly degrading qubit before a
conventional static threshold does?

- q0 readout error ramps linearly 2% → 6% over 48 batches (true 5% crossing at
  batch 35.25 = 352.5 min). q1 constant 2%.
- Control: q0 constant at 4.5% (just below threshold) for 48 batches.
- Conventional comparator: per-batch point estimate on deterministic circuits
  > 5% ("naive").
- Profiler early warning = first forecast or threshold alert on q0.
- 50 seeds.

| ID | Criterion | Pass if |
|---|---|---|
| E1.C1 | fraction of seeds where the profiler alerts before the true crossing | ≥ 0.80 |
| E1.C2 | median profiler lead time − median naive lead time | ≥ 30 min |
| E1.C3 | control: fraction of runs with **any** profiler alert on q0 (incl. INFO forecasts) | ≤ 0.10 |

## E2 — Sudden degradation

*Question:* does it catch abrupt changes without excessive false alarms?

- q0 readout error 2% for 24 batches, then steps to 2% × {1.5, 1.2, 1.1};
  plus a no-step control. q1 constant 2% throughout (every q1 alarm is false).
- Detection = first drift/threshold WARNING or CRITICAL on q0 at or after the step.
- False alarm = any WARNING/CRITICAL on q0 before the step (or anywhere in the
  control), or on q1 anywhere.
- Comparator: Shewhart 3σ chart on per-batch rates, baseline = first 10 batches.
- 50 seeds per condition.

| ID | Criterion | Pass if |
|---|---|---|
| E2.C1 | ×1.5 step detected within 6 batches | ≥ 0.90 of seeds |
| E2.C2 | ×1.2 step detected within 24 batches | ≥ 0.50 of seeds |
| E2.C3 | runs with any false WARNING/CRITICAL (all conditions) | ≤ 0.10 |
| E2.C4 | original spec claim: ×1.1 detected within 20 circuits (5 batches) | ≥ 0.80 of seeds |

E2.C4 is a check of a claim in the original project brief. A power
calculation suggests 2000 shots × 2 deterministic circuits per batch is far
too little for it; we expect it to fail and record it either way.

## E3 — Insufficient evidence

*Question:* does the profiler recognize when the data can't support an
estimate? Headline metric: **false-confidence rate** = P(status OK and truth
outside the reported 95% interval).

- **E3a** workload identifiability (Aer + Qiskit adapter, 30 seeds): 8 circuits
  per batch with 0%, 25%, 100% deterministic circuits; true flip rate 3%.
- **E3b** interval calibration of the effective flip estimator (direct
  binomial draws, 10×REPS per cell): p ∈ {0.1%, 0.5%, 2%, 10%} ×
  n ∈ {50, 100, 200, 500, 2000, 10000}; `min_shots = 200`.
- **E3c** T1 delay range (synthetic binomial, REPS per cell): T1 = 100 µs, 2%
  readout error, 15 delays on [0, r·T1], r ∈ {0.01, 0.05, 0.2, 1, 3, 10}, 1000 shots.
- **E3d** misspecification (REPS each): (i) T1 fluctuating per sweep point,
  lognormal σ = 0.3 around 100 µs; (ii) bi-exponential decay 0.7·e^(−t/100µs)
  + 0.3·e^(−t/15µs), where no single T1 exists and abstention is correct.
- REPS = 200.

| ID | Criterion | Pass if |
|---|---|---|
| E3.C1 | E3a 0% deterministic: abstention rate | = 1.0 |
| E3.C2 | E3a 25%/100%: min 95%-interval coverage among OK estimates | ≥ 0.90 |
| E3.C3 | E3b: min coverage across all reported cells | ≥ 0.90 |
| E3.C4 | E3b: abstention when n < min_shots | = 1.0 |
| E3.C5 | E3c: max false-confidence rate over r | ≤ 0.10 |
| E3.C6 | E3d(i): false-confidence rate | ≤ 0.10 |
| E3.C7 | E3d(ii): abstention rate | ≥ 0.50 |

E3.C6 and E3.C7 probe a known gap: v0.1 has no goodness-of-fit check, so
we expect both to fail. Recording that failure is the point; a
posterior-predictive misfit check is the planned fix and will be evaluated
as a new run.
