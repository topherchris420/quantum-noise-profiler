"""Run the preregistered v0.2 study (experiments/V02_PREREGISTRATION.md).

    python experiments/run_v02.py calibrate          # §2, calibration seeds
    python experiments/run_v02.py A|B|C|D|E|F        # confirmatory experiments
    python experiments/run_v02.py C --smoke           # CI smoke test (tiny, separate results dir)

Confirmatory experiments read the calibrated thresholds from the most recent
``V02_calibration`` entry of results/runs.jsonl and refuse to run without one.
Each invocation appends one entry to results/runs.jsonl and one gzipped raw
file to results/raw/. Nothing is overwritten.
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

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
warnings.filterwarnings("ignore")

from common import RESULTS, ROOT, Criterion, environment, record
from v02 import analysis
from v02.compact import compact_v01, compact_v02
from v02.harness import (
    SEED_CALIBRATION,
    SEED_CONFIRMATORY,
    EngineSpec,
    aer_batches,
    run_engine,
    seed_for,
    surrogate_batches,
)

N, SHOTS, THR, BATCH_MIN = 48, 2000, 0.05, 10.0
SPB = 2 * SHOTS  # deterministic shots per qubit per batch
REF = 10
V02 = EngineSpec("v02", "v02")
V01 = EngineSpec("v01", "v01")
PROTOCOL = "experiments/V02_PREREGISTRATION.md"


def stable(p0, p1, n=N):
    return [np.full(n, p0), np.full(n, p1)]


CAL_CONDITIONS = {"K1": (0.005, 0.005), "K2": (0.02, 0.02), "K3": (0.045, 0.02), "K4": (0.049, 0.02)}


# --------------------------------------------------------------------------- worker


def _monitor_job(job: dict) -> dict:
    sched = [np.asarray(s) for s in job["schedules"]]
    gen = surrogate_batches if job["data"] == "surrogate" else aer_batches
    batches = gen(sched, job["shots"], job["seed"])
    rec = {
        "exp": job["exp"],
        "cond": job["cond"],
        "seed": job["seed"],
        "n_batches": len(batches),
        "data": job["data"],
        "naive": [[round(b.naive(q), 6) for q in sorted(b.counts)] for b in batches],
    }
    rec["v02"] = compact_v02(run_engine(batches, V02))
    rec["v01"] = compact_v01(run_engine(batches, V01)) if job.get("v01") else None
    return rec


def _e_job(job: dict) -> dict:
    from v02.workloads import e_batches

    bs = e_batches(job["scenario"], job["seed"])
    rec = {"scenario": job["scenario"], "seed": job["seed"], "v02": {}, "contexts": {}}
    for mode, batches in bs.items():
        rec["v02"][mode] = compact_v02(run_engine(batches, V02))
        rec["contexts"][mode] = {
            "before": sorted({c for b in batches[:24] for c in b.counts.get(0, {})}),
            "after": sorted({c for b in batches[24:] for c in b.counts.get(0, {})}),
        }
    return rec


def _f_job(job: dict) -> dict:
    from v02.workloads import f_batches

    batches = f_batches(job["framework"], job["cond"], job["seed"])
    rec = {"framework": job["framework"], "cond": job["cond"], "seed": job["seed"]}
    rec["v02"] = compact_v02(run_engine(batches, V02))
    counts: dict = {}
    for b in batches:
        for q, cs in b.counts.items():
            for ctx, (k, n) in cs.items():
                kk = counts.setdefault(str(q), {}).setdefault(ctx, [[], []])
                kk[0].append(int(k))
                kk[1].append(int(n))
    rec["counts"] = counts
    return rec


def _d_job(job: dict) -> dict:
    from v02.exp_d import run_rep

    return run_rep(job["scenario"], job["rep"])


WORKERS = {"monitor": _monitor_job, "E": _e_job, "F": _f_job, "D": _d_job}


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


def latest_calibration() -> dict:
    path = RESULTS / "runs.jsonl"
    entries = [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()] if path.exists() else []
    cal = [e for e in entries if e["experiment"] == "V02_calibration"]
    if not cal:
        raise SystemExit("no V02_calibration entry: run `python experiments/run_v02.py calibrate` first")
    chosen = cal[-1]["summary"]["chosen"]
    if any(v is None for v in chosen.values()):
        raise SystemExit(f"calibration did not find a value for every method: {chosen}")
    return {"run_id": cal[-1]["run_id"], **chosen}


# --------------------------------------------------------------------------- experiments


def plan(name: str, smoke: bool):
    """Return (experiment id, jobs, config)."""
    r = (lambda n: min(n, 3)) if smoke else (lambda n: n)
    base_cfg = {
        "n_batches": N,
        "shots": SHOTS,
        "shots_per_batch": SPB,
        "ref": REF,
        "threshold": THR,
        "batch_minutes": BATCH_MIN,
        "smoke": smoke,
    }
    if name == "calibrate":
        jobs = []
        for j, (cond, (p0, p1)) in enumerate(CAL_CONDITIONS.items()):
            for e in (0, 1):
                for run in range(r(200)):
                    jobs.append(
                        {
                            "kind": "monitor",
                            "data": "surrogate",
                            "exp": "cal",
                            "cond": cond,
                            "schedules": [x.tolist() for x in stable(p0, p1)],
                            "shots": SHOTS,
                            "seed": seed_for(SEED_CALIBRATION, e, j, run),
                            "v01": e == 0,
                        }
                    )
        cfg = {
            **base_cfg,
            "conditions": list(CAL_CONDITIONS),
            "condition_rates": CAL_CONDITIONS,
            "seed_block": SEED_CALIBRATION,
            "experiment_indices": [0, 1],
            "target": analysis.CAL_TARGET,
            "grids": {"c": analysis.C_GRID, "k": analysis.K_GRID, "h": analysis.H_GRID, "b": analysis.B_GRID},
        }
        return "V02_calibration", jobs, cfg
    if name == "D":
        from v02.exp_d import REPS, SCENARIOS

        jobs = [{"kind": "D", "scenario": sc, "rep": rep} for sc in SCENARIOS for rep in range(r(REPS[sc]))]
        cfg = {
            "scenarios": {
                k: {kk: (list(vv) if isinstance(vv, tuple) else vv) for kk, vv in v.items()}
                for k, v in SCENARIOS.items()
            },
            "reps": {k: r(v) for k, v in REPS.items()},
            "seed_rule": "40000 + 1000*scenario_index + rep",
            "smoke": smoke,
        }
        return "V02_D_misspecification", jobs, cfg
    cal = latest_calibration()
    base_cfg["calibrated"] = {k: cal[k] for k in ("c_star", "k_star", "h_star", "b_star")}
    base_cfg["calibration_run_id"] = cal["run_id"]
    jobs = []
    if name == "A":
        conds = {"A1": (0.005, 0.005), "A2": (0.02, 0.02), "A3": (0.045, 0.02), "A4": (0.049, 0.02)}
        for j, (cond, (p0, p1)) in enumerate(conds.items()):
            for e in (0, 6):
                for run in range(r(200)):
                    jobs.append(
                        {
                            "kind": "monitor",
                            "data": "aer",
                            "exp": "A",
                            "cond": cond,
                            "schedules": [x.tolist() for x in stable(p0, p1)],
                            "shots": SHOTS,
                            "seed": seed_for(SEED_CONFIRMATORY, e, j, run),
                            "v01": e == 0,
                        }
                    )
        for run in range(r(200)):
            jobs.append(
                {
                    "kind": "monitor",
                    "data": "aer",
                    "exp": "A",
                    "cond": "A5",
                    "schedules": [x.tolist() for x in stable(0.02, 0.02, 144)],
                    "shots": SHOTS,
                    "seed": seed_for(SEED_CONFIRMATORY, 0, 4, run),
                    "v01": run < 100,
                }
            )
        from qnp.sim import ou_log_process

        for run in range(r(200)):
            seed = seed_for(SEED_CONFIRMATORY, 6, 4, run)
            sched = ou_log_process(0.02, 0.1, 5.0, N, np.random.default_rng([seed, 1]), n_series=2)
            jobs.append(
                {
                    "kind": "monitor",
                    "data": "aer",
                    "exp": "A",
                    "cond": "A6",
                    "schedules": [x.tolist() for x in sched],
                    "shots": SHOTS,
                    "seed": seed,
                    "v01": False,
                }
            )
        cfg = {
            **base_cfg,
            "conditions": ["A1", "A2", "A3", "A4", "A5", "A6"],
            "condition_rates": conds,
            "seed_block": SEED_CONFIRMATORY,
            "experiment_indices": [0, 6],
        }
        return "V02_A_false_alarm", jobs, cfg
    if name == "B":
        conds = {"B1": (0.02, 0.06), "B2": (0.02, 0.055)}
        spec = {}
        for j, (cond, (lo, hi)) in enumerate(conds.items()):
            spec[cond] = {"ramp": [lo, hi], "i_cross": (THR - lo) / ((hi - lo) / (N - 1))}
            for run in range(r(200)):
                jobs.append(
                    {
                        "kind": "monitor",
                        "data": "aer",
                        "exp": "B",
                        "cond": cond,
                        "schedules": [np.linspace(lo, hi, N).tolist(), np.full(N, 0.02).tolist()],
                        "shots": SHOTS,
                        "seed": seed_for(SEED_CONFIRMATORY, 1, j, run),
                        "v01": True,
                    }
                )
        cfg = {**base_cfg, "conditions": spec, "seed_block": SEED_CONFIRMATORY, "experiment_indices": [1]}
        return "V02_B_gradual", jobs, cfg
    if name == "C":
        conds = {"x1.1": 1.1, "x1.2": 1.2, "x1.5": 1.5, "none": 1.0}
        for j, (cond, ratio) in enumerate(conds.items()):
            sched = np.where(np.arange(N) < 24, 0.02, 0.02 * ratio)
            for run in range(r(200)):
                jobs.append(
                    {
                        "kind": "monitor",
                        "data": "aer",
                        "exp": "C",
                        "cond": cond,
                        "schedules": [sched.tolist(), np.full(N, 0.02).tolist()],
                        "shots": SHOTS,
                        "seed": seed_for(SEED_CONFIRMATORY, 2, j, run),
                        "v01": True,
                    }
                )
        cfg = {
            **base_cfg,
            "conditions": conds,
            "step_at": 24,
            "seed_block": SEED_CONFIRMATORY,
            "experiment_indices": [2],
        }
        return "V02_C_abrupt", jobs, cfg
    if name == "E":
        from v02.workloads import E_SCENARIOS

        for k, sc in enumerate(E_SCENARIOS):
            e, j = (4, k) if k < 5 else (8, k - 5)
            for run in range(r(100)):
                jobs.append({"kind": "E", "scenario": sc, "seed": seed_for(SEED_CONFIRMATORY, e, j, run)})
        cfg = {
            "calibrated": base_cfg["calibrated"],
            "calibration_run_id": cal["run_id"],
            "scenarios": list(E_SCENARIOS),
            "shift_at": 24,
            "n_batches": N,
            "seed_block": SEED_CONFIRMATORY,
            "experiment_indices": [4, 8],
            "smoke": smoke,
            "deviations": ["DV1", "DV2"],
        }
        return "V02_E_workload_shift", jobs, cfg
    if name == "F":
        for j, cond in enumerate(("F1", "F2")):
            for run in range(r(100)):
                seed = seed_for(SEED_CONFIRMATORY, 5, j, run)
                for fw in ("qiskit", "cirq"):
                    jobs.append({"kind": "F", "framework": fw, "cond": cond, "seed": seed})
        cfg = {
            "calibrated": base_cfg["calibrated"],
            "calibration_run_id": cal["run_id"],
            "step_at": 24,
            "n_batches": N,
            "seed_block": SEED_CONFIRMATORY,
            "experiment_indices": [5],
            "smoke": smoke,
            "qubits": [3, 7],
            "deviations": ["DV2"],
        }
        return "V02_F_cross_framework", jobs, cfg
    raise SystemExit(f"unknown experiment {name}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("experiment", choices=["calibrate", "A", "B", "C", "D", "E", "F"])
    ap.add_argument("--smoke", action="store_true", help="3 runs per condition, for CI; never evidence")
    ap.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    args = ap.parse_args(argv)
    if args.smoke and RESULTS.resolve() == (ROOT / "results").resolve():
        raise SystemExit("--smoke must write elsewhere: set QNP_RESULTS_DIR to a scratch directory")
    started = datetime.now(timezone.utc)
    env0 = environment()
    exp_id, jobs, cfg = plan(args.experiment, args.smoke)
    print(f"{exp_id}: {len(jobs)} jobs on {args.workers} workers", flush=True)
    trials = run_jobs(jobs, args.workers)
    summary = analysis.SUMMARY[exp_id](trials, cfg)
    crit_fn = analysis.CRITERIA.get(exp_id)
    criteria = [Criterion(*c) for c in crit_fn(summary)] if crit_fn else []
    notes = "SMOKE TEST - not evidence" if args.smoke else ""
    entry = record(
        exp_id, cfg, summary, criteria, trials, started, notes, env_at_start=env0, protocol=PROTOCOL, compress=True
    )
    print(f"\n== {entry['run_id']}  passed_all={entry['passed_all']}")
    for c in entry["criteria"]:
        print(
            f"   [{'PASS' if c['passed'] else 'FAIL'}] {c['name']}: observed {c['observed']:.4g} "
            f"{c['comparison']} {c['threshold']:g}"
        )
    if exp_id == "V02_calibration":
        print("   chosen:", summary["chosen"], "max FA:", summary["chosen_max_fa"])
    return entry


if __name__ == "__main__":
    main()
