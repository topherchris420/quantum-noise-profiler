"""Run the preregistered v0.3 study (experiments/V03_PREREGISTRATION.md).

    python experiments/run_v03.py G|H|I              # confirmatory simulation experiments
    python experiments/run_v03.py G --smoke          # CI smoke test (tiny, separate results dir)
    python experiments/run_v03.py pilot              # hardware pilot, DRY RUN: plan and budget, nothing sent
    python experiments/run_v03.py pilot --submit     # hardware pilot on IBM Quantum (credentials needed)
    python experiments/run_v03.py pilot --fake FakeTorino --submit --interval 0   # rehearsal (local, not evidence)

G and I reuse the calibrated thresholds of the v0.2 calibration run (c*,
h*, k*; read from results/runs.jsonl). Each completed invocation appends one entry to
results/runs.jsonl and one gzipped raw file to results/raw/; nothing is
overwritten. The pilot also journals each job to a private per-run checkpoint
directory, including interrupted runs; it does not resume or stitch them.
Smoke and rehearsal runs must write elsewhere (QNP_RESULTS_DIR).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
warnings.filterwarnings("ignore")

from common import RESULTS, ROOT, Criterion, environment, record
from v02.harness import seed_for
from v03 import analysis
from v03.harness import SEED_CONFIRMATORY_V03, SEED_H

PROTOCOL = "experiments/V03_PREREGISTRATION.md"
G_ORDER = ("G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8")


def g_seed(scenario: str, run: int) -> int:
    k = G_ORDER.index(scenario)
    e, j = (0, k) if k < 5 else (1, k - 5)
    return seed_for(SEED_CONFIRMATORY_V03, e, j, run)


def i_seed(k: int, run: int) -> int:
    return seed_for(SEED_CONFIRMATORY_V03, 2, k, run)


def h_seed(k: int, design_index: int, rep: int) -> int:
    if not 0 <= rep < 200 or not 0 <= design_index < 3:
        raise ValueError("H seed layout supports rep < 200, design index < 3")
    return SEED_H + 1000 * k + 200 * design_index + rep


# --------------------------------------------------------------------------- workers


def _g_job(job: dict) -> dict:
    from v03.exp_g import run_job

    return run_job(job["scenario"], job["seed"])


def _h_job(job: dict) -> dict:
    from v03.exp_h import run_rep

    return run_rep(job["scenario"], job["design"], job["seed"])


def _i_job(job: dict) -> dict:
    from v03.operational import make_world, simulate
    from v03.policies import build_policies, scenario_from_config

    sc = scenario_from_config(job["scenario_spec"])
    w = make_world(sc, job["n_batches"], job["seed"])
    pols = build_policies(job["calibrated"])
    return {
        "scenario": job["scenario"],
        "seed": job["seed"],
        "n_events": [len(e) for e in w.events],
        "outcomes": {name: simulate(pol, w).to_dict() for name, pol in pols.items()},
    }


WORKERS = {"G": _g_job, "H": _h_job, "I": _i_job}


def _dispatch(job):
    return WORKERS[job["kind"]](job)


def run_jobs(jobs: list[dict], workers: int) -> list[dict]:
    t0 = time.time()
    out = []
    if workers <= 1:
        for i, j in enumerate(jobs):
            out.append(_dispatch(j))
            if (i + 1) % 25 == 0:
                print(f"  {i + 1}/{len(jobs)} ({time.time() - t0:.0f} s)", flush=True)
        return out
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for i, r in enumerate(ex.map(_dispatch, jobs, chunksize=1)):
            out.append(r)
            if (i + 1) % 25 == 0 or i + 1 == len(jobs):
                print(f"  {i + 1}/{len(jobs)} ({time.time() - t0:.0f} s)", flush=True)
    return out


def v02_calibration() -> dict:
    """The v0.2 calibration run whose thresholds v0.3 reuses (V03_PREREGISTRATION.md section 0)."""
    cal: list = []
    # smoke runs write elsewhere but reuse the recorded calibration of the repository
    for path in dict.fromkeys([RESULTS / "runs.jsonl", ROOT / "results" / "runs.jsonl"]):
        if path.exists():
            entries = [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
            cal = [e for e in entries if e["experiment"] == "V02_calibration" and not e["config"].get("smoke")]
        if cal:
            break
    if not cal:
        raise SystemExit("no V02_calibration entry")
    return {"run_id": cal[-1]["run_id"], **cal[-1]["summary"]["chosen"]}


# --------------------------------------------------------------------------- plans


def plan(name: str, smoke: bool):
    r = (lambda n: min(n, 2)) if smoke else (lambda n: n)
    if name == "G":
        from v03.exp_g import G_SCENARIOS, N_BATCHES, SHIFT_AT, crossing_batch

        cal = v02_calibration()
        jobs = [{"kind": "G", "scenario": sc, "seed": g_seed(sc, run)} for sc in G_SCENARIOS for run in range(r(100))]
        cfg = {
            "scenarios": list(G_SCENARIOS),
            "scenario_descriptions": G_SCENARIOS,
            "n_batches": N_BATCHES,
            "shift_at": SHIFT_AT,
            "batch_minutes": 10.0,
            "ramp_crossing_batch": crossing_batch(),
            "calibrated": {k: cal[k] for k in ("c_star", "k_star", "h_star", "b_star")},
            "calibration_run_id": cal["run_id"],
            "architectures": {
                "v02": "all circuits -> INFERRED effective flip (exact contexts); thresholds V02_THRESHOLDS; 2 qubits x 1 metric",
                "v03": "workload -> INFERRED effective flip (exact, no threshold); probes -> MEASURED readout_error "
                "(threshold 0.05); 2 qubits x 2 metrics",
            },
            "seed_block": SEED_CONFIRMATORY_V03,
            "experiment_indices": [0, 1],
            "smoke": smoke,
        }
        return "V03_G_workload_probes", jobs, cfg
    if name == "H":
        from v03.exp_h import DESIGNS, SCENARIOS

        jobs = []
        for k, sc in enumerate(SCENARIOS):
            designs = ["interleaved"] if SCENARIOS[sc].get("aer") else list(DESIGNS)
            reps = 100 if SCENARIOS[sc].get("aer") else 200
            for d in designs:
                for rep in range(r(reps)):
                    jobs.append(
                        {"kind": "H", "scenario": sc, "design": d, "seed": h_seed(k, list(DESIGNS).index(d), rep)}
                    )
        cfg = {
            "scenarios": {
                k: {kk: (list(vv) if isinstance(vv, tuple) else vv) for kk, vv in v.items()}
                for k, v in SCENARIOS.items()
            },
            "designs": DESIGNS,
            "seed_rule": "70000 + 1000*scenario_index + 200*design_index + rep",
            "smoke": smoke,
        }
        return "V03_H_sweep_drift", jobs, cfg
    if name == "I":
        from v03.policies import FRONTIER, MONITORS, OPS_SCENARIOS, PAIRED, policy_descriptions, scenario_to_config

        cal = v02_calibration()
        days = 0.5 if smoke else 4.0
        n_runs = r(40)
        jobs = [
            {
                "kind": "I",
                "scenario": sc,
                "scenario_spec": scenario_to_config(spec),
                "seed": i_seed(k, run),
                "n_batches": int(days * 144),
                "calibrated": {kk: cal[kk] for kk in ("c_star", "k_star", "h_star")},
            }
            for k, (sc, spec) in enumerate(OPS_SCENARIOS.items())
            for run in range(n_runs)
        ]
        cfg = {
            "scenarios": list(OPS_SCENARIOS),
            "scenario_specs": {k: scenario_to_config(v) for k, v in OPS_SCENARIOS.items()},
            "days": days,
            "n_qubits": 2,
            "n_runs": n_runs,
            "policies": policy_descriptions(),
            "frontier_policies": FRONTIER,
            "monitor_policies": MONITORS,
            "paired_comparisons": PAIRED,
            "bootstrap_seed": 2026,
            "bootstrap_samples": 2000 if not smoke else 50,
            "calibrated": {k: cal[k] for k in ("c_star", "k_star", "h_star", "b_star")},
            "calibration_run_id": cal["run_id"],
            "seed_block": SEED_CONFIRMATORY_V03,
            "experiment_indices": [2],
            "smoke": smoke,
        }
        return "V03_I_operational", jobs, cfg
    raise SystemExit(f"unknown experiment {name}")


# --------------------------------------------------------------------------- pilot


def _backend(args):
    if args.fake:
        import qiskit_ibm_runtime.fake_provider as fp

        return getattr(fp, args.fake)()
    from qiskit_ibm_runtime import QiskitRuntimeService

    token = os.environ.get("QISKIT_IBM_TOKEN")
    instance = os.environ.get("QISKIT_IBM_INSTANCE")
    service = (
        QiskitRuntimeService(channel="ibm_quantum_platform", token=token, instance=instance)
        if token
        else QiskitRuntimeService()
    )
    if args.backend:
        return service.backend(args.backend)
    return service.least_busy(operational=True, simulator=False, min_num_qubits=5)


def run_pilot(args) -> dict | None:
    from v03 import pilot as P
    from v03.checkpoints import PilotCheckpoint

    from qnp.hardware import HardwareSession, JobBudget

    if args.fake and args.submit and RESULTS.resolve() == (ROOT / "results").resolve():
        raise SystemExit("a fake-backend rehearsal is not evidence: set QNP_RESULTS_DIR to a scratch directory")
    started = datetime.now(timezone.utc)
    env0 = environment()
    backend = _backend(args)
    budget = JobBudget(**P.BUDGET)  # type: ignore[arg-type]
    session = HardwareSession(backend, dry_run=not args.submit, allow_submission=args.submit, budget=budget)
    snap = session.snapshot()
    sel = P.select_qubits(snap)
    qubits = sel["qubits"]
    plans = P.make_plans(backend, snap, qubits)
    totals = P.planned_totals(plans)
    print(f"backend {snap['backend_name']} ({'local fake' if snap['local_simulation'] else 'IBM Quantum'})")
    print(f"qubits {qubits} (rule: {sel['rule']}, {sel['n_candidates']} candidates)")
    print(
        f"planned: {totals['jobs']} jobs, {totals['shots']} shots, ~{totals['estimated_qpu_seconds']:.0f} s QPU (estimate)"
    )
    print(f"budget: {P.BUDGET}")
    over = [
        k
        for k, (v, lim) in {
            "jobs": (totals["jobs"], budget.max_jobs),
            "shots": (totals["shots"], budget.max_total_shots),
            "seconds": (totals["estimated_qpu_seconds"], budget.max_estimated_qpu_seconds),
        }.items()
        if v > lim
    ]
    if over:
        raise SystemExit(f"the planned pilot exceeds its budget: {over}")
    if not args.submit:
        rec = session.submit(plans["probe"])  # dry run: describes, sends nothing
        print(f"DRY RUN: nothing was sent ({rec['status']}). Re-run with --submit to execute.")
        return None
    checkpoint = PilotCheckpoint(args.checkpoint_dir)
    print(f"Local, private job checkpoints: {checkpoint.directory}", flush=True)
    raw = P.execute(session, plans, qubits, interval_s=args.interval, checkpoint=checkpoint.record)
    cfg = {
        "backend": snap["backend_name"],
        "local_simulation": snap["local_simulation"],
        "qubits": qubits,
        "selection": sel,
        "budget": P.BUDGET,
        "planned": totals,
        "design": {
            "n_probe_batches": P.N_PROBE_BATCHES,
            "probe_shots": P.PROBE_SHOTS,
            "sweep_shots": P.SWEEP_SHOTS,
            "n_delays": P.N_DELAYS,
            "sweep_span_t1": P.SWEEP_SPAN_T1,
            "n_references": P.N_REFERENCES,
            "interval_s": args.interval,
        },
        "rehearsal": bool(args.fake),
    }
    summary = P.analyze(raw, cfg)
    criteria = [Criterion(*c) for c in P.criteria(summary)]
    notes = "REHEARSAL on a fake backend (local simulation) - not hardware evidence" if args.fake else ""
    entry = record("V03_P_pilot", cfg, summary, criteria, [raw], started, notes, env0, PROTOCOL, compress=True)
    checkpoint.record("research_recorded", {"run_id": entry["run_id"], "passed_all": entry["passed_all"]})
    _print_entry(entry)
    return entry


def _print_entry(entry):
    print(f"\n== {entry['run_id']}  passed_all={entry['passed_all']}")
    for c in entry["criteria"]:
        print(
            f"   [{'PASS' if c['passed'] else 'FAIL'}] {c['name']}: observed {c['observed']:.4g} "
            f"{c['comparison']} {c['threshold']:g}"
        )


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("experiment", choices=["G", "H", "I", "pilot"])
    ap.add_argument("--smoke", action="store_true", help="2 runs per condition, for CI; never evidence")
    ap.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    ap.add_argument("--backend", default=None, help="pilot: IBM backend name (default: least busy)")
    ap.add_argument(
        "--fake", default=None, help="pilot: rehearse on a qiskit_ibm_runtime fake backend, e.g. FakeTorino"
    )
    ap.add_argument("--submit", action="store_true", help="pilot: actually run the jobs (default: dry run)")
    ap.add_argument("--interval", type=float, default=600.0, help="pilot: seconds between probe batches")
    ap.add_argument(
        "--checkpoint-dir",
        default=None,
        help="pilot: private checkpoint root (default: ~/.qnp/pilot-checkpoints); no automatic resume",
    )
    args = ap.parse_args(argv)
    if args.experiment == "pilot":
        return run_pilot(args)
    if args.smoke and RESULTS.resolve() == (ROOT / "results").resolve():
        raise SystemExit("--smoke must write elsewhere: set QNP_RESULTS_DIR to a scratch directory")
    started = datetime.now(timezone.utc)
    env0 = environment()
    exp_id, jobs, cfg = plan(args.experiment, args.smoke)
    print(f"{exp_id}: {len(jobs)} jobs on {args.workers} workers", flush=True)
    trials = run_jobs(jobs, args.workers)
    summary = analysis.SUMMARY[exp_id](trials, cfg)
    criteria = [Criterion(*c) for c in analysis.CRITERIA[exp_id](summary)]
    notes = "SMOKE TEST - not evidence" if args.smoke else ""
    entry = record(exp_id, cfg, summary, criteria, trials, started, notes, env0, PROTOCOL, compress=True)
    _print_entry(entry)
    return entry


if __name__ == "__main__":
    main()
