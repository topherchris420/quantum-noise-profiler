"""Experiment P: a short real-device pilot (V03_PREREGISTRATION.md section 7).

It does not validate the method (too short, one device); it checks the
assumptions the method rests on, on real hardware, and runs real data through
the v0.3 pipeline end to end:

* P1 binomial adequacy -- are per-batch readout-probe counts of a qubit
  consistent with one constant rate over the session (the null of the drift
  channel)?
* P2 within-job drift -- do the ground references interleaved in a T1 sweep
  agree (the D11 failure mode)?
* P3 T1 fits on hardware -- statuses and reasons of the v0.3 fit with the
  drift-robust design; consistency (not accuracy) with vendor T1 values.
* P4 the v0.3 engine on the probe series -- which alerts, if any.
* P5 metadata -- execution timestamps, per-property calibration timestamps,
  calibration-history access.

Execution order: snapshot, T1 sweep (all qubits, one job), probe batches at a
fixed interval, T1 sweep, snapshot. Everything goes through
``qnp.hardware.HardwareSession``: dry run by default, explicit authorization
per plan, cumulative budget.
"""

from __future__ import annotations

import itertools
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

N_QUBITS = 5
QUANTILES = (0.1, 0.3, 0.5, 0.7, 0.9)
N_PROBE_BATCHES = 12
PROBE_SHOTS = 4000
SWEEP_SHOTS = 1000
N_DELAYS = 15
SWEEP_SPAN_T1 = 3.0  # delays on [0, 3 x vendor T1] per qubit
N_REFERENCES = 5
INTERVAL_S = 600.0
SEED_P = 90_000  # sweep-order seeds: SEED_P + sweep index (0, 1)
ALPHA = 0.01
BUDGET = {"max_jobs": 14, "max_total_shots": 320_000, "max_circuits_per_job": 300, "max_estimated_qpu_seconds": 420.0}


# --------------------------------------------------------------------------- design


def _vendor(entry: dict, key: str) -> float | None:
    rec = entry.get(key)
    if not isinstance(rec, dict):
        return None
    v = rec.get("value")
    return float(v) if v is not None and math.isfinite(float(v)) else None


def select_qubits(snapshot: dict, n: int = N_QUBITS) -> dict[str, Any]:
    """Preregistered rule: among qubits that the backend reports as operational
    (when it reports it) with a positive vendor T1 and T2, T2 <= 2 T1
    (physically consistent values) and a readout error, sort by vendor readout
    error (ties by index) and take the qubits at ranks round(f (N - 1)) for
    f in 0.1, 0.3, 0.5, 0.7, 0.9 -- a spread of readout quality, chosen
    before any pilot data."""
    cands = []
    for qs, entry in snapshot["qubits"].items():
        t1, t2, ro = _vendor(entry, "T1"), _vendor(entry, "T2"), _vendor(entry, "readout_error")
        op = _vendor(entry, "operational")
        if t1 and t2 and 0 < t2 <= 2 * t1 and ro is not None and (op is None or op >= 1):
            cands.append((ro, int(qs)))
    cands.sort()
    if len(cands) < n:
        raise ValueError(f"only {len(cands)} qubits qualify; need {n}")
    ranks = [round(f * (len(cands) - 1)) for f in QUANTILES[:n]]
    chosen = [cands[r][1] for r in ranks]
    if len(set(chosen)) != n:
        raise ValueError("selection rule produced duplicate qubits")
    return {"qubits": chosen, "n_candidates": len(cands), "ranks": ranks, "rule": "readout-error quantiles"}


def sweep_delays(snapshot: dict, q: int) -> list[float]:
    t1 = _vendor(snapshot["qubits"][str(q)], "T1")
    if not t1:
        raise ValueError(f"no vendor T1 for qubit {q}")
    return [float(x) for x in np.linspace(0, SWEEP_SPAN_T1 * t1, N_DELAYS)]


