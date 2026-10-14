# Quantum Noise Profiler (`qnp`)

**Uncertainty-aware monitoring of qubit noise that says how it knows each
number, controls how often it raises false alarms over a whole monitoring
session, and refuses to report estimates its data or model cannot support.**

> **Status: v0.3 research prototype (`0.3.0.dev0`).** The method results
> below come from preregistered *simulations* (Qiskit Aer, Cirq, numpy). The
> only hardware data is a short preregistered QPU experiment (Experiment P,
> 14 jobs on IBM `ibm_fez`, two hours). It checks two of the method's
> assumptions. Readout was stable within a job (P.C2 passed), but readout
> error fluctuated between batches by more than binomial noise (P.C1 failed,
> 6 of 10 series). See [What is not known](#what-is-not-known) and
> [`results/V03_SUMMARY.md`](results/V03_SUMMARY.md).

## First physical-QPU experiment: what the assumptions got wrong

**IBM `ibm_fez` · October 13–14, 2026 UTC · 5 qubits · 14 jobs · 296,000 shots · 130 seconds QPU time.** A preregistered two-hour pilot tested *assumptions*, not whether the alerts predict real hardware failures.

| Assumption check | Real-device result | Status |
|---|---|---|
| P.C1: each readout-probe series has a constant binomial error rate across 12 batches | 6 of 10 series reject | **Not supported on this device** |
| P.C2: interleaved ground references detect readout drift within T1 sweeps | 0 of 10 sweeps reject | **No within-job drift detected** |

On qubit **108**, `p(0|1)` rose from around 1% to nearly 3%, then partially recovered. Five drift alerts followed. **We cannot label them true or false warnings without independent reference data.** The v0.3 simulations do not establish detector validity on the real device.

[**Read the hardware addendum**](docs/report/HARDWARE_ADDENDUM.md) · [Raw-data-backed results](results/V03_SUMMARY.md) · [Future holdout-study plan](experiments/P04_FOLLOWUP_PLAN.md)

## Technical report

**Warnings a qubit monitor can stand behind** — an assessment of Quantum Noise Profiler (`qnp`) v0.3.
Christopher Woodyard, Vers3Dynamics · October 2026 · 10 pages. **Historical simulation-only report written before Experiment P**; for the real-QPU findings, read the [hardware addendum](docs/report/HARDWARE_ADDENDUM.md).

<p>
  <a href="https://github.com/topherchris420/quantum-noise-profiler/blob/main/docs/report/qnp-technical-report.pdf"><img src="https://raw.githubusercontent.com/topherchris420/quantum-noise-profiler/main/docs/report/qnp-report-p01.png" width="49%" alt="Report cover"></a>
  <a href="https://github.com/topherchris420/quantum-noise-profiler/blob/main/docs/report/qnp-technical-report.pdf"><img src="https://raw.githubusercontent.com/topherchris420/quantum-noise-profiler/main/docs/report/qnp-report-p02.png" width="49%" alt="Summary for decision-makers"></a>
</p>

**[Read the full report (PDF)](https://github.com/topherchris420/quantum-noise-profiler/blob/main/docs/report/qnp-technical-report.pdf)**

<details>
<summary>All pages</summary>

![Page 1](https://raw.githubusercontent.com/topherchris420/quantum-noise-profiler/main/docs/report/qnp-report-p01.png)
![Page 2](https://raw.githubusercontent.com/topherchris420/quantum-noise-profiler/main/docs/report/qnp-report-p02.png)
![Page 3](https://raw.githubusercontent.com/topherchris420/quantum-noise-profiler/main/docs/report/qnp-report-p03.png)
![Page 4](https://raw.githubusercontent.com/topherchris420/quantum-noise-profiler/main/docs/report/qnp-report-p04.png)
![Page 5](https://raw.githubusercontent.com/topherchris420/quantum-noise-profiler/main/docs/report/qnp-report-p05.png)
![Page 6](https://raw.githubusercontent.com/topherchris420/quantum-noise-profiler/main/docs/report/qnp-report-p06.png)
![Page 7](https://raw.githubusercontent.com/topherchris420/quantum-noise-profiler/main/docs/report/qnp-report-p07.png)
![Page 8](https://raw.githubusercontent.com/topherchris420/quantum-noise-profiler/main/docs/report/qnp-report-p08.png)
![Page 9](https://raw.githubusercontent.com/topherchris420/quantum-noise-profiler/main/docs/report/qnp-report-p09.png)
![Page 10](https://raw.githubusercontent.com/topherchris420/quantum-noise-profiler/main/docs/report/qnp-report-p10.png)

</details>

## Independent validation: collaborators welcome

We are inviting independent replication and exploratory discussions about a
**proposed 30-day, read-only observation study** using existing qubit calibration
records or authorized exports. The observation-only phase would **not** submit
quantum jobs, modify device settings, access someone else's provider account, or
claim ground-truth error detection. It can examine data quality, repeatability,
timestamp fidelity, and agreement with recorded calibration changes. Measuring
detection accuracy requires a separately defined independent reference.

A later **optional, separately approved** phase could run dedicated T1/T2 and
fixed-context probe circuits under explicit provider authorization and
shot/time budgets. Neither proposed longer-term phase has started. The separately authorized short **Experiment P has already run**; see the hardware addendum.

Researchers at national laboratories, NIST, universities, and other quantum
facilities can review the [proposed study and collaboration checklist](docs/HARDWARE_VALIDATION.md).
To discuss feasibility, [open a GitHub issue](https://github.com/topherchris420/quantum-noise-profiler/issues/new)
without including credentials, restricted records, or confidential data.
No institutional partnership or endorsement is implied.

## Why it matters

Error rates and coherence times of real qubits drift between calibrations.
A monitor that watches them continuously is useful only if its warnings can
be trusted: checked after every batch, a monitor that uses a fixed
per-check probability bar will eventually raise a false alarm in almost every
session. The v0.1 prototype of this project did exactly that
(62% of stable sessions alerted), and its T1 fits reported confident but
wrong values when the decay was not a single exponential (72% false
confidence). v0.2 is the attempt to fix both, measured against
preregistered criteria. v0.3 fixes two of v0.2's failures, the
absolute-threshold misfire and drift-blind T1 fits. It also tests whether
earlier warnings reduce failed jobs or calibration overhead.

## What the profiler does

| | |
|---|---|
| **Provenance** | every estimate is *observed* (vendor calibration), *inferred* (from ordinary jobs), or *measured* (dedicated T1/T2 sequences); series are never mixed |
| **Sequential error control** | anytime-valid e-processes with an explicit session error budget across time, qubits, metrics and contexts; each alert states its e-value, threshold and the kind of guarantee behind it |
| **Meaningful deterioration** | an alert needs statistical evidence *and* an effect of at least 10% *and* persistence |
| **Forecasts that can abstain** | `VALID_FORECAST`, `INSUFFICIENT_EVIDENCE`, `MODEL_MISSPECIFICATION`, `INSUFFICIENT_HISTORY`, `UNSTABLE_TREND`, `UNSUPPORTED_HORIZON`, with machine-readable reasons; predictive (not just parameter) intervals for the threshold-crossing time |
| **Readout probes** | two prepare-and-measure circuits added to a job become MEASURED `readout_error` series (`p(1\|0)`, `p(0\|1)`); the absolute recalibration threshold applies only to them, so a workload change cannot trip it. Workload error rates are monitored for relative change only |
| **Model checking** | a T1/T2 value is reported only if delay coverage, deviance, posterior-predictive and residual checks pass; otherwise `insufficient_evidence` or `model_misspecification` |
| **Drift-robust sweeps** | T1/T2 delays are acquired in random order with 5 interleaved ground references; readout drift during the sweep is reported (`READOUT_DRIFT`) instead of bending the estimate |
| **Evidence integrity** | append-only run log, SHA-256 manifest, every summary recomputable from raw data, provenance checks in CI |

## What has been shown (simulation only)

Two preregistered studies. Each used disjoint seeds for development,
calibration and testing, and ran every method on identical data. Failures
are listed, not hidden.

### v0.3 follow-up: 40 of 40 preregistered criteria passed

Details: [`results/V03_SUMMARY.md`](results/V03_SUMMARY.md).

| Question | v0.2 design | v0.3 design |
|---|---|---|
| Runs with a false alert after adding a 2 µs idle before measurement (hardware unchanged) | 1.00 | 0.02 |
| ... after adding two-qubit gates | 0.43 | 0.05 |
| T1 reported confidently wrong under slow readout drift (v0.2's D11 conditions) | 0.255 | 0.005 |
| ... under linear readout drift of ±1.5% | 0.370 | 0.000 |
| Valid T1 fits rejected (the price of the drift check) | 1.5–2% | 2.5–4% |

The false-alert rows use the calibrated configuration (empirical, not
anytime-valid, false-alarm control), 100 simulated runs per scenario; T1
rows, 200 simulated fits per scenario and design.

**Do earlier warnings help?** A closed-loop simulation tested this, with
illustrative degradation rates and qubits degrading about once per day:

- **Failed jobs:** with daily calibration alone, 13–20% of jobs ran on a
  qubit above 5% readout error. Recalibrating on v0.3 warnings as well cut
  this to at most 0.31%, 4.7–5.4 points below a fixed schedule of equal
  cost.
- **Calibration overhead:** warnings alone used as many calibrations as
  the daily schedule, or about 0.5 more per qubit-day. They used fewer only
  when degradation was rare or absent.
- **What did not hold up:** a calibrated CUSUM on the same probes did as
  well as the v0.3 engine.

![Failed jobs against calibrations per qubit-day](https://raw.githubusercontent.com/topherchris420/quantum-noise-profiler/main/paper/figures/fig10_operational_frontier.png)

### v0.2 study: 53 of 62 preregistered checks passed

Details: [`results/V02_SUMMARY.md`](results/V02_SUMMARY.md).

| Question | v0.1 | v0.2 |
|---|---|---|
| Stable 8 h sessions with any false alert (qubit at 4.5%, threshold 5%) | 0.70 | 0.010 anytime-valid · 0.068 calibrated |
| Stable 24 h sessions with any false alert | 0.77 | 0.005 · 0.070 |
| Warning lead before a drifting qubit crosses 5% (median, matched false-alert rate) | 203 min (re-thresholded) | 253 min **calibrated** (Shewhart 223, CUSUM 213) |
| ×1.2 step detected within 6 batches (matched false-alert rate) | 0.20 | 0.73 (CUSUM 0.48) |
| T1 reported confidently wrong when T1 fluctuates | 0.72 | 0.00 |
| T1 withheld for a two-component decay | 0.00 | 1.00 |
| 80% forecast intervals that contained the true crossing time | – | 0.800 |

**Interpretation matters:** the <= 1% stable-session false-alert figures were
*observed in five simulated conditions* using the **uncalibrated,
anytime-valid** thresholds. They are not a universal 1% false-alarm guarantee.
The 253-minute median warning result used a **separately calibrated**
configuration with *empirical*, not anytime-valid, false-alarm control.
The declared session error budget is `alpha_session = 0.10` and its coverage
depends on channel-specific null assumptions; see
[Sequential methods](docs/SEQUENTIAL_METHODS.md). Forecast coverage was
measured across correlated forecasts within runs, not independent hardware
trials. Nothing here establishes performance on real devices.

![False alerts accumulate under v0.1 and stay bounded under v0.2](https://raw.githubusercontent.com/topherchris420/quantum-noise-profiler/main/paper/figures/fig3_false_alert_accumulation.png)

**Where v0.2 failed (preregistered criteria):**

- A 10% step is not detected within 5 batches by any method at this shot
  budget (0.09; the original project claim was 0.80). *Unchanged in v0.3.*
- Slowly drifting readout offset during a T1 sweep passes the model checks
  in 74% of fits and yields a wrong T1 in 28.5%. *Fixed in simulation by
  the v0.3 sweep design (0.5%).*
- Circuits with idle time or extra two-qubit gates trigger the absolute 5%
  threshold on unchanged hardware, because their effective error rate really
  is above 5%. The threshold is applied to a workload-dependent quantity.
  *Fixed in simulation by v0.3 readout probes (2–5%, all from the drift
  channel).*
- Stationary 10% fluctuations of an otherwise stable device alarm in about
  half of runs (exploratory condition). *Unresolved.* v0.3's operational
  simulation includes a ±5% fluctuation. In it, 0.27–0.44 calibrations per
  qubit-day were triggered without real degradation.

**Where conventional methods remain better:** a calibrated CUSUM detects the
smallest (10%) steps more often within 24 batches (0.64 vs 0.52).

## What is not known

- **Real hardware.** The only real-device data is one two-hour pilot
  (Experiment P: 14 jobs on `ibm_fez`, 5 qubits, 2026-10-13/14).
  - **Binomial constant-rate counts:** failed (P.C1). Readout error
    fluctuated between batches beyond binomial noise in 6 of 10 probe series.
    The drift channel needs a fluctuation model or a larger effect gate
    before deployment on that device.
  - **Readout stability within a job:** held (P.C2, 0 of 10 sweeps).
  - **Batch independence:** not tested separately.
  - **Generality:** one device and two hours say nothing about other devices
    or longer periods.
  - **Running it yourself:** `python tools/ibm_connect.py` saves an IBM
    Quantum account. `python experiments/run_v03.py pilot` is a dry run that
    sends nothing; adding `--submit` runs it. It submits jobs, so it is the
    separately authorized kind of experiment, not part of the read-only
    observation study.
  - **Interrupted QPU jobs:** future runs save per-job IDs and results in a local private checkpoint directory; no automatic resume or stitching. See [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md).
  - See [`docs/HARDWARE_VALIDATION.md`](docs/HARDWARE_VALIDATION.md).
- **Other noise processes.** Leakage, coherent errors, crosstalk, 1/f
  dephasing and correlated multi-qubit errors are not simulated
  ([`src/qnp/sim.py`](src/qnp/sim.py) docstring).
- **Operational value on hardware.** The v0.3 result is a simulation with
  chosen degradation rates. It assumes recalibration on demand, which cloud
  users cannot do. Their intervention, avoiding or remapping a degraded
  qubit, has not been tested.
- **Scale.** Families of 2 qubits were tested; the union-bound budget grows
  conservative with many qubits and metrics.

## Quick start

```bash
pip install -e ".[qiskit]"          # or ".[dev]" for tests, Cirq, IBM fake backends, figures
python examples/demo_qiskit_sim.py
```

```python
from qnp import DriftConfig, ErrorBudget, Profiler
from qnp.alerts import format_text
from qnp.measured import readout_probe_circuits

probes = readout_probe_circuits(physical_qubits, num_qubits=backend.num_qubits)  # |0..0> and |1..1>, measured
# run the probes in the same job as the transpiled workload, without a layout change
prof = Profiler(config=DriftConfig(budget=ErrorBudget(alpha_session=0.10, n_qubits=5, n_metrics=2)))
prof.ingest_qiskit([*isa_workload, *probes], sampler_job.result(), timestamp=ts)
# probes -> MEASURED readout_error (threshold applies); workload -> INFERRED effective flip (relative change only)
alerts = prof.check()               # alerts carry e-value, threshold, alpha and guarantee type
print(format_text(alerts))
reports = prof.report()             # per-group evidence, gates and forecast statuses with reasons
```

- Pass the executed (ISA) circuits, so qubit indices are physical.
- Readout probes and workload series are two metrics (`n_metrics=2`).
  Without probes, no absolute threshold applies to anything ingested from
  jobs. `readout_probes="off", context_mode="bucket"` restores the v0.2
  ingestion.
- Declare the monitoring family up front (`ErrorBudget(n_qubits, n_metrics, n_provenances)`;
  monitoring one quantity through several provenances counts each as a test);
  if it grows later, `prof.family["exceeded"]` is set and the budget no
  longer holds.
- `DriftConfig(log_e_offset=2.0)` is the empirically calibrated configuration
  of the study. Its alerts are labelled `+calibrated`, and its guarantee is
  empirical, not anytime-valid.
- `LegacyDriftConfig()` reproduces the frozen v0.1 rules.
- T1/T2: `qnp.measured.run_t1(...)` returns `ok`, `insufficient_evidence` or
  `model_misspecification`, with reason codes in `estimate.diagnostics`.
  - Sweeps use the drift-robust design by default.
  - `plan=decay_sweep_plan(delays, **V02_SWEEP)` gives the v0.2 sequential
    design.

## How the guarantees work, in one paragraph

The monitor uses sequential e-values and declares a session error budget
`alpha_session = 0.10`, split among channels and the fixed monitoring
family (qubits, metrics, provenances). **Where the e-process null assumptions
hold**, Ville's inequality bounds the chance that a test crosses its
threshold at *any* monitoring time. The binomial threshold channel has an
exact frequentist guarantee under its model; the binomial drift channel has
a **Bayesian-marginal** guarantee, with fixed-rate false alerts evaluated by
simulation. Gaussian approximations and plug-in uncertainty estimates carry
their own limitations. The faster calibrated configuration **does not retain
the anytime-valid guarantee**. Each alert reports its guarantee type, and
the pilot tested assumptions but did **not** validate monitoring accuracy or false-alert guarantees on hardware. Details:
[`docs/SEQUENTIAL_METHODS.md`](docs/SEQUENTIAL_METHODS.md).

## Reproduce and verify

```bash
python tools/verify_results.py    # hashes + recompute every reported number from raw data
python tools/pilot_diagnostics.py # exploratory diagnostics of the recorded QPU pilot
python tools/check_provenance.py  # schema, clean source tree, preregistered seed blocks
python experiments/run_v03.py H   # re-run an experiment (appends; never overwrites)
python tools/make_figures.py && python tools/make_v03_figures.py
```

See [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md).

## Documentation

| Document | Contents |
|---|---|
| [`docs/report/qnp-technical-report.pdf`](docs/report/qnp-technical-report.pdf) | Original 10-page simulation-only report, preserved as written |
| [`docs/report/HARDWARE_ADDENDUM.md`](docs/report/HARDWARE_ADDENDUM.md) | Accessible, text-based account of the real-device pilot and its negative assumption check |
| [`experiments/P04_FOLLOWUP_PLAN.md`](experiments/P04_FOLLOWUP_PLAN.md) | Unexecuted future independent hardware study, baselines, evidence safeguards |
| [`paper/paper.md`](paper/paper.md) | research report: definitions, hypotheses, methods, results, limitations, references |
| [`experiments/V03_PREREGISTRATION.md`](experiments/V03_PREREGISTRATION.md) | v0.3 protocol (G, H, I and the hardware pilot P), committed before data |
| [`results/V03_SUMMARY.md`](results/V03_SUMMARY.md), [`results/V03_TABLES.md`](results/V03_TABLES.md) | v0.3 results, every criterion, full tables |
| [`experiments/v03/DEVELOPMENT_NOTES.md`](experiments/v03/DEVELOPMENT_NOTES.md) | development runs (seeds < 20 000) behind the v0.3 design choices |
| [`experiments/V02_PREREGISTRATION.md`](experiments/V02_PREREGISTRATION.md) | v0.2 protocol, committed before data |
| [`results/V02_SUMMARY.md`](results/V02_SUMMARY.md) | v0.2 results and the eight success questions |
| [`docs/V01_AUDIT.md`](docs/V01_AUDIT.md), [`results/E2_CORRECTION.md`](results/E2_CORRECTION.md) | audit of v0.1 and the matched E2 re-analysis |
| [`docs/SEQUENTIAL_METHODS.md`](docs/SEQUENTIAL_METHODS.md) | e-processes, budget, forecasts, what is and is not guaranteed |
| [`docs/INVESTIGATION_V02.md`](docs/INVESTIGATION_V02.md) | Qiskit/Aer/Cirq/Stim/Runtime behaviour, with REA artifact evidence |
| [`docs/HARDWARE_VALIDATION.md`](docs/HARDWARE_VALIDATION.md) | collaboration invitation, the read-only and separately authorized study phases, how to run Experiment P, and the limits of vendor calibration data |
| [`docs/DESIGN.md`](docs/DESIGN.md), [`docs/INSPECTION_LOG.md`](docs/INSPECTION_LOG.md) | v0.1 design and framework inspection (kept as written) |
| [`RELEASE_NOTES.md`](RELEASE_NOTES.md), [`CITATION.cff`](CITATION.cff) | changes and citation |

## Citation

See [`CITATION.cff`](CITATION.cff). Please also cite Qiskit, Qiskit Aer,
Qiskit Experiments and Cirq. Native-artifact inspection used
[REA](https://github.com/morluto/rea).

MIT licence.
