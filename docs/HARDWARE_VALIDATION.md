# IBM Quantum validation pathway (design; not yet executed)

No real-device job has been run for this project. Everything in
`results/` is simulation. This document describes how a first hardware
study would be run with `qnp.hardware`, and what such a study could and
could not establish.

## Invitation to collaborate

We welcome independent replication of the recorded simulations and contact
from quantum-hardware researchers who could help evaluate an **unstarted,
proposed 30-day read-only observation pilot**. This is an invitation for
feasibility discussion, **not** an announcement of a hardware partnership,
device access, or operational readiness. Please
[open a repository issue](https://github.com/topherchris420/quantum-noise-profiler/issues/new)
with a description of the data source and permitted use, **not** raw
restricted data, credentials, tokens, serial numbers, or provider account
details. Any access or sharing must comply with the data owner's policies
and authorization requirements.

Useful information for scoping a pilot:

- Hardware family/backend type (only if public or approved for release),
  available qubit count, and the observation period.
- Which calibration estimates can be exported: T1, T2, asymmetric readout
  errors, two-qubit errors; their physical units and **per-property**
  calibration timestamps, rather than just the collection timestamp.
- Whether uncertainties, method details, or an **independent reference**
  measurement exist, and how they were acquired.
- Data permissions and restrictions on publication, retention and sharing;
  a sanitized schema or synthetic example is enough to begin the discussion.

Participation is voluntary; no submission of sensitive or nonpublic
information is requested.

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

## Proposed study: two distinct phases (neither executed)

### Phase A — read-only observation, 30 days

Collect existing vendor calibration records or authorized snapshots without
submitting jobs or using QPU time. The initial design is hourly
`HardwareSession.snapshot()` on up to 5 selected qubits (subject to
actual provider access and availability). Capture OBSERVED T1, T2, readout
P(1|0), P(0|1), and two-qubit error with each property's calibration
timestamp. Snapshots are read-only but may repeat stale vendor estimates;
**hourly polling does not imply hourly recalibration or independent
measurements**. Approved historical exports may be used instead of direct
account access.

Before inspecting outcomes, agree on a prospective analysis plan specifying
the monitored family and contexts, data exclusions, time windows, baseline
and alert rules, missing-data handling, independent-replication procedure,
and which outputs may be shared. Keep any tuning data separate from
held-out evaluation; record changes to the plan rather than retroactively
calling them preregistered. No such real-hardware plan or pilot results
are claimed here.

**Phase A can test:** ingestion/provenance integrity, missingness,
timestamp accuracy, alert consistency across repeated snapshots, and
agreement with subsequently reported vendor calibration changes.
It cannot independently validate the accuracy of error estimates or infer
unobserved between-calibration drift. A lack of changes in stale vendor
records is not proof of qubit stability.

### Phase B — optional, separately authorized active characterization

Only if collaborators and device operators separately approve experiments,
review access rights and costs, and explicitly authorize each submission:

1. **Measured T1/T2:** `plan_characterization(backend, "t1" |
   "t2_echo", qubits, delays, shots=1000)` with 15 delays up to
   3·T1(vendor). Example: 5 qubits × 2 sequences × 15 circuits × 1000
   shots = 150,000 shots **per session**, before provider-specific limits,
   queue times or additional controls. The dry-run plan must first be
   inspected for estimated QPU time and cost.
2. **Inferred probes:** `plan_characterization(..., "probe")` and optional
   mirror circuits of 2–3 depths, using exact contexts and a fixed probe
   workload so that workload changes are not confused with device changes.
3. **Independent reference:** if possible, collect dense characterization
   on the same qubits, with a defined reference measurement and analysis
   window that do not reuse the monitor's own estimate as truth.
4. **Evaluation:** declare the monitoring family before analysis
   (`ErrorBudget(n_qubits=5, n_metrics=…)` is an example, not a validated
   real-hardware setting); evaluate session-level false alerts, timely
   detection, false confidence in accepted T1/T2 fits, forecast coverage,
   abstention, workload robustness, and uncertainty intervals against
   blinded/independent reference where available. Publish negative and
   inconclusive outcomes subject to data permissions.

These active experiments are **not read-only** and are **not included**
in the 30-day observation-only invitation. `qnp.hardware` defaults to
refusing submissions and requires explicit authorization and budget gates.

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
