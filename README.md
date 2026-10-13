# Quantum Noise Profiler (`qnp`)

**Uncertainty-aware monitoring of qubit noise that says how it knows each
number, controls how often it raises false alarms over a whole monitoring
session, and refuses to report estimates its data or model cannot support.**

> **Status: v0.2 research prototype.** Every result below comes from
> preregistered *simulations* (Qiskit Aer, Cirq, numpy). Nothing has been
> run on quantum hardware. See [What is not known](#what-is-not-known).

## Why it matters

Error rates and coherence times of real qubits drift between calibrations.
A monitor that watches them continuously is useful only if its warnings can
be trusted: checked after every batch, a monitor that uses a fixed
per-check probability bar will eventually raise a false alarm in almost every
session. The v0.1 prototype of this project did exactly that
(62% of stable sessions alerted), and its T1 fits reported confident but
wrong values when the decay was not a single exponential (72% false
confidence). v0.2 is the attempt to fix both, measured against
preregistered criteria.

## What the profiler does

| | |
|---|---|
| **Provenance** | every estimate is *observed* (vendor calibration), *inferred* (from ordinary jobs), or *measured* (dedicated T1/T2 sequences); series are never mixed |
| **Sequential error control** | anytime-valid e-processes with an explicit session error budget across time, qubits, metrics and contexts; each alert states its e-value, threshold and the kind of guarantee behind it |
| **Meaningful deterioration** | an alert needs statistical evidence *and* an effect of at least 10% *and* persistence |
| **Forecasts that can abstain** | `VALID_FORECAST`, `INSUFFICIENT_EVIDENCE`, `MODEL_MISSPECIFICATION`, `INSUFFICIENT_HISTORY`, `UNSTABLE_TREND`, `UNSUPPORTED_HORIZON`, with machine-readable reasons; predictive (not just parameter) intervals for the threshold-crossing time |
| **Model checking** | a T1/T2 value is reported only if delay coverage, deviance, posterior-predictive and residual checks pass; otherwise `insufficient_evidence` or `model_misspecification` |
| **Evidence integrity** | append-only run log, SHA-256 manifest, every summary recomputable from raw data, provenance checks in CI |

## What has been shown (simulation only)

Preregistered study, disjoint seeds for development, calibration and
testing, every method run on identical data. **53 of 62 preregistered checks
passed**; the failures are listed below, not hidden. Details:
[`results/V02_SUMMARY.md`](results/V02_SUMMARY.md).

| Question | v0.1 | v0.2 |
|---|---|---|
| Stable 8 h sessions with any false alert (qubit at 4.5%, threshold 5%) | 0.70 | 0.010 anytime-valid · 0.068 calibrated |
| Stable 24 h sessions with any false alert | 0.77 | 0.005 · 0.070 |
| Warning lead before a drifting qubit crosses 5% (median, matched false-alert rate) | 203 min | 253 min (Shewhart 223, CUSUM 213) |
| ×1.2 step detected within 6 batches (matched false-alert rate) | 0.20 | 0.73 (CUSUM 0.48) |
| T1 reported confidently wrong when T1 fluctuates | 0.72 | 0.00 |
| T1 withheld for a two-component decay | 0.00 | 1.00 |
| 80% forecast intervals that contained the true crossing time | – | 0.800 |

![False alerts accumulate under v0.1 and stay bounded under v0.2](paper/figures/fig3_false_alert_accumulation.png)

**Where it failed (preregistered criteria):**

- A 10% step is not detected within 5 batches by any method at this shot
  budget (0.09; the original project claim was 0.80).
- Slowly drifting readout offset during a T1 sweep passes the model checks
  in 74% of fits and yields a wrong T1 in 28.5%.
- Circuits with idle time or extra two-qubit gates trigger the absolute 5%
  threshold on unchanged hardware, because their effective error rate really
  is above 5%. The threshold is applied to a workload-dependent quantity.
- Stationary 10% fluctuations of an otherwise stable device alarm in about
  half of runs (exploratory condition).

**Where conventional methods remain better:** a calibrated CUSUM detects the
smallest (10%) steps more often within 24 batches (0.64 vs 0.52).

## What is not known

- **Real hardware.** No real-device data exist yet. Batch independence and
  binomial counts are assumptions. The read-only IBM pathway (`qnp.hardware`)
  is designed and tested on fake backends; see
  [`docs/HARDWARE_VALIDATION.md`](docs/HARDWARE_VALIDATION.md).
- **Other noise processes.** Leakage, coherent errors, crosstalk, 1/f
  dephasing and correlated multi-qubit errors are not simulated
  ([`src/qnp/sim.py`](src/qnp/sim.py) docstring).
- **Operational value.** Whether earlier warnings save calibration time or
  failed jobs needs an intervention study.
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

prof = Profiler(config=DriftConfig(budget=ErrorBudget(alpha_session=0.10, n_qubits=5, n_metrics=1)))
prof.ingest_qiskit(isa_circuits, sampler_job.result(), timestamp=ts, context_mode="exact")  # INFERRED
alerts = prof.check()               # alerts carry e-value, threshold, alpha and guarantee type
print(format_text(alerts))
reports = prof.report()             # per-group evidence, gates and forecast statuses with reasons
```

- Pass the executed (ISA) circuits, so qubit indices are physical.
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

## How the guarantees work, in one paragraph

Each monitored series carries an *e-process*: a running likelihood ratio,
mixed over possible change times and effect sizes, whose expectation under
"no deterioration" is at most 1. Ville's inequality then bounds the chance
that it *ever* exceeds 1/α, however long monitoring runs. The session
budget α = 0.10 is split across channels (drift, threshold, forecast) and
across the declared qubits, metrics and provenances. The threshold channel's guarantee
is exact. The drift channel's guarantee holds under a prior on the unknown
baseline rate and is checked empirically at fixed rates. Experiment A held
in every tested condition. See [`docs/SEQUENTIAL_METHODS.md`](docs/SEQUENTIAL_METHODS.md).

## Reproduce and verify

```bash
python tools/verify_results.py    # hashes + recompute every reported number from raw data
python tools/check_provenance.py  # schema, clean source tree, preregistered seed blocks
python experiments/run_v02.py C   # re-run an experiment (appends; never overwrites)
python tools/make_figures.py
```

See [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md).

## Documentation

| Document | Contents |
|---|---|
| [`paper/paper.md`](paper/paper.md) | research report: definitions, hypotheses, methods, results, limitations, references |
| [`experiments/V02_PREREGISTRATION.md`](experiments/V02_PREREGISTRATION.md) | v0.2 protocol, committed before data |
| [`results/V02_SUMMARY.md`](results/V02_SUMMARY.md) | v0.2 results and the eight success questions |
| [`docs/V01_AUDIT.md`](docs/V01_AUDIT.md), [`results/E2_CORRECTION.md`](results/E2_CORRECTION.md) | audit of v0.1 and the matched E2 re-analysis |
| [`docs/SEQUENTIAL_METHODS.md`](docs/SEQUENTIAL_METHODS.md) | e-processes, budget, forecasts, what is and is not guaranteed |
| [`docs/INVESTIGATION_V02.md`](docs/INVESTIGATION_V02.md) | Qiskit/Aer/Cirq/Stim/Runtime behaviour, with REA artifact evidence |
| [`docs/HARDWARE_VALIDATION.md`](docs/HARDWARE_VALIDATION.md) | IBM Quantum pathway and the limits of vendor calibration data |
| [`docs/DESIGN.md`](docs/DESIGN.md), [`docs/INSPECTION_LOG.md`](docs/INSPECTION_LOG.md) | v0.1 design and framework inspection (kept as written) |
| [`RELEASE_NOTES.md`](RELEASE_NOTES.md), [`CITATION.cff`](CITATION.cff) | changes and citation |

## Citation

See [`CITATION.cff`](CITATION.cff). Please also cite Qiskit, Qiskit Aer,
Qiskit Experiments and Cirq. Native-artifact inspection used
[REA](https://github.com/morluto/rea).

MIT licence.