def make_plans(backend, snapshot: dict, qubits: list[int]) -> dict[str, Any]:
    from qnp.hardware import plan_characterization

    delays = {q: sweep_delays(snapshot, q) for q in qubits}
    common = {"n_references": N_REFERENCES, "randomize": True}
    return {
        "sweep0": plan_characterization(backend, "t1", qubits, delays, SWEEP_SHOTS, seed=SEED_P, **common),
        "sweep1": plan_characterization(backend, "t1", qubits, delays, SWEEP_SHOTS, seed=SEED_P + 1, **common),
        "probe": plan_characterization(backend, "probe", qubits, shots=PROBE_SHOTS, parallel=True),
    }


def planned_totals(plans: dict) -> dict[str, float]:
    jobs = 2 + N_PROBE_BATCHES
    shots = plans["sweep0"].total_shots + plans["sweep1"].total_shots + N_PROBE_BATCHES * plans["probe"].total_shots
    secs = (
        plans["sweep0"].estimated_qpu_seconds
        + plans["sweep1"].estimated_qpu_seconds
        + N_PROBE_BATCHES * plans["probe"].estimated_qpu_seconds
    )
    return {"jobs": jobs, "shots": shots, "estimated_qpu_seconds": secs}


# --------------------------------------------------------------------------- execution


def _ts(x) -> str | None:
    if x is None:
        return None
    if isinstance(x, datetime):
        return x.isoformat()
    return str(x)


def _pub_counts(pub) -> dict[str, dict[str, int]]:
    data = pub.data
    names = list(data.keys()) if hasattr(data, "keys") else ["c"]
    return {name: {k: int(v) for k, v in getattr(data, name).get_counts().items()} for name in names}


def _run(session, plan, label: str) -> dict:
    from qnp.hardware import execution_timestamps

    rec = session.submit(plan, authorize=True)
    if rec["status"] != "submitted":
        raise RuntimeError(f"{label}: not submitted ({rec.get('status')})")
    job = rec.pop("job")
    result = job.result()
    done = datetime.now(timezone.utc)
    return {
        "label": label,
        "job_id": rec["job_id"],
        "submitted_at": rec["requested_at"],
        "result_received_at": done.isoformat(),
        "execution": {k: _ts(v) for k, v in execution_timestamps(job).items()},
        "counts": [_pub_counts(result[i]) for i in range(plan.n_circuits)],
        "plan": plan.summary(),
        "local_simulation": rec.get("local_simulation"),
    }


def calibration_history_probe(backend) -> dict[str, Any]:
    """P5: does ``properties(datetime=...)`` return an older snapshot?"""
    try:
        when = datetime.now(timezone.utc) - timedelta(days=3)
        p = backend.properties(datetime=when)
        return {"available": p is not None, "last_update_date": _ts(getattr(p, "last_update_date", None))}
    except Exception as exc:  # NotImplementedError on some services, TypeError on fakes
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"[:300]}


def execute(session, plans: dict, qubits: list[int], interval_s: float = INTERVAL_S, sleep=time.sleep) -> dict:
    """Run the pilot; returns the raw record (counts, job ids, timestamps,
    snapshots). Probe batches start every ``interval_s`` seconds (later if a
    job queues longer)."""
    raw: dict[str, Any] = {"snapshots": [session.snapshot(qubits)], "jobs": []}
    raw["calibration_history"] = calibration_history_probe(session.backend)
    raw["jobs"].append(_run(session, plans["sweep0"], "sweep0"))
    t_next = time.monotonic()
    for b in range(N_PROBE_BATCHES):
        wait = t_next - time.monotonic()
        if wait > 0:
            sleep(wait)
        t_next = time.monotonic() + interval_s
        raw["jobs"].append(_run(session, plans["probe"], f"probe{b}"))
    raw["jobs"].append(_run(session, plans["sweep1"], "sweep1"))
    raw["snapshots"].append(session.snapshot(qubits))
    raw["session_log"] = [{k: v for k, v in e.items() if k != "job"} for e in session.log]
    return raw


# --------------------------------------------------------------------------- analysis (pure function of the raw record)


def _parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t if t.tzinfo is not None else t.replace(tzinfo=timezone.utc)


