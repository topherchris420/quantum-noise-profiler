# IBM Quantum validation pathway

One real-device experiment has been run for this project: Experiment P, 14
jobs on `ibm_fez` on 2026-10-13/14 (`results/V03_SUMMARY.md` §1). Everything
else in `results/` is simulation. This document covers:

- an invitation to collaborate on a proposed 30-day, **read-only**
  observation study, which submits no jobs;
- the safety properties of `qnp.hardware`;
- **Experiment P**, a short QPU experiment preregistered with the v0.3 study
  (`experiments/V03_PREREGISTRATION.md` §5, where it is called the hardware
  pilot). It submits 14 jobs, so it is an active, separately authorized
  experiment, not part of the read-only observation study. It has run once:
  P.C2 passed and P.C1 failed;
- the proposed two-phase study, and what such studies could and could not
  establish.

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
| Delays the device accepts | sweep delays are rounded to the backend's timing grid (dt × lcm(granularity, pulse and acquire alignment); `align_delays`); the fit uses the rounded delays |
| Drift-visible sweeps | T1/T2 plans acquire delays in random order with 5 interleaved ground references (`decay_sweep_plan`), so readout drift inside a job is reported (`READOUT_DRIFT`) instead of bending the estimate |
| Provenance | each submission stores a backend snapshot (name, version, `last_update_date`, per-property calibration timestamps, physical qubits, software versions), the plan summary, the job id and `job.metrics()` timestamps when the service reports them |

Tested in `tests/test_hardware.py` and `tests/test_pilot.py` with
`qiskit_ibm_runtime.fake_provider` backends (local simulation, no account,
no network).

## Experiment P: a short QPU experiment (preregistered, separately authorized, run once)

Experiment P answers one question: do the assumptions the monitor rests on
hold on a real device over about two hours?

It is **not read-only**. It uses QPU time on the account it runs with, so
run it only on an account you are authorized to use, after inspecting the
dry run. It is a small instance of the active characterization described
under Phase B below, and is not part of the read-only observation
invitation. It submits 14 jobs:

1. a T1 sweep on 5 qubits (one job; per qubit 15 delays on [0, 3 × vendor
   T1] in random order plus 5 ground references, 1000 shots per circuit);
2. 12 readout-probe batches, one every 10 minutes (two circuits preparing all
   5 qubits in |0⟩ and in |1⟩, 4000 shots each);
3. a second T1 sweep; read-only snapshots before and after.

Qubits are chosen by a rule fixed in the preregistration (a spread of vendor
readout error among qubits with consistent vendor values). The budget is ≤ 14
jobs, ≤ 320 000 shots and ≤ 420 s estimated QPU time (the crude estimate
gives about 150 s); it is enforced before every job.

What it needs:

- an IBM Quantum Platform account with access to a QPU, and its API key and
  instance CRN as environment variables `QISKIT_IBM_TOKEN` and
  `QISKIT_IBM_INSTANCE` (or an account saved with
  `QiskitRuntimeService.save_account`). `python tools/ibm_connect.py` saves
  them (the key prompt does not echo) and lists the reachable QPUs and the
  remaining usage; it submits nothing;
- network access to `quantum.cloud.ibm.com` and `iam.cloud.ibm.com`
  (`qiskit-ibm-runtime` ≥ 0.40, channel `ibm_quantum_platform`).

```bash
pip install -e ".[dev]"
python experiments/run_v03.py pilot                          # dry run: qubits, plans, budget; sends nothing
python experiments/run_v03.py pilot --submit                 # runs it (least busy device), ~2 h wall clock
python experiments/run_v03.py pilot --backend ibm_xxx --submit
```

The run appends a `V03_P_pilot` entry to `results/runs.jsonl` with every
count, job id, timestamp and snapshot in its raw file;
`tools/verify_results.py` recomputes its summary. A rehearsal on a fake
backend tests the code path without hardware and must write elsewhere:

```bash
QNP_RESULTS_DIR=$(mktemp -d) python experiments/run_v03.py pilot --fake FakeManilaV2 --submit --interval 0
```

Rehearsals on `FakeTorino` and `FakeManilaV2` found two defects before any
hardware use, both fixed: backends with timing constraints reject delays off
their grid (now rounded), and fake-backend simulation rejects qubits whose
vendor T2 > 2·T1 (now excluded by the selection rule).

