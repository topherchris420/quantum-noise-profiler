# v0.2 development notes (not evidence)

Everything here used **development seeds below 20 000** and the surrogate
(numpy) readout-only pipeline. It informed design choices made *before*
`experiments/V02_PREREGISTRATION.md` was committed. None of it is evidence
for or against any v0.2 hypothesis, and none of these seeds are reused for
calibration or confirmatory testing.

## Sweep of 2026-10-12 (80 runs per condition, 48 batches, 2 qubits, 2000 shots × 2 deterministic circuits)

Run-level false-alert rate (any alert on either qubit, whole run) of the
v0.2 engine with every e-value threshold divided by exp(c):

| condition | c=0 | c=1 | c=2 | c=2.5 | c=3 | c=3.5 | c=4 |
|---|---|---|---|---|---|---|---|
| stable 0.5% | 0.00 | 0.00 | 0.05 | 0.05 | 0.11 | 0.42 | 1.00 |
| stable 2% | 0.00 | 0.00 | 0.03 | 0.06 | 0.10 | 0.40 | 1.00 |
| q0 at 4.5%, q1 at 2% | 0.01 | 0.04 | 0.09 | 0.14 | 0.23 | 0.36 | 1.00 |
| q0 at 4.9%, q1 at 2% | 0.00 | 0.00 | 0.03 | 0.06 | 0.14 | 0.29 | 1.00 |

Detection (q0, 2% base):

| condition | c=0 | c=2 | c=3 |
|---|---|---|---|
| ramp 2→6%: early (before true crossing) / median lead | 1.00 / 232 min | 1.00 / 242 min | 1.00 / 262 min |
| ×1.5 step: detected / median delay (batches) | 1.00 / 1 | 1.00 / 1 | 1.00 / 1 |
| ×1.2 step | 0.99 / 7 | 1.00 / 4 | 1.00 / 3 |
| ×1.1 step | 0.23 / 14.5 | 0.51 / 12 | 0.72 / 8.5 |

Observations that shaped the protocol:

1. With the theoretical thresholds (c = 0) the engine is very conservative
   (false-alert rate ≈ 0–1% against a 10% budget). An empirically
   calibrated variant is therefore worth testing; it is defined in the
   preregistration with its own calibration seeds.
2. At c = 4 every condition alarms immediately: the offset exceeds the
   smallest nominal threshold (log 40 = 3.69 for the drift channel), so the
   calibration grid is capped at c = 3.5.
3. At 4.5% the forecast channel dominates false alerts once c ≥ 2.
4. Conventional comparators with reference windows estimated from the
   first 10 batches need much wider limits than textbook values: a CUSUM
   (allowance 0.5σ) with h = 8σ still alarmed in 14% of stable runs, and a
   3σ Shewhart chart in 15–19%. Their calibration grids are widened
   accordingly (k up to 5σ, h up to 40σ).