def batch_time(job: dict) -> datetime:
    """Execution time of a job: the service's 'running' or 'finished'
    timestamp when it reports one, else the time the result was received."""
    ex = job.get("execution") or {}
    for k in ("running", "finished"):
        t = _parse_time(ex.get(k))
        if t is not None:
            return t
    t = _parse_time(job["result_received_at"])
    assert t is not None
    return t


def _probe_estimates(job: dict, qubits: list[int]) -> list:
    """MEASURED readout_error per qubit and preparation from one probe job."""
    from qnp.measured import estimate_readout

    ts = batch_time(job)
    out = []
    # parallel probe circuits: circuit 0 prepares |0...0>, circuit 1 |1...1>; one register,
    # bit j <-> qubits[j] (qnp.measured.readout_probe_circuits)
    for prep, circ in enumerate(job["counts"]):
        (counts,) = circ.values()
        shots = sum(counts.values())
        for j, q in enumerate(qubits):
            ones = sum(v for k, v in counts.items() if k.replace(" ", "")[::-1][j] == "1")
            errors = ones if prep == 0 else shots - ones
            out.append(estimate_readout(q, prep, errors, shots, ts, source="pilot:readout-probe"))
    return out


def _sweep_estimates(job: dict, qubits: list[int]) -> list:
    from qnp.measured import DecaySweepPlan, estimate_t1_from_plan

    plan = job["plan"]
    if list(plan["physical_qubits"]) != list(qubits):
        raise ValueError("sweep job qubits differ from the pilot qubits")
    out, offset = [], 0
    for q in plan["physical_qubits"]:
        sp = plan["sweeps"][str(q)]
        sweep = DecaySweepPlan(tuple(sp["delays_s"]), tuple((k, int(i)) for k, i in sp["slots"]), sp["seed"])
        ones = []
        for j in range(len(sweep.slots)):
            (counts,) = job["counts"][offset + j].values()
            ones.append(sum(v for k, v in counts.items() if k.endswith("1")))
        offset += len(sweep.slots)
        out.append(estimate_t1_from_plan(q, sweep, ones, plan["shots"], batch_time(job), source="pilot:t1"))
    return out


