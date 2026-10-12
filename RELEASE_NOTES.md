# Release notes

## v0.2.0 (development, not yet released)

Research release. All validation is in simulation; nothing has been run on
quantum hardware.

### Evidence handling
- v0.1 baseline preserved (`v0.1-baseline` = commit `0e8e41d`; see
  `docs/V01_AUDIT.md` on the tag push). Every recorded artifact is hashed in
  `results/MANIFEST.sha256`; `tools/verify_results.py` recomputes every summary
  from raw data; `tools/check_provenance.py` validates schema, clean source
  trees and seed blocks.
- E2 comparison corrected by re-analysis of the recorded data
  (`results/E2_CORRECTION.md`); the original entry is unchanged.
- v0.2 study preregistered before any calibration or confirmatory run
  (`experiments/V02_PREREGISTRATION.md`); deviations in `results/V02_DEVIATIONS.md`.

### Monitoring engine (`qnp.drift`, `qnp.sequential`, `qnp.forecast`)
- Anytime-valid e-processes replace per-check posterior bars; explicit
  session error budget (`ErrorBudget`) across channels, qubits and metrics.
- Every alert states its e-value, threshold, per-series α and the kind of
  guarantee (`exact`, `bayesian_marginal`, `gaussian_approx`, `plug_in`,
  `+calibrated`).
- Drift alerts require evidence, effect size (≥ 10% relative change) and
  persistence (≥ 2 batches).
- Forecast statuses `VALID_FORECAST`, `INSUFFICIENT_EVIDENCE`,
  `MODEL_MISSPECIFICATION`, `INSUFFICIENT_HISTORY`, `UNSTABLE_TREND`,
  `UNSUPPORTED_HORIZON` with machine-readable reasons; predictive
  crossing-time intervals including future process variation.
- Optional empirically calibrated thresholds (`DriftConfig.log_e_offset`).
- The v0.1 rules remain available, frozen, as `LegacyDriftConfig`.

### Measurement (`qnp.stats`, `qnp.measured`)
- Decay fits check delay-range coverage, binomial deviance,
  posterior-predictive deviance and residual runs before reporting a value.
  New status `MODEL_MISSPECIFICATION`. A bi-exponential model is scored for
  diagnosis only, never substituted.

### Simulation, adapters, hardware
- `qnp.sim`: thermal relaxation, amplitude damping, dephasing,
  gate-dependent depolarizing, asymmetric readout, schedules for drift,
  correlated disturbances, TLS switching, missing data, irregular timing;
  verified against closed forms, an independent density-matrix reference,
  Cirq and Stim.
- Exact circuit contexts (gate composition and idle time) in both adapters;
  explicit errors on malformed results, inconsistent qubit identifiers and
  naive timestamps.
- `qnp.hardware`: read-only, budgeted, dry-run-by-default IBM Runtime
  pathway with per-property calibration timestamps.

### Infrastructure
- GitHub Actions: lint, format, mypy, tests on 3 OS × 4 Python versions,
  lowest-dependency job, build and clean install, experiment smoke tests,
  result integrity.

### Results
See `results/V02_SUMMARY.md` (filled in from recorded runs only).

### Known limitations and release blockers
See `results/V02_SUMMARY.md` § Limitations and `paper/paper.md` § 8.

## v0.1.0 (research baseline, 2026-10-12)
Provenance-aware estimates (observed / inferred / measured), Bayesian
drift/threshold/forecast alerts, three preregistered simulator experiments:
8 of 14 criteria passed.
