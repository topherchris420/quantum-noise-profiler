# Quantum Noise Profiler (`qnp`)

Tracks per-qubit noise over time and flags drift, **telling you how it knows
each number, and when it doesn't know.**

Every estimate carries a provenance:

- **observed**: read from the backend's own calibration data;
- **inferred**: identified from your ordinary jobs, with a Bayesian credible
  interval and its assumptions attached;
- **measured**: from dedicated characterization sequences (T1, Hahn-echo T2).

When the data can't support an estimate, the result is
`insufficient_evidence` with a reason, not a number.

> Status: v0.1 research prototype. Simulator-validated only; see
> [results](#evidence-so-far). Not yet tested on hardware.

## Why the three modes?
T1 and T2 can't be recovered from arbitrary circuit results. T1 needs decay
over controlled delays, and T2 needs Ramsey/echo sequences. What *is*
identifiable from workloads is narrower: for any qubit whose noiseless outcome
is a definite bit, how often it comes out flipped (`effective_flip_rate`, per
circuit context). `qnp` reports exactly that. For T1/T2 it either reads the
vendor's numbers or measures them, and it keeps those series apart.

## Quick start
```bash
pip install -e ".[qiskit]"          # or ".[dev]" for tests + cirq + qiskit-experiments
python examples/demo_qiskit_sim.py
```

```python
from qnp import Profiler
from qnp.alerts import format_text, to_json
from qnp.measured import run_t1

prof = Profiler()                                    # in-memory; Profiler(EstimateStore("qnp.db")) to persist
prof.observe_qiskit_backend(backend)                 # OBSERVED
prof.ingest_qiskit(isa_circuits, sampler_job.result(), timestamp=ts)   # INFERRED
prof.add(run_t1(backend, qubit=0, delays_s=delays))  # MEASURED
alerts = prof.check()
print(format_text(alerts))          # humans
payload = to_json(alerts)           # control systems
prof.mark_recalibrated(ts)          # restart baselines after a recalibration
```

Pass the **executed (ISA) circuits** so qubit indices are physical.

## What the metrics mean
- **T1**: how long an excited qubit takes to relax to |0⟩.
- **T2 (Hahn echo)**: how long a superposition keeps its phase, with slow
  noise echoed away. It isn't the same as T2* (Ramsey).
- **readout error**: probability a measurement reports the wrong bit (vendor figure).
- **effective flip rate**: probability a qubit with a definite ideal outcome
  is observed flipped in *this kind of circuit*. It includes prep, gate,
  decoherence and readout error. It's comparable only within one context
  (`ideal=<bit>|1q<n>|2q<m>`).

## Alerts
- `CRITICAL threshold`: posterior P(beyond recalibration threshold) ≥ 0.95.
- `WARNING drift`: P(degraded by ≥ 10% vs baseline) ≥ 0.95.
- `INFO/WARNING forecast`: trend projected to cross the threshold, with an 80%
  interval for the time. It never extrapolates beyond the span of the data.

## Evidence so far
Three preregistered simulator experiments (gradual drift, sudden degradation,
insufficient evidence). Criteria are in `experiments/PREREGISTRATION.md`,
committed before any run. All runs, including failures, are in
`results/runs.jsonl`. **v0.1 passed 8 of 14 criteria**: abstention and interval calibration held; continuous-monitoring false alarms and misspecified T1 fits failed. See [`results/SUMMARY.md`](results/SUMMARY.md).

## Limitations
- Simulator-only validation so far; readout error was the only injected noise.
- Inferred mode needs deterministic-outcome qubits in the workload (basis-state
  probes, mirror circuits, syndrome qubits). A pure-superposition workload gives
  insufficient evidence by design.
- Circuits with mid-circuit measurement, reset, control flow, or > 16 active
  qubits are skipped (reported, not guessed).
- T1/T2 fits assume single-exponential decay and have no goodness-of-fit
  check yet (see E3d).
- Qiskit `Target` has no calibration timestamp and no uncertainties. Observed
  series use the ingestion time unless you pass one.
- Adapters: Qiskit (Sampler V2 + legacy counts), Cirq (results). pyQuil and
  Cirq-Google calibration are not implemented yet.

## Docs
- `docs/INSPECTION_LOG.md`: what Qiskit/Cirq/pyQuil actually return (plus REA findings)
- `docs/DESIGN.md`: data model and algorithms
- `docs/VALIDATION_PLAN.md`: next simulator and IBM hardware validation

## Citation
If you use this, please cite the repository (citation file to come with the
first tagged release) and the frameworks it builds on: Qiskit, Qiskit Aer,
Qiskit Experiments, Cirq. Package inspection used
[REA](https://github.com/morluto/rea).

MIT licence.