def analyze(raw: dict, config: dict) -> dict:
    """Summary of the pilot (P1-P5), recomputable from ``raw`` and ``config``."""
    from qnp import DriftConfig, ErrorBudget, Profiler
    from qnp.stats import beta_interval, reference_homogeneity

    qubits = config["qubits"]
    probes = [j for j in raw["jobs"] if j["label"].startswith("probe")]
    sweeps = [j for j in raw["jobs"] if j["label"].startswith("sweep")]
    snap0 = raw["snapshots"][0]
    out: dict[str, Any] = {"backend": snap0["backend_name"], "qubits": qubits}
    times = [batch_time(j) for j in probes]
    gaps = [(b - a).total_seconds() / 60 for a, b in itertools.pairwise(times)]
    out["timing"] = {
        "first_probe": times[0].isoformat() if times else None,
        "last_probe": times[-1].isoformat() if times else None,
        "median_gap_min": float(np.median(gaps)) if gaps else None,
        "execution_timestamps_reported": sum(bool((j.get("execution") or {}).get("available")) for j in raw["jobs"]),
        "n_jobs": len(raw["jobs"]),
    }
    # P1: homogeneity of each (qubit, preparation) probe series across batches
    est = [e for j in probes for e in _probe_estimates(j, qubits)]
    p1 = {}
    for q in qubits:
        for ctx in ("p(1|0)", "p(0|1)"):
            s = [e for e in est if e.qubits == (q,) and e.context == ctx]
            k = [e.successes for e in s]
            n = [e.trials for e in s]
            stat, p, dof = reference_homogeneity(k, n)
            vendor = _vendor(snap0["qubits"][str(q)], "prob_meas1_prep0" if ctx == "p(1|0)" else "prob_meas0_prep1")
            pooled = sum(k) / sum(n) if n else None
            _, lo, hi = beta_interval(sum(k), sum(n)) if n else (None, None, None)
            p1[f"{q}:{ctx}"] = {
                "rates": [ki / ni for ki, ni in zip(k, n)],
                "g_statistic": stat,
                "dof": dof,
                "p": p,
                "dispersion": stat / dof if dof else None,
                "pooled": pooled,
                "pooled_ci95": [lo, hi],
                "vendor": vendor,
                "vendor_inside_pooled_ci": None if vendor is None or lo is None else bool(lo <= vendor <= hi),
            }
    out["P1_probe_homogeneity"] = p1
    out["P1_n_rejected"] = sum(v["p"] < ALPHA for v in p1.values())
    # P2/P3: T1 sweeps with interleaved references
    p23 = {}
    for j in sweeps:
        snap = raw["snapshots"][0 if j["label"] == "sweep0" else -1]
        for e in _sweep_estimates(j, qubits):
            q = e.qubits[0]
            d = e.diagnostics
            vendor_t1 = _vendor(snap["qubits"][str(q)], "T1")
            p23[f"{j['label']}:{q}"] = {
                "status": e.status.value,
                "value_s": e.value,
                "ci95_s": None if e.ci_low is None else [e.ci_low, e.ci_high],
                "codes": [r["code"] for r in d.get("reasons", [])],
                "reference_p": (d.get("references") or {}).get("p"),
                "reference_rates": (d.get("references") or {}).get("rates"),
                "acquisition_runs_p": d.get("acquisition_runs_test_p"),
                "vendor_t1_s": vendor_t1,
                "vendor_inside_ci": None
                if e.ci_low is None or vendor_t1 is None
                else bool(e.ci_low <= vendor_t1 <= e.ci_high),
            }
    out["P2_P3_sweeps"] = p23
    out["P2_n_reference_rejected"] = sum((v["reference_p"] or 1.0) < ALPHA for v in p23.values())
    out["P3_n_ok"] = sum(v["status"] == "ok" for v in p23.values())
    out["P3_n_fits"] = len(p23)
    # P4: the v0.3 engine on the probe series (family: the pilot qubits x readout_error)
    prof = Profiler(config=DriftConfig(budget=ErrorBudget(n_qubits=len(qubits), n_metrics=1, n_provenances=1)))
    alerts = []
    for j in probes:
        prof.add(_probe_estimates(j, qubits))
        for a in prof.check(now=batch_time(j)):
            alerts.append({"batch": j["label"], "qubit": a.qubits[0], "kind": a.kind, "level": a.level.value})
    out["P4_engine_alerts"] = alerts
    # P5: metadata
    out["P5_metadata"] = {
        "calibration_history": raw.get("calibration_history"),
        "per_property_timestamps": all(
            all(
                isinstance(v, dict) and v.get("calibrated_at")
                for k, v in e.items()
                if k in ("T1", "T2", "readout_error")
            )
            for e in snap0["qubits"].values()
        ),
        "properties_changed_during_pilot": raw["snapshots"][0].get("last_update_date")
        != raw["snapshots"][-1].get("last_update_date"),
    }
    return out


def criteria(s: dict) -> list[tuple]:
    """Assumption checks (V03_PREREGISTRATION.md section 7). Failing one is a
    finding about the device, not a failure of the pilot."""
    n1 = len(s["P1_probe_homogeneity"])
    n2 = len(s["P2_P3_sweeps"])
    return [
        (
            "P.C1",
            f"probe series rejecting one constant rate across batches (G-test, alpha 0.01), of {n1}",
            1.0,
            float(s["P1_n_rejected"]),
            "<=",
        ),
        (
            "P.C2",
            f"T1 sweeps whose interleaved ground references disagree (alpha 0.01), of {n2}",
            1.0,
            float(s["P2_n_reference_rejected"]),
            "<=",
        ),
    ]


def recompute_summary(trials: list[dict], config: dict) -> dict:
    """tools/verify_results.py: the pilot's raw file holds one record."""
    (raw,) = trials
    return analyze(raw, config)
