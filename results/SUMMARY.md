# Results summary: v0.1 preregistered simulator experiments

**Overall: 8 of 14 preregistered criteria passed, 6 failed.** Every run is
in `runs.jsonl`; raw per-seed/per-rep data is in `raw/`. All three runs used
code identical to the preregistration commit `4ba70c2`. `src/` and
`experiments/` are unchanged since then, and every run recorded
`git_dirty = false`. Criteria are defined in
[`experiments/PREREGISTRATION.md`](../experiments/PREREGISTRATION.md).

| Run | Criterion | Observed | Required | |
|---|---|---|---|---|
| E1 | C1 alert before true 5% crossing | 50/50 seeds (1.00) | ≥ 0.80 | ✅ |
| E1 | C2 median lead over naive threshold | +170 min (192 vs 22) | ≥ 30 min | ✅ |
| E1 | C3 control runs with any q0 alert | 0.62 | ≤ 0.10 | ❌ |
| E2 | C1 ×1.5 step detected within 6 batches | 1.00 | ≥ 0.90 | ✅ |
| E2 | C2 ×1.2 step detected within 24 batches | 0.96 | ≥ 0.50 | ✅ |
| E2 | C3 runs with any false WARNING/CRITICAL | 0.37 | ≤ 0.10 | ❌ |
| E2 | C4 spec claim: ×1.1 within 20 circuits | 0.20 | ≥ 0.80 | ❌ (predicted) |
| E3 | C1 no deterministic qubits → abstain | 1.00 | = 1.0 | ✅ |
| E3 | C2 flip-rate coverage, real workloads | 0.925 (min) | ≥ 0.90 | ✅ |
| E3 | C3 flip-rate coverage, all reported cells | 0.939 (min) | ≥ 0.90 | ✅ |
| E3 | C4 abstain below min_shots | 1.00 | = 1.0 | ✅ |
| E3 | C5 T1 false-confidence, any delay range | 0.12 (at 0.2·T1) | ≤ 0.10 | ❌ |
| E3 | C6 T1 false-confidence, fluctuating T1 | 0.72 | ≤ 0.10 | ❌ (predicted) |
| E3 | C7 abstain on bi-exponential decay | 0.00 | ≥ 0.50 | ❌ (predicted) |

## What the failures say

**1. Sequential false alarms (E1.C3, E2.C3) are the main defect.** The
profiler re-tests after every batch (48 checks per run), and each check
uses a per-check bar of P ≥ 0.95 (drift) or P ≥ 0.9 (trend). Small per-check
error rates accumulate over a run:

- E2: of 200 stable q1 series, 45 had a false WARNING (22.5%). In the no-step
  control, q0 had one in 16/50 runs. Before the step (24 checks), it was
  21/150 runs. False-alarm rates scale with the number of checks.
  First false alarms fall at batch 9–24 (interquartile).
- E1: control false alerts were almost all INFO forecasts (31/50 runs);
  WARNING/CRITICAL occurred in 3/50.
- Comparators: the naive per-batch threshold falsely alarmed in 92% of E1
  control runs. The Shewhart 3σ chart (per-check bar ≈ P ≥ 0.9987) had 7%
  false-alarm runs in E2, but it detected ×1.2 steps in 80% of runs vs 96% and
  ×1.1 steps in 40% vs 60%. **The profiler's detection-power advantage was
  bought partly with a looser per-check bar, so the power comparison isn't
  like-for-like yet.**

**2. Spec claim not supported (E2.C4).** "Detect 10% degradation within 20
circuits" held in 20% of runs at 2 deterministic circuits × 2000 shots per
batch. The median detection delay for ×1.1 was 7 batches (28 circuits), with
40% never detected in 24 batches. This is a statistical-power limit, not a
tuning issue. The claim needs roughly an order of magnitude more
deterministic shots per batch.

**3. Overconfident T1 when the model is wrong (E3.C6, C7).** With fluctuating
T1 or two-component decay the fit never abstained. It reported a narrow, wrong
T1 in 72% of fluctuating cases and ~62 µs for a 0.7·100 µs + 0.3·15 µs
mixture. This matches the preregistered expectation for v0.1, which has no
goodness-of-fit check. E3.C5 was a narrow miss: at 0.2·T1 delay span,
coverage was 0.88.

## What worked
- **The abstention logic is sound.** Unidentifiable workloads, thin shot
  counts and badly short T1 sweeps (≤ 0.05·T1: 399/400 abstained) all produced
  `insufficient_evidence`, not numbers.
- **Flip-rate credible intervals are calibrated** (0.925–0.987 coverage
  across 18 reported cells and real Aer workloads).
- **Early warning on gradual drift**: about 3 h ahead of the threshold crossing, in every seed.

## v0.2 plan (each fix is evaluated as a *new* run; these entries stay)
1. Calibrate alerting for continuous monitoring: choose per-check bars to hit
   a target run-level false-alarm rate (e.g. CUSUM / BOCPD with
   average-run-length calibration, or alpha-spending), and account for the
   multiple context series per qubit. Re-run E1/E2 against the same criteria.
2. Forecasts: require persistence across consecutive checks.
3. Decay fits: posterior-predictive goodness-of-fit check →
   `insufficient_evidence` on misfit. Re-run E3.
4. Compare against Shewhart at matched false-alarm rates.
