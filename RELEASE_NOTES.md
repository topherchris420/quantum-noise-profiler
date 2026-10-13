# Release notes

## v0.2.0 (development, not yet released)

Research release. All validation is in simulation; nothing has been run on
quantum hardware.

### Evidence handling
- v0.1 baseline preserved: commit `0e8e41d` (annotated tag `v0.1-baseline`
  created locally; this session's git access could not push tags, so the tag
  must be pushed by a maintainer: `git push origin v0.1-baseline`). Every recorded artifact is hashed in
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

### Results (simulation only)
53 of 62 preregistered checks passed (`results/V02_SUMMARY.md`). Run-level
false-alert probability on stable qubits fell from 0.43–0.88 (v0.1) to at
most 0.010 (anytime-valid) / 0.070 (calibrated). Failures: 10% steps are not
detected within 5 batches (all methods); correlated readout drift during a
T1 sweep passes the model checks (28.5% false confidence); idle-time and
extra-2q-gate workload changes trip the absolute threshold on unchanged
hardware.

### Fixed after the study
- `qnp.sim.aer_noise_model` omitted thermal relaxation during two-qubit
  gates when two-qubit depolarizing was zero (no recorded result affected).
- CI workflow was invalid before commit `c0f7d6d` (runner context in
  job-level env): no CI job had run until then.
- From code review (none affects a recorded result; every experiment used one
  provenance and the default shares):
  - the session budget now also divides by the number of provenances monitored
    per (qubit, metric) (`ErrorBudget.n_provenances`); before, observed and
    measured T1 of the same qubit each received the full per-series alpha;
  - a zero channel share disables that channel instead of raising
    `ZeroDivisionError`;
  - hardware planning rejects non-integer physical qubit identifiers (`1.9`,
    `True`, `"1"`) instead of coercing them to a possibly different qubit;
  - a series with no variation (a vendor value re-read unchanged) abstains
    with `NO_VARIATION` instead of crashing the forecast;
  - the CI smoke job's provenance check was non-fatal (`|| true`) and masked
    a raw-path schema failure; raw paths are now logical
    (`results/raw/<file>`) and the check is enforced.

### Release blockers
1. No real-hardware validation.
2. Absolute thresholds on workload-dependent effective flip rates misfire
   (Experiment E5/E6); needs a design change and a new preregistered test.
3. Correlated measurement drift during decay sweeps is not detected (D11).
4. The `v0.1-baseline` tag is not yet on the remote.
5. The full study ran in one computing environment only.

## v0.1.0 (research baseline, 2026-10-12)
Provenance-aware estimates (observed / inferred / measured), Bayesian
drift/threshold/forecast alerts, three preregistered simulator experiments:
8 of 14 criteria passed.
