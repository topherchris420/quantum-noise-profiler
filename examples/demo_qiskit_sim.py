"""End-to-end demo on a simulator: all three provenance modes, then a readout
degradation on qubit 0 that the profiler should flag.

    python examples/demo_qiskit_sim.py
"""

import warnings
from datetime import datetime, timedelta, timezone

import numpy as np
from qiskit import QuantumCircuit
from qiskit.providers.fake_provider import GenericBackendV2
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, ReadoutError

from qnp import Profiler
from qnp.alerts import format_text
from qnp.measured import run_t1

warnings.filterwarnings("ignore")
t0 = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
prof = Profiler()

# 1. OBSERVED: what the backend says about itself.
backend = GenericBackendV2(num_qubits=2, seed=7)
prof.observe_qiskit_target(backend.target, t0)

# 2. MEASURED: a dedicated T1 sweep on qubit 0.
truth_t1 = backend.target.qubit_properties[0].t1
prof.add(
    run_t1(AerSimulator.from_backend(backend), 0, np.linspace(0, 3 * truth_t1, 15), shots=1000, seed=1, timestamp=t0)
)

# 3. INFERRED: ordinary jobs. One deterministic circuit, one that isn't.
det = QuantumCircuit(2)
det.x(0)
det.measure_all()
bell = QuantumCircuit(2)
bell.h(0)
bell.cx(0, 1)
bell.measure_all()
for i in range(12):
    p0 = 0.02 if i < 8 else 0.035  # qubit 0 readout degrades after job 8
    nm = NoiseModel()
    nm.add_readout_error(ReadoutError([[1 - p0, p0], [p0, 1 - p0]]), [0])
    sim = AerSimulator(noise_model=nm)
    res = sim.run([det, bell], shots=4000, seed_simulator=i).result()
    prof.ingest_qiskit([det, bell], [res.get_counts(0), res.get_counts(1)], t0 + timedelta(minutes=10 * i))

print("Latest estimate per series:")
for s in prof.snapshot():
    if s["metric"] in ("gate_error",):
        continue
    val = "INSUFFICIENT EVIDENCE: " + s["reason"] if s["value"] is None else f"{s['value']:.4g}"
    ci = f"  95% CI [{s['ci_low']:.4g}, {s['ci_high']:.4g}]" if s["ci_low"] is not None else ""
    print(f"  q{s['qubits']} {s['metric']:<20} {s['provenance']:<9} {s['context']:<24} {val}{ci}")
print(f"\n(truth: T1 q0 = {truth_t1:.4g} s)\n")
print(format_text(prof.check()))
