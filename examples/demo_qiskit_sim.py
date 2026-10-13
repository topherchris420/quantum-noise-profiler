"""End-to-end demo on a simulator: all three provenance modes, then a readout
degradation on qubit 0 that the profiler should flag.

    python examples/demo_qiskit_sim.py

v0.3: the job carries two readout probe circuits, whose results become
MEASURED readout_error series (the absolute recalibration threshold applies
to them); the workload circuit's effective flip rate depends on the circuit,
so it is monitored for relative change only. The T1 sweep uses the default
drift-robust design (random delay order, interleaved ground references).
"""

import warnings
from datetime import datetime, timedelta, timezone

import numpy as np
from qiskit import QuantumCircuit
from qiskit.providers.fake_provider import GenericBackendV2
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, ReadoutError

from qnp import DriftConfig, ErrorBudget, Profiler
from qnp.alerts import format_text
from qnp.measured import readout_probe_circuits, run_t1

warnings.filterwarnings("ignore")
t0 = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
# 2 qubits x 4 metrics (T1, readout error, effective flip, gate error) x 2 provenances, declared up front
prof = Profiler(config=DriftConfig(budget=ErrorBudget(n_qubits=2, n_metrics=4, n_provenances=2)))

# 1. OBSERVED: what the backend says about itself.
backend = GenericBackendV2(num_qubits=2, seed=7)
prof.observe_qiskit_target(backend.target, t0)

# 2. MEASURED: a dedicated T1 sweep on qubit 0 (random order + 5 ground references by default).
truth_t1 = backend.target.qubit_properties[0].t1
prof.add(
    run_t1(AerSimulator.from_backend(backend), 0, np.linspace(0, 3 * truth_t1, 15), shots=1000, seed=1, timestamp=t0)
)

# 3. INFERRED + MEASURED: ordinary jobs carrying two readout probes.
workload = QuantumCircuit(2)
workload.sx(0)
workload.sx(0)  # sx.sx = X: a deterministic outcome on qubit 0
workload.cx(0, 1)
workload.measure_all()
probes = readout_probe_circuits([0, 1])
for i in range(12):
    p0 = 0.02 if i < 8 else 0.07  # qubit 0 readout degrades after job 8
    nm = NoiseModel()
    nm.add_readout_error(ReadoutError([[1 - p0, p0], [p0, 1 - p0]]), [0])
    sim = AerSimulator(noise_model=nm)
    circuits = [workload, *probes]
    res = sim.run(circuits, shots=4000, seed_simulator=i).result()
    prof.ingest_qiskit(circuits, [res.get_counts(j) for j in range(3)], t0 + timedelta(minutes=10 * i))

print("Latest estimate per series:")
for s in prof.snapshot():
    if s["metric"] in ("gate_error",):
        continue
    val = "INSUFFICIENT EVIDENCE: " + s["reason"] if s["value"] is None else f"{s['value']:.4g}"
    ci = f"  95% CI [{s['ci_low']:.4g}, {s['ci_high']:.4g}]" if s["ci_low"] is not None else ""
    print(f"  q{s['qubits']} {s['metric']:<20} {s['provenance']:<9} {s['context']:<34} {val}{ci}")
print(f"\n(truth: T1 q0 = {truth_t1:.4g} s)\n")
print(format_text(prof.check()))
