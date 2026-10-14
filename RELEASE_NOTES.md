# Release notes

## Unreleased: post-P research integrity and safety hardening

- **Research record:** synchronized README, paper and `CITATION.cff` with
  the complete IBM Fez pilot. Added `docs/report/HARDWARE_ADDENDUM.md`.
  The ten-page PDF is intentionally preserved as the original simulation-only
  snapshot rather than retroactively altering an earlier report.
- **No manufactured success:** P.C1 remains a failed constant-rate assumption
  (6/10 rejecting), P.C2 a non-rejection (0/10), and hardware warning
  accuracy unestablished. The 40/40 simulation outcomes are unchanged.
- **Crash-safe QPU checkpoints:** private, atomic and fsynced per-job
  submission IDs and measurements; no automatic resume or unexpected
  resubmission. Added interruption tests.
- **Exploration only:** read-only pilot variability diagnostics and a written
  proposal for independent P04 hardware validation and fair CUSUM baselines;
  no thresholds silently recalibrated and no new hardware jobs submitted.

## v0.3.0 (development, not yet released)

Research release addressing three of the v0.2 release blockers. The new
methods were tested in a new preregistered simulation study
(`experiments/V03_PREREGISTRATION.md`, committed and pushed before any
confirmatory run; results in `results/V03_SUMMARY.md`). A short QPU
experiment (the hardware pilot, Experiment P; 14 jobs) ran on IBM `ibm_fez`
on 2026-10-13/14.

### Results (simulation; 40 of 40 preregistered criteria passed)
- **G, workload changes on unchanged hardware.** Runs with a false alert
  fell from 1.00 to 0.02 (2 µs idle before measurement) and from 0.43 to
  0.05 (extra two-qubit gates). The threshold channel raised no false alert
  in 700 runs. A readout ramp was still caught before the crossing in every
  run, 10 min later in the median than v0.2.
- **H, T1 fits under slow readout drift.** Confidently wrong T1 fell from
  0.255 to 0.005 (v0.2 D11 conditions) and from 0.370 to 0.000 (linear
  drift). Valid fits rejected: 2.5–4%, against 1.5–2% before.
- **I, operational value (closed-loop simulation, illustrative rates).**
  - **Failed jobs:** recalibrating on v0.3 warnings cut jobs run on a
    degraded qubit from 13–20% (daily schedule alone) to at most 0.31%.
    That is 4.7–5.4 points below fixed schedules of equal cost.
  - **Calibrations:** warnings alone did not use fewer calibrations than
    the daily schedule unless degradation was rare or absent.
  - **Baseline:** a calibrated CUSUM on the same probes did as well.
- **P, hardware pilot (`ibm_fez`, 5 qubits, 2 h).**
  - **P.C2 passed:** no readout drift within a job (0 of 10 sweeps).
  - **P.C1 failed:** readout error fluctuated between batches beyond
    binomial noise (6 of 10 series; G/dof up to 12.6). On that device the
    drift channel's constant-rate null does not hold.
  - Two earlier launches were interrupted and are listed, unused, in
    `results/V03_DEVIATIONS.md`.

### Workload-safe thresholds (`qnp.measured`, adapters, `qnp.drift`)
- **Readout probes.** Prepare-and-measure circuits (`readout_probe_circuits`;
  any circuit of only X gates and terminal measurements in which no qubit is
  held waiting for another qubit's measurement) are recognised by their
  structure in Qiskit and Cirq results and become MEASURED
  `readout_error` estimates with contexts `p(1|0)` / `p(0|1)` and binomial
  counts.
- **Thresholds apply to hardware properties only.** `DriftConfig.thresholds`
  defaults to `{readout_error: 0.05}`. Workload effective flip rates
  (`qnp.drift.WORKLOAD_DEPENDENT`) get no absolute threshold or crossing
  forecast by default and are monitored for relative change; group reports
  say why. `DriftConfig(thresholds=dict(V02_THRESHOLDS))` restores v0.2.
- `Profiler.ingest_qiskit` / `ingest_cirq` now call
  `estimates_from_results`: probes are routed to MEASURED estimates and
  contexts default to `exact`. `readout_probes="off", context_mode="bucket"`
  is the v0.2 behaviour; `infer_from_results` is unchanged.

### Decay sweeps robust to measurement drift (`qnp.measured`, `qnp.stats`)
- `decay_sweep_plan`: delays in random acquisition order with 5 ground
  references (prepare |0>, measure) spread over the acquisition;
  `decay_plan_circuits`, `estimate_t1_from_plan`, `estimate_t2_echo_from_plan`.
- New check `READOUT_DRIFT` (G-test of reference homogeneity, alpha 0.01) ->
  `MODEL_MISSPECIFICATION`. The runs test of residuals in acquisition order
  is reported (`acquisition_runs_test_p`) but is not a rejection rule. Fits
  without acquisition information say that slow drift cannot be detected
  (`order_note`).
- `run_t1`, `run_t2_echo` and hardware plans use the new design by default;
  `decay_sweep_plan(delays, **V02_SWEEP)` is the v0.2 design.

### Hardware pathway (`qnp.hardware`, `experiments/run_v03.py pilot`)
- Per-qubit sweep delays; parallel readout probes; sweep delays rounded to
  the backend's timing grid (`align_delays`; IBM rejects off-grid delays);
  `estimates_from_sweep_job`.
- A preregistered pilot (Experiment P): dry run by default, 14 jobs, budget
  enforced; rehearsed on `FakeTorino` and `FakeManilaV2` (local simulation),
  which exposed the timing-grid defect and an unphysical-vendor-value case,
  both fixed before preregistration.

### Study infrastructure
- `experiments/run_v03.py` (G, H, I, pilot), `experiments/v03/` (generators,
  closed-loop operational simulator, analysis), `tools/make_v03_tables.py`,
  `tools/make_v03_figures.py`; `tools/verify_results.py` and
  `tools/check_provenance.py` cover v0.3 entries (seed blocks, protocol,
  calibration order, rehearsals never in `results/`); CI runs v0.3 smoke
  experiments and a fake-backend pilot rehearsal.
- The v0.1 and v0.2 pipelines pin their original behaviour; recorded v0.2
  runs (Experiments C and E) re-run bit-identically with the v0.3 code.

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
