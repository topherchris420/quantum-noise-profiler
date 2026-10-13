# IBM Quantum validation pathway (design; not yet executed)

No real-device job has been run for this project. Everything in
`results/` is simulation. This document describes how a first hardware
study would be run with `qnp.hardware`, and what such a study could and
could not establish.

## Safety properties of `qnp.hardware`

| Property | How it is enforced |
|---|---|
| Read-only by default | `HardwareSession(dry_run=True, allow_submission=False, budget=JobBudget())` — a zero budget |
| No accidental submission | `submit()` needs `dry_run=False`, `allow_submission=True` **and** `authorize=True` per plan; otherwise `SubmissionRefused` |
| Bounded cost | `JobBudget(max_jobs, max_total_shots, max_circuits_per_job, max_estimated_qpu_seconds)`, checked cumulatively before every submission (`BudgetExceeded`) |
| No recalibration | Qiskit Runtime exposes no recalibration call and the module has none; `Profiler.mark_recalibrated` only *records* that the vendor recalibrated |
| Provenance | each submission stores a backend snapshot (name, version, `last_update_date`, per-property calibration timestamps, physical qubits, software versions), the plan summary, the job id and `job.metrics()` timestamps when the service reports them |

Tested in `tests/test_hardware.py` with `qiskit_ibm_runtime.fake_provider`
backends (local simulation, no account, no network).

## Verified behaviour (qiskit-ibm-runtime 0.50.0, fake backends)

- `backend.properties().qubit_property(q)` returns each value **with its own
  calibration datetime** (T1, T2, readout error, `prob_meas1_prep0`,
  `prob_meas0_prep1`). On `FakeTorino` qubit 0, T1 was calibrated on
  2025-01-29 while its readout error was calibrated on 2025-02-25. v0.1's
  `observe_backend` stamped every value with `last_update_date`, which hides
  this. `observe_ibm_backend` uses the per-property dates and records the
  asymmetric readout probabilities as separate contexts.
- Fake backends are snapshots: their "calibration" never changes and is not
  current device data.
- Live-service behaviour (`properties(datetime=...)` history, `job.metrics()`
  timestamp fields, Open-plan quotas) is **unverified**: no IBM account was
  used.

## Proposed first study (requires an account and an explicit budget)

1. **Observed series, read-only, 30 days.** Hourly `HardwareSession.snapshot()`
   of 5 chosen qubits. Cost: zero QPU time. Output: OBSERVED T1, T2,
   readout P(1|0), P(0|1), 2q error, each with its calibration timestamp.
2. **Measured T1/T2, twice daily.** `plan_characterization(backend, "t1" |
   "t2_echo", qubits, delays, shots=1000)` with 15 delays to 3·T1(vendor).
   Example budget: 5 qubits × 2 sequences × 15 circuits × 1000 shots =
   150 000 shots per session. Run dry first; the plan reports an estimated
   QPU time to compare with the account's quota.
3. **Inferred probes, hourly.** `plan_characterization(..., "probe")` plus
   mirror circuits of 2–3 depths, analysed with exact contexts.
4. **Analysis.** The same v0.2 engine and budget as in simulation, with the
   family declared up front (`ErrorBudget(n_qubits=5, n_metrics=…)`).

## What vendor calibration values are, and are not

They are point estimates from the vendor's own procedure, with unreported
fit model, uncertainty and acquisition schedule. They may be hours to weeks
old at job time (per-property dates above), are reported after the vendor's
own filtering, and are refreshed on the vendor's calibration cycle, not the
user's workload. Treating them as ground truth would make "agreement with
vendor values" circular for anything the vendor also measures, and would
miss fluctuations between calibration cycles (two-level-system defects
change T1 on minute-to-hour scales). A hardware study can therefore test
**consistency** (do measured intervals contain vendor values more often than
chance? do detected changes precede vendor-reported changes?) but cannot
establish detection accuracy without an independent reference, such as
dense dedicated characterization on the same qubits.

## What a hardware study would still not show

- Generalisation beyond the chosen backend, qubits and weeks.
- That the binomial and Gaussian models hold: real batches can be
  correlated (drifts within a job, leakage, crosstalk), which the e-process
  guarantees assume away.
- Operational value (calibration time saved): that needs an intervention
  study, not monitoring alone.