What Experiment P reports (`experiments/v03/pilot.py`):

| Check | Meaning if it fails |
|---|---|
| P.C1: ≤ 1 of 10 probe series (5 qubits × 2 preparations) rejects one constant rate across the 12 batches (G-test, α = 0.01) | batch-to-batch readout fluctuation exceeds binomial noise on this device: the drift channel's null does not hold there, and a fluctuation model (or a larger effect gate) is needed before deployment |
| P.C2: ≤ 1 of 10 T1 sweeps has disagreeing ground references (α = 0.01) | readout drifts within a job: sequential sweeps (v0.2 design) would give confidently wrong T1 there |

Also reported: T1 statuses and reason codes; whether vendor T1 lies in each
accepted fit's interval and vendor readout errors in the pooled probe
intervals (consistency only); the v0.3 engine's alerts on the probe series;
which execution timestamps the service reports; whether calibration history
(`properties(datetime=…)`) is available.

**Result** (`V03_P_pilot-20261013T234830-220ff3`):

- **Run:** `ibm_fez`, qubits 54, 108, 127, 59 and 87; 130 s of QPU time,
  against an estimate of 144 s.
- **P.C1 failed:** 6 of 10 probe series rejected one constant rate, with
  G/dof up to 12.6.
- **P.C2 passed:** 0 of 10 sweeps had disagreeing references.

Details are in `results/V03_SUMMARY.md` §1. Two earlier launches were
interrupted before completing; they are listed, unused, in
`results/V03_DEVIATIONS.md`. A long run should therefore be started in a
process that nothing else will stop: the record is written only at the end.

## Verified behaviour (qiskit-ibm-runtime 0.50.0, fake backends and the live service)

- `backend.properties().qubit_property(q)` returns each value **with its own
  calibration datetime** (T1, T2, readout error, `prob_meas1_prep0`,
  `prob_meas0_prep1`). On `FakeTorino` qubit 0, T1 was calibrated on
  2025-01-29 while its readout error was calibrated on 2025-02-25. v0.1's
  `observe_backend` stamped every value with `last_update_date`, which hides
  this. `observe_ibm_backend` uses the per-property dates and records the
  asymmetric readout probabilities as separate contexts — the same contexts
  as the MEASURED readout probes (`p(1|0)`, `p(0|1)`).
- Timing constraints differ by backend: `FakeManilaV2` 16-dt alignment,
  `FakeBrisbane` 8-dt, `FakeTorino` 1-dt.
- Fake backends are snapshots: their "calibration" never changes, and
  `properties(datetime=...)` is not supported on them.
- Live service (IBM Quantum Platform Open Plan, `ibm_fez`, 2026-10-13/14):
  - `properties(datetime=…)` returned calibration history.
  - `job.metrics()` reported execution timestamps for all 14 jobs.
  - The Open Plan's 600 s of QPU time is a rolling 28-day window, as reported
    by `service.usage()` (`usage_period`), not a calendar cycle.

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

### How Experiment P and v0.3 relate to the two phases

- **Experiment P** is a two-hour, 14-job check of the kind listed under
  Phase B, fixed in advance by the v0.3 preregistration. P.C1 (batch-to-batch
  readout fluctuation against binomial noise) indicates whether the 10%
  effect gate must grow before a longer study. P.C2 indicates whether
  readout drifts within a job. Its protocol covers only this experiment;
  the Phase A analysis plan has not been written.
- **v0.3 defaults:**
  - T1/T2 plans from `plan_characterization` use the interleaved design:
    random delay order and 5 ground references.
  - `"probe"` plans produce readout probes, reported as MEASURED
    `readout_error` (`p(1|0)`, `p(0|1)`) rather than inferred rates. They
    are the fixed probe workload that carries the absolute threshold
    (`docs/SEQUENTIAL_METHODS.md` §3.1).

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
- That the binomial and Gaussian models hold beyond the study's window: real
  batches can be correlated (drifts within a job, leakage, crosstalk), which
  the e-process guarantees assume away.
- Operational value on hardware: cloud users cannot trigger a calibration,
  so the intervention available to them is avoiding or remapping a degraded
  qubit until the vendor recalibrates. Experiment I simulates the operator's
  case (recalibration on demand); a hardware intervention study is still
  missing.
