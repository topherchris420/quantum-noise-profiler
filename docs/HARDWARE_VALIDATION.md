# IBM Quantum validation pathway (pilot ready; not yet executed)

No real-device job has been run for this project. Everything in `results/`
is simulation. v0.3 adds a short, preregistered hardware pilot
(Experiment P, `experiments/V03_PREREGISTRATION.md` §5) that runs with one
command once an IBM Quantum account is available. This document describes
how to run it, what it can and cannot establish, and the longer study that
should follow it.

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

## Running the pilot (Experiment P)

The pilot answers one question: do the assumptions the monitor rests on hold
on a real device over about two hours? It runs 14 jobs:

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
  `QiskitRuntimeService.save_account`);
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

What the pilot reports (`experiments/v03/pilot.py`):

| Check | Meaning if it fails |
|---|---|
| P.C1: ≤ 1 of 10 probe series (5 qubits × 2 preparations) rejects one constant rate across the 12 batches (G-test, α = 0.01) | batch-to-batch readout fluctuation exceeds binomial noise on this device: the drift channel's null does not hold there, and a fluctuation model (or a larger effect gate) is needed before deployment |
| P.C2: ≤ 1 of 10 T1 sweeps has disagreeing ground references (α = 0.01) | readout drifts within a job: sequential sweeps (v0.2 design) would give confidently wrong T1 there |

Also reported: T1 statuses and reason codes; whether vendor T1 lies in each
accepted fit's interval and vendor readout errors in the pooled probe
intervals (consistency only); the v0.3 engine's alerts on the probe series;
which execution timestamps the service reports; whether calibration history
(`properties(datetime=…)`) is available.

## Verified behaviour (qiskit-ibm-runtime 0.50.0, fake backends)

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
- Live-service behaviour (calibration history, `job.metrics()` timestamp
  fields, plan quotas) is **unverified**: no IBM account was used. The pilot
  records it.

## After the pilot: the longer study

1. **Observed series, read-only, 30 days.** Hourly `HardwareSession.snapshot()`
   of the pilot qubits. Cost: zero QPU time.
2. **Measured T1/T2, twice daily**, interleaved design.
3. **Readout probes with every monitored job**, plus mirror circuits of 2–3
   depths analysed with exact contexts.
4. **Analysis** with the v0.3 engine and the family declared up front
   (`ErrorBudget(n_qubits=…, n_metrics=…, n_provenances=…)`), with the
   fluctuation scale measured in the pilot deciding whether the 10% effect
   gate must grow.

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
- That the binomial and Gaussian models hold beyond the pilot's window: real
  batches can be correlated (drifts within a job, leakage, crosstalk), which
  the e-process guarantees assume away.
- Operational value on hardware: cloud users cannot trigger a calibration,
  so the intervention available to them is avoiding or remapping a degraded
  qubit until the vendor recalibrates. Experiment I simulates the operator's
  case (recalibration on demand); a hardware intervention study is still
  missing.
