# Hardware addendum | Experiment P: first physical-QPU test

**Quantum Noise Profiler, 2026-10-13/14 UTC · Christopher Woodyard · Vers3Dynamics**

**Status:** Recorded, preregistered *assumption check* on one IBM Quantum processor, not a validation of drift-detection accuracy, a discovery of a noise mechanism, or evidence of deployment readiness. This addendum follows the 10-page **simulation-only** [v0.3 technical report](qnp-technical-report.pdf), which is preserved unchanged as a historical snapshot.

## Executive finding

On `ibm_fez`, a 14-job measurement sequence with 296,000 shots consumed approximately 130 seconds of actual QPU time across nearly two hours of elapsed observation. The two predetermined checks disagreed:

| Preregistered criterion | Observation | Decision |
|---|---|---|
| P.C1: at most 1 of 10 qubit/preparation readout series rejects one constant binomial rate over 12 batches (G-test, α = 0.01) | **6 of 10** rejected | **FAIL** |
| P.C2: at most 1 of 10 T1 sweeps detects nonhomogeneous interleaved ground references (α = 0.01) | **0 of 10** rejected | PASS |

Failing P.C1 is a useful *negative model-check result*: over the observed window, these probe counts are inconsistent with the assumed fixed readout-error rate. P.C2 means this pilot **did not detect** within-sweep readout drift, not that all future sweeps or devices are stable.

**No detection-accuracy claim can be made** because no independent truth label for hardware degradation was acquired. IBM's calibration estimates are not independent ground truth.

## Provenance

- Preregistered protocol: [`experiments/V03_PREREGISTRATION.md`](../../experiments/V03_PREREGISTRATION.md), `5, committed before the run.
- Recorded complete run: `V03_P_pilot-20261013T234830-220ff3`, executed from clean commit `1ea9556`.
- Readable results: [`results/V03_SUMMARY.md`](../../results/V03_SUMMARY.md) and [`results/V03_TABLES.md`](../../results/V03_TABLES.md).
- Full raw counts, timestamps and snapshots: [`results/raw/V03_P_pilot-20261013T234830-220ff3.jsonl.gz`](../../results/raw/V03_P_pilot-20261013T234830-220ff3.jsonl.gz); audited using `python tools/verify_results.py` and `python tools/check_provenance.py`.
- Five selected physical qubits: **54, 108, 127, 59, 87**. They were selected by the preregistered vendor-readout-error quantile rule, not after viewing their measured behavior.
- Twelve probe batches were spaced at a median **10.009 minutes**; every job had an IBM-reported execution timestamp.
- Two preceding `ibm_kingston` launches were interrupted and excluded from confirmatory evidence, consuming another **170 s** of QPU time. Their job IDs and reasons are preserved in [`results/V03_DEVIATIONS.md`](../../results/V03_DEVIATIONS.md).

## Readout fluctuations that require explanation

Qubit 108, `p(0|1)`: the fraction of outcomes reported as 0 when the qubit was prepared in 1. Rates were measured using **4,000 shots per probe batch**:

| Batch | Error rate | Batch | Error rate |
|---:|---:|---:|---:|
| 0 | 1.000% | 6 | 2.775% |
| 1 | 0.925% | 7 | 2.975% |
| 2 | 0.800% | 8 | 1.550% |
| 3 | 0.975% | 9 | 1.175% |
| 4 | 0.975% | 10 | 1.550% |
| 5 | 1.100% | 11 | 1.450% |

This series rejects a constant binomial rate very strongly (G = 138.89 on 11 degrees of freedom; p ≈ 2.74×10⁻²⁴). But the G-test **cannot tell whether the excess variation comes from time-varying true readout error, correlated samples, preparation effects, or another systematic process**. The design provides no independent diagnosis of the mechanism.

The six rejecting series had G/degrees-of-freedom between **2.3 and 12.6**. A simple fixed-rate sampling model can therefore understate expected variations and make some alerts overconfident.

## Post hoc cross-series dependence check

The [frozen preregistration](../../experiments/V03_PREREGISTRATION.md#5-experiment-p--hardware-pilot-ibm-quantum)
uses about 0.004 as the null probability of at least two rejections among ten.
The binomial calculation assumes independent rejection indicators (and
marginal size 0.01 for equality). Independence was not established: the five
qubits shared each probe circuit. The threshold of at most one rejection and
both registered outcomes remain unchanged.

Under the complete constant-binomial-rate null, **if** each marginal G-test
has size at most 0.01, the expected number of rejections is at most 0.10
regardless of cross-series dependence. Markov's inequality therefore bounds
the probability of at least two rejections by 0.05, and of **at least the six
observed** by 0.0167. Independently of that count bound, [Holm's
procedure](https://www.jstor.org/stable/4615733) at family alpha 0.05 rejects
the same six series when applied to the stored marginal p-values. The two
calculations interrogate the same pilot, not separate evidence.

Both checks depend on calibration of the marginal tests. The p-values use
an asymptotic chi-square reference, and neither adjustment validates that
reference with sparse counts, establishes within-series independence, or
identifies a physical mechanism. This is exploratory sensitivity analysis,
not a new confirmatory result. Reproduce it from the archived run index
without a QPU:

```sh
python tools/pilot_diagnostics.py --run-id V03_P_pilot-20261013T234830-220ff3
```

## Additional observations, not pass/fail criteria

- **T1 measurement gate:** 7 of 10 estimates accepted, 3 abstained or rejected due to insufficient evidence or model misspecification.
- **Change between accepted sweeps:** qubit 87 changed from 167 µs [150, 189] to 94 µs [88, 101]; qubit 54 from 162 µs [151, 174] to 142 µs [134, 150]. These are estimates, not a causal attribution.
- **Vendor comparison:** 2 of the 7 accepted T1 intervals included the vendor estimate. Only 4 of the 10 pooled readout intervals included their corresponding vendor readout rate. Vendor calibrations did not update during the observation.
- **Profiler output:** five drift warnings were emitted for qubit 108, all after the readout excursion. Whether these were appropriate warnings requires independent reference data.

These observations must not be converted into claims that the profiler is a validated detector, that QPU quality was independently measured, or that the physical source of noise is known.

## Engineering response and next scientific test

1. **Crash resilience:** the pilot runner now journals the job ID immediately after submission, then saves its counts and timestamps once the job completes. Each run uses its own local private directory. Interrupted attempts remain partial, cannot silently become complete runs and are never automatically resumed or stitched together. Details: [checkpoint protocol](../../docs/REPRODUCIBILITY.md).
2. **Descriptive analysis:** run `python tools/pilot_diagnostics.py` for variance-to-binomial ratios, descriptive lag-one correlations and the original G-test results. This is explicitly **exploratory** and is not an independent replication.
3. **Prespecified independent follow-up:** [`experiments/P04_FOLLOWUP_PLAN.md`](../../experiments/P04_FOLLOWUP_PLAN.md) defines a future holdout hardware design, robust alternatives and comparisons to calibrated CUSUM. It is a **plan**, with no P04 hardware results.
4. **No performance retuning from this pilot:** preserve the recorded v0.3 configurations. Any new fluctuation-aware model must report the assumptions under which its error guarantees actually apply, calibrate using separate data, and be evaluated on held-out hardware sessions.

## Boundaries

The result covers **one device, five qubits, 12 batches over approximately two hours**. Temporal variability may violate the drift channel's assumptions, but independent batch dependence was not separately tested. No multi-day data, second device, held-out intervention trial, or proof of better operational outcomes exists yet. The 40/40 v0.3 simulation criteria remain simulation results and do not override the hardware finding.
