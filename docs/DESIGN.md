# Design (Phase 2)

> **v0.2 note.** The drift, threshold and forecast rules below are the v0.1 design, kept for the record and available as `LegacyDriftConfig`. The v0.2 engine is described in `docs/SEQUENTIAL_METHODS.md` and `paper/paper.md` §3–5.

## Principle
Every number carries **how we know it**. Where the data can't support a
number, the profiler says so (`status = insufficient_evidence`, `value = None`,
`reason = ...`). It does not fill the gap with a guess.

## Three provenance modes

| Mode | Source | Metrics | Uncertainty |
|---|---|---|---|
| **observed** | vendor calibration (`Target`, IBM `properties()`, later Rigetti ISA) | T1, T2, readout error, gate error | none unless the vendor reports one (Qiskit doesn't; we never invent one) |
| **inferred** | ordinary workload results | `effective_flip_rate` per (qubit, context) | Beta posterior (Jeffreys prior), 95% equal-tailed |
| **measured** | dedicated sequences: T1 (X–delay–measure), Hahn echo | T1, T2 (echo) | grid posterior; A and B (SPAM) marginalized out |

Series are keyed by `(metric, qubits, context, provenance)`. Observed and
measured T1 are **never pooled**: they come from different procedures at
different times.

## Inferred mode
1. Analyze the executed circuit (ISA, physical qubits). Reject mid-circuit
   measurement, reset, control flow, unbound parameters, and circuits wider
   than `max_sim_qubits` (default 16). The reason is attached to every
   affected qubit.
2. Simulate the unitary part noiselessly over active qubits only. A measured
   qubit with P(1) < 10⁻⁹ or > 1 − 10⁻⁹ has a deterministic ideal bit.
3. Context = `ideal=<bit>|1q<bucket>|2q<bucket>` (gate counts on that qubit,
   bucketed). Rates are compared only within a context. The ideal bit is part
   of the context because P(0|1) ≠ P(1|0) (relaxation during readout).
4. Pool flips/shots per (qubit, context) per batch. Below `min_shots`
   (default 200) → insufficient evidence.

Assumptions travel with every estimate (`Estimate.assumptions`).

## Measured mode
P(t) = A·e^(−t/τ) + B, binomial likelihood, on a grid of 400 τ × 41 A × 41 B.
The prior is log-uniform in τ over [min delay / 20, 20 × max delay], uniform
in A and B. If more than 5% of posterior mass sits on the outer 2% of the τ
grid, the delays don't bracket τ, and the result is **insufficient evidence**
rather than an interval clipped by the prior.

Known gap (preregistered as E3.C6/C7): no goodness-of-fit check yet, so
non-exponential data (TLS fluctuations, two-component decay) can produce a
confident but wrong T1. Planned fix: a posterior-predictive check of the
binomial deviance → insufficient evidence on misfit.

## Drift, threshold, forecast (`drift.py`)
Three evidence paths, chosen per series:
- **binomial** (inferred flip rates): exact Beta posteriors. Drift fires when
  P(p_recent > 1.1 · p_baseline) ≥ 0.95. The minimum effect size stops huge
  shot counts from turning trivial changes into alerts.
- **interval** (measured T1/T2): Gaussian in log space from the credible
  interval, so the decay-time intervals are allowed to be asymmetric.
- **point** (observed, no uncertainty): the baseline's own scatter defines a
  Student-t posterior predictive. Alert when the new value is in the 5% tail
  *and* ≥ 10% worse.

Threshold: CRITICAL when P(beyond threshold) ≥ 0.95 (for point series, when
the value is beyond the threshold; the message notes the missing uncertainty).

Forecast: Bayesian linear regression (noise inflated by reduced χ² when the
scatter exceeds reported errors). Alert when P(trend worsening) ≥ 0.9 and
P(cross within horizon) ≥ 0.5, where horizon = min(24 h, span of observed
data). The cap was added after a unit test caught 15–19 h projections made
from 2 h of stable data.

`mark_recalibrated(ts, qubits)` restarts baselines after recalibration.

## Alerts
`Alert(level, kind, metric, qubits, provenance, context, message, details)`.
`qnp.alerts.to_json()` produces JSON for control systems;
`format_text()` produces text for humans. Webhook/EPICS output is a Phase 3
item (pyepics PV write or HTTP POST of the same JSON).

## Storage
Append-only SQLite (`EstimateStore`), one JSON body per estimate, plus a
recalibration table. Insufficient-evidence estimates are stored as well, so
`Profiler.snapshot()` shows where knowledge is missing.

## Deliberately not done (yet)
- pyQuil adapter (needs a real ISA payload to test against); Cirq OBSERVED
  (needs `cirq_google`).
- Readout-only inference from arbitrary workloads. It isn't identifiable.
  Users who want a readout number should use OBSERVED or add basis-state
  probes, which the inferred mode picks up automatically as context `1q<=0`/`<=1`.
- Online change-point models (BOCPD). The two-window comparison is simpler to
  audit; E2 measures whether it is good enough.
