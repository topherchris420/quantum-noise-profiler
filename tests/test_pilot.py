"""Experiment P (hardware pilot): qubit selection rule and the analysis of a
raw pilot record, on synthetic records (no backend, no network)."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

from v03 import pilot as P

from qnp.measured import decay_sweep_plan

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _snapshot(n=20, seed=0):
    rng = np.random.default_rng(seed)
    qubits = {}
    for q in range(n):
        t1 = float(rng.uniform(80e-6, 200e-6))
        t2 = float(t1 * rng.uniform(0.5, 1.8))
        if q == 3:
            t2 = 2.5 * t1  # unphysical vendor pair: excluded
        qubits[str(q)] = {
            "T1": {"value": t1, "calibrated_at": T0.isoformat()},
            "T2": {"value": t2, "calibrated_at": T0.isoformat()},
            "readout_error": {"value": 0.005 + 0.001 * q, "calibrated_at": T0.isoformat()},
            "prob_meas1_prep0": {"value": 0.004 + 0.001 * q, "calibrated_at": T0.isoformat()},
            "prob_meas0_prep1": {"value": 0.006 + 0.001 * q, "calibrated_at": T0.isoformat()},
        }
    qubits["7"]["operational"] = {"value": 0.0, "calibrated_at": T0.isoformat()}
    return {"backend_name": "synthetic", "qubits": qubits, "last_update_date": T0.isoformat()}


def test_selection_rule_is_deterministic_and_excludes_inconsistent_qubits():
    snap = _snapshot()
    sel = P.select_qubits(snap)
    assert sel["n_candidates"] == 18  # qubit 3 (T2 > 2 T1) and qubit 7 (not operational) excluded
    # readout error increases with the index, so the quantile ranks map to these qubits
    cands = [q for q in range(20) if q not in (3, 7)]
    assert sel["qubits"] == [cands[round(f * 17)] for f in P.QUANTILES]
    with pytest.raises(ValueError, match="qualify"):
        P.select_qubits({"qubits": {k: v for k, v in list(snap["qubits"].items())[:3]}})


def _probe_job(b, qubits, rates, rng, shots=4000):
    counts = []
    for prep in (0, 1):
        bits = np.zeros((shots, len(qubits)), dtype=int)
        for j, q in enumerate(qubits):
            flips = rng.random(shots) < rates[(q, prep)][b]
            bits[:, j] = np.where(flips, 1 - prep, prep)
        c: dict = {}
        for row in bits:
            key = "".join(str(x) for x in row[::-1])
            c[key] = c.get(key, 0) + 1
        counts.append({"c": c})
    ts = (T0 + timedelta(minutes=10 * b)).isoformat()
    return {
        "label": f"probe{b}",
        "result_received_at": ts,
        "execution": {"available": True, "running": ts},
        "counts": counts,
    }


def _sweep_job(label, qubits, snap, rng, seed, drift=None, shots=1000):
    sweeps, counts = {}, []
    for q in qubits:
        t1 = snap["qubits"][str(q)]["T1"]["value"]
        plan = decay_sweep_plan(np.linspace(0, 3 * t1, 15), seed=seed)
        sweeps[str(q)] = plan.to_dict()
        for j, (what, i) in enumerate(plan.slots):
            p = 0.02 if what == "reference" else 0.96 * np.exp(-plan.delays_s[i] / t1) + 0.02
            if drift is not None and q == drift[0]:
                p += drift[1][j]
            k = int(rng.binomial(shots, min(max(p, 0), 1)))
            counts.append({"c": {"1": k, "0": shots - k}})
    return {
        "label": label,
        "result_received_at": T0.isoformat(),
        "execution": {"available": False},
        "counts": counts,
        "plan": {"physical_qubits": list(qubits), "shots": shots, "sweeps": sweeps},
    }


def _raw(snap, qubits, rng, rates, drift=None):
    jobs = [_sweep_job("sweep0", qubits, snap, rng, 90_000, drift)]
    jobs += [_probe_job(b, qubits, rates, rng) for b in range(P.N_PROBE_BATCHES)]
    jobs.append(_sweep_job("sweep1", qubits, snap, rng, 90_001))
    return {"snapshots": [snap, snap], "jobs": jobs, "calibration_history": {"available": False}}


def test_analysis_passes_on_well_behaved_data_and_flags_violations():
    snap = _snapshot()
    qubits = P.select_qubits(snap)["qubits"]
    rng = np.random.default_rng(1)
    steady = {(q, prep): [0.02] * P.N_PROBE_BATCHES for q in qubits for prep in (0, 1)}
    s = P.analyze(_raw(snap, qubits, rng, steady), {"qubits": qubits})
    assert s["P1_n_rejected"] <= 1 and s["P2_n_reference_rejected"] <= 1 and s["P3_n_fits"] == 10
    assert s["P3_n_ok"] >= 8
    assert {c[0]: c[3] <= c[2] for c in P.criteria(s)} == {"P.C1": True, "P.C2": True}
    assert s["timing"]["median_gap_min"] == pytest.approx(10.0)
    # batch-to-batch fluctuation of two qubits' readout, and readout drift within one sweep
    bad = dict(steady)
    for q in qubits[:2]:
        bad[(q, 0)] = list(0.02 * np.exp(0.3 * rng.normal(size=P.N_PROBE_BATCHES)))
    slots = 20
    s2 = P.analyze(_raw(snap, qubits, rng, bad, drift=(qubits[0], np.linspace(-0.02, 0.02, slots))), {"qubits": qubits})
    assert s2["P1_n_rejected"] >= 2
    assert s2["P2_P3_sweeps"][f"sweep0:{qubits[0]}"]["status"] == "model_misspecification"
    assert "READOUT_DRIFT" in s2["P2_P3_sweeps"][f"sweep0:{qubits[0]}"]["codes"]
    assert P.criteria(s2)[0][3] > 1  # P.C1 fails: the constant-rate null does not hold
