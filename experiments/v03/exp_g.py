"""Experiment G: workload shift and hardware change with readout probes.

The v0.2 Experiment E device and workloads (E1-E7), with two readout probe
circuits (prepare |00> / |11>, measure) added to every batch, plus a stable
control (G0) and a gradual readout ramp (G8). Two engine architectures run
on identical simulated counts:

* ``v02``: every circuit is workload (probes included) -> INFERRED effective
  flip rates, exact contexts, v0.2 thresholds (absolute 5% on every context);
  family 2 qubits x 1 metric;
* ``v03``: workload -> INFERRED effective flip rates (exact contexts, no
  absolute threshold); probes -> MEASURED readout_error (threshold 5%);
  family 2 qubits x 2 metrics.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
from v02.harness import BATCH_INTERVAL, T0
from v02.workloads import E_DEVICE, e_workload

N_BATCHES = 48
SHIFT_AT = 24
G_SCENARIOS = {
    "G0": "stable hardware, constant workload",
    "G1": "E1 depth (same bucket)",
    "G2": "E2 gate composition",
    "G3": "E3 circuit frequencies",
    "G4": "E4 shots and batch interval",
    "G5": "E5 2 us idle before measurement",
    "G6": "E6 extra two-qubit gates",
    "G7": "E7 = E2 workload change and q0 readout x1.5 at the same batch",
    "G8": "constant workload, q0 readout ramp 2% -> 6% over 48 batches",
}
RAMP = (0.02, 0.06)


def g_workload(scenario: str, phase: int):
    from qnp.measured import readout_probe_circuits

    if scenario in ("G0", "G8"):
        circuits, shots = e_workload("E1", 0)  # the common pre-shift workload of E1, E2, E4-E7
    else:
        circuits, shots = e_workload("E" + scenario[1:], phase)
    return circuits + readout_probe_circuits([0, 1]), shots


def q0_readout(scenario: str, i: int) -> float:
    if scenario == "G7" and i >= SHIFT_AT:
        return 0.03
    if scenario == "G8":
        return float(np.linspace(*RAMP, N_BATCHES)[i])
    return 0.02


def g_batches(scenario: str, seed: int, n_batches: int = N_BATCHES):
    """Per batch (i, timestamp, v02-architecture estimates, v03-architecture
    estimates, true q0 readout error) from one set of Aer counts."""
    from qnp.adapters.qiskit_adapter import estimates_from_results, infer_from_results
    from qnp.sim import aer_run_counts

    out = []
    t = T0
    for i in range(n_batches):
        phase = int(i >= SHIFT_AT)
        circuits, shots = g_workload(scenario, phase)
        p0 = q0_readout(scenario, i)
        dev = E_DEVICE if p0 == 0.02 else E_DEVICE.with_qubit(0, p_read1_given0=p0, p_read0_given1=p0)
        counts = aer_run_counts(circuits, dev, shots, seed * 10_000 + i)
        if i > 0:
            t = t + (timedelta(minutes=30) if (scenario == "G4" and phase) else BATCH_INTERVAL)
        e02 = infer_from_results(circuits, counts, t, context_mode="exact")
        e03 = estimates_from_results(circuits, counts, t, context_mode="exact", readout_probes="auto")
        out.append((i, t, e02, e03, p0))
    return out


def crossing_batch() -> float:
    lo, hi = RAMP
    return (0.05 - lo) / ((hi - lo) / (N_BATCHES - 1))


def run_job(scenario: str, seed: int) -> dict:
    """One run of one scenario: both architectures on the same counts."""
    from .harness import EngineSpec3, run_engine3

    bs = g_batches(scenario, seed)
    rec: dict = {"scenario": scenario, "seed": seed, "p0": [b[4] for b in bs], "t_hours": []}
    rec["t_hours"] = [round((b[1] - bs[0][1]).total_seconds() / 3600, 6) for b in bs]
    rec["v02"] = run_engine3([(i, t, e) for i, t, e, _, _ in bs], EngineSpec3("v02", "v02", n_metrics=1))
    rec["v03"] = run_engine3([(i, t, e) for i, t, _, e, _ in bs], EngineSpec3("v03", "v03", n_metrics=2))
    rec["contexts_q0"] = {
        arch: {
            "before": sorted({e.context for _, _, *es, _ in bs[:SHIFT_AT] for e in es[k] if e.qubits == (0,)}),
            "after": sorted({e.context for _, _, *es, _ in bs[SHIFT_AT:] for e in es[k] if e.qubits == (0,)}),
        }
        for k, arch in ((0, "v02"), (1, "v03"))
    }
    for arch in ("v02", "v03"):
        rec[arch].pop("alerts")  # the c = 0 engine's alerts are recomputable from the evidence
    return rec
