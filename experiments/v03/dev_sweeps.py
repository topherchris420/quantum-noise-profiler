"""Development sweeps for the v0.3 study (development seeds below 20 000).

Not evidence: these runs informed design choices fixed in
experiments/V03_PREREGISTRATION.md before any confirmatory run, and are
summarised in experiments/v03/DEVELOPMENT_NOTES.md.

    python experiments/v03/dev_sweeps.py h [--reps 100] [--workers 4]
    python experiments/v03/dev_sweeps.py i [--reps 10] [--days 4] [--workers 4]
    python experiments/v03/dev_sweeps.py g [--reps 10] [--workers 4]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEV_BASE = 10_000


def _h(args):
    from v03.exp_h import run_rep

    return run_rep(*args)


def _g(args):
    from v03.exp_g import run_job

    return run_job(*args)


def _i(args):
    from v03.operational import make_world, simulate

    sc, seed, days, policies = args
    w = make_world(sc, int(days * 144), seed)
    return {name: simulate(pol, w).to_dict() for name, pol in policies.items()}


def dev_policies():
    from v03.operational import NaiveMonitor, OracleMonitor, Policy

    pols = {f"fixed{h}": Policy(f"fixed{h}", schedule_hours=h) for h in (2, 3, 4, 6, 8, 12, 24, 48)}
    pols["none"] = Policy("none", schedule_hours=None)
    pols["oracle+24"] = Policy("oracle+24", OracleMonitor)
    pols["oracle_only"] = Policy("oracle_only", OracleMonitor, None)
    pols["naive+24"] = Policy("naive+24", NaiveMonitor)
    pols["cusum+24"] = Policy("cusum+24", _Cusum)
    pols["cusum_only"] = Policy("cusum_only", _Cusum, None)
    pols["shewhart+24"] = Policy("shewhart+24", _Shewhart)
    pols["eng_cross+24"] = Policy("eng_cross+24", _EngCross)
    pols["eng_any+24"] = Policy("eng_any+24", _EngAny)
    pols["eng_any_only"] = Policy("eng_any_only", _EngAny, None)
    pols["eng_cross_only"] = Policy("eng_cross_only", _EngCross, None)
    return pols


def _Cusum():
    from v03.operational import ChartMonitor

    return ChartMonitor("cusum", 10.0)


def _Shewhart():
    from v03.operational import ChartMonitor

    return ChartMonitor("shewhart", 3.65)


def _EngCross():
    from v03.operational import EngineMonitor

    return EngineMonitor(2.0, "crossing")


def _EngAny():
    from v03.operational import EngineMonitor

    return EngineMonitor(2.0, "any")


def summarise_i(rows_by_sc, days):
    out = {}
    for sc, rows in rows_by_sc.items():
        for name in rows[0]:
            o = [r[name] for r in rows]
            jobs = sum(x["jobs"] for x in o)
            out[f"{sc}/{name}"] = {
                "failed": sum(x["failed"] for x in o) / jobs,
                "cal_per_qday": sum(x["calibrations"] for x in o) / (len(o) * 2 * days),
                "trig_false_per_qday": sum(x["triggered_false"] for x in o) / (len(o) * 2 * days),
                "trig_degraded_per_qday": sum(x["triggered_degraded"] for x in o) / (len(o) * 2 * days),
                "trig_above_per_qday": sum(x["triggered_above"] for x in o) / (len(o) * 2 * days),
            }
    return out


def summarise_h(rows):
    from v03.exp_h import SCENARIOS

    out = {}
    for sc in sorted({r["scenario"] for r in rows}, key=lambda s: list(SCENARIOS).index(s)):
        truth = SCENARIOS[sc]["truth"]
        for d in ("sequential", "randomized", "interleaved"):
            rs = [r for r in rows if r["scenario"] == sc and r["design"] == d]
            if not rs:
                continue
            ok = [r for r in rs if r["status"] == "ok"]
            n = len(rs)
            if truth is None:
                fc = len(ok) / n
                cov = None
            else:
                hit = [r["ci_low"] <= truth <= r["ci_high"] for r in ok]
                fc = (len(ok) - sum(hit)) / n
                cov = float(np.mean(hit)) if hit else None
            codes: dict = {}
            for r in rs:
                for c in r["codes"]:
                    codes[c] = codes.get(c, 0) + 1
            out[f"{sc}/{d}"] = {
                "n": n,
                "not_ok": 1 - len(ok) / n,
                "insufficient": sum(r["status"] == "insufficient_evidence" for r in rs) / n,
                "false_conf": fc,
                "coverage_ok": cov,
                "codes": codes,
            }
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["h", "i", "g"])
    ap.add_argument("--days", type=float, default=4.0)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--reps", type=int, default=100)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--scenarios", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    if a.what == "h":
        from v03.exp_h import DESIGNS, SCENARIOS

        scs = a.scenarios.split(",") if a.scenarios else [s for s in SCENARIOS if s != "H13"]
        jobs = [(sc, d, DEV_BASE + 300 * k + rep) for k, sc in enumerate(scs) for d in DESIGNS for rep in range(a.reps)]
        t0 = time.time()
        with ProcessPoolExecutor(a.workers) as ex:
            rows = list(ex.map(_h, jobs, chunksize=4))
        print(f"{len(rows)} fits in {time.time() - t0:.0f} s")
        s = summarise_h(rows)
        for k, v in s.items():
            cov = "-" if v["coverage_ok"] is None else f"{v['coverage_ok']:.3f}"
            print(
                f"{k:<22} not_ok={v['not_ok']:.3f} insuff={v['insufficient']:.3f} "
                f"false_conf={v['false_conf']:.3f} cov_ok={cov} {v['codes']}"
            )
        if a.out:
            Path(a.out).write_text(json.dumps({"summary": s, "rows": rows}))
    if a.what == "g":
        from v03.analysis import exp_g_summary
        from v03.exp_g import G_SCENARIOS, N_BATCHES, SHIFT_AT, crossing_batch

        scs = a.scenarios.split(",") if a.scenarios else list(G_SCENARIOS)
        jobs = [
            (sc, DEV_BASE + 8000 + 100 * list(G_SCENARIOS).index(sc) + a.offset + rep)
            for sc in scs
            for rep in range(a.reps)
        ]
        t0 = time.time()
        with ProcessPoolExecutor(a.workers) as ex:
            trials = list(ex.map(_g, jobs, chunksize=1))
        print(f"{len(trials)} runs in {time.time() - t0:.0f} s")
        cfg = {
            "scenarios": scs,
            "shift_at": SHIFT_AT,
            "batch_minutes": 10.0,
            "ramp_crossing_batch": crossing_batch(),
            "calibrated": {"c_star": 2.0},
            "n_batches": N_BATCHES,
        }
        s = exp_g_summary(trials, cfg)
        print(json.dumps(s, indent=1)[:20000])
        if a.out:
            Path(a.out).write_text(json.dumps({"summary": s, "trials": trials}))
    if a.what == "i":
        from v03.operational import OpsScenario

        scen = {
            "I0": OpsScenario("I0", 0.0, 0.0),
            "I1": OpsScenario("I1", 0.5, 0.0),
            "I2": OpsScenario("I2", 0.0, 1.0),
            "I3": OpsScenario("I3", 0.5, 0.5),
        }
        pols = dev_policies()
        jobs = [
            (scen[k], DEV_BASE + 5000 + 100 * j + rep, a.days, pols)
            for j, k in enumerate(scen)
            for rep in range(a.reps)
        ]
        t0 = time.time()
        with ProcessPoolExecutor(a.workers) as ex:
            res = list(ex.map(_i, jobs, chunksize=1))
        print(f"{len(res)} worlds in {time.time() - t0:.0f} s")
        by = {k: res[j * a.reps : (j + 1) * a.reps] for j, k in enumerate(scen)}
        s = summarise_i(by, a.days)
        for k, v in s.items():
            print(f"{k:<24} " + " ".join(f"{kk}={vv:.4f}" for kk, vv in v.items()))
        if a.out:
            Path(a.out).write_text(json.dumps({"summary": s, "rows": by}))


if __name__ == "__main__" and (len(sys.argv) < 2 or sys.argv[1] != "hv"):
    main()


# --------------------------------------------------------------------------- H design variants (offline rules)


def _h_raw(args):
    """One fit with every misfit test disabled (alpha 0), so that value, CI
    and all p-values are recorded and any decision rule can be applied
    offline."""
    import numpy as np

    from qnp.measured import decay_sweep_plan, estimate_t1_from_plan
    from qnp.stats import FitDiagnosticsConfig
    from v03.exp_h import N_DELAYS, SCENARIOS, SHOTS, T1, acquisition_probabilities

    scenario, n_refs, seed = args
    spec = SCENARIOS[scenario]
    rng = np.random.default_rng(seed)
    delays = np.linspace(0, spec["r"] * T1, N_DELAYS)
    plan = decay_sweep_plan(delays, n_references=n_refs, randomize=True, seed=int(rng.integers(2**31)))
    ones = rng.binomial(SHOTS, acquisition_probabilities(spec, plan, rng))
    cfg = FitDiagnosticsConfig(deviance_alpha=0, ppc_alpha=0, runs_alpha=0, reference_alpha=0, acquisition_runs_alpha=0)
    est = estimate_t1_from_plan(0, plan, ones, SHOTS, diagnostics=cfg)
    d = est.diagnostics
    refs = d.get("references") or {}
    return {
        "scenario": scenario,
        "k": n_refs,
        "status": est.status.value,
        "value": est.value,
        "ci": None if est.ci_low is None else [est.ci_low, est.ci_high],
        "dev_p": d.get("deviance_p"),
        "ppc_p": d.get("ppc_p"),
        "runs_p": d.get("runs_test_p"),
        "acq_p": d.get("acquisition_runs_test_p"),
        "ref_p": refs.get("p"),
        "ref_rates": refs.get("rates"),
        "ref_pos": refs.get("positions"),
        "truth": spec["truth"],
    }


def trend_p(rates, positions, shots):
    """Two-sided Cochran-Armitage trend test of reference rates in acquisition position."""
    import numpy as np
    from scipy import stats as sps

    k = np.asarray(rates) * shots
    n = np.full(len(rates), float(shots))
    x = np.asarray(positions, float)
    p = k.sum() / n.sum()
    if not 0 < p < 1:
        return 1.0
    xb = (n * x).sum() / n.sum()
    num = (k * (x - xb)).sum()
    var = p * (1 - p) * (n * (x - xb) ** 2).sum()
    return float(2 * sps.norm.sf(abs(num) / np.sqrt(var))) if var > 0 else 1.0


def apply_rule(r, alpha=0.01, trend=False, acq=True):
    if r["status"] != "ok":
        return "insufficient_evidence", None
    tests = [r["dev_p"], r["ppc_p"], r["runs_p"]]
    if acq and r["acq_p"] is not None:
        tests.append(r["acq_p"])
    ref_ok = True
    if r["ref_p"] is not None:
        if trend:
            pt = trend_p(r["ref_rates"], r["ref_pos"], 1000)
            ref_ok = min(r["ref_p"], pt) >= alpha / 2
        else:
            ref_ok = r["ref_p"] >= alpha
    ok = ref_ok and all(p is None or p >= alpha for p in tests)
    return ("ok" if ok else "model_misspecification"), r["ci"] if ok else None


def main_hv(reps=200, workers=4):
    scs = ["H1", "H2", "H3", "H10", "H11", "H11s", "H11l", "H12"]
    jobs = [(sc, k, DEV_BASE + 6000 + 300 * j + rep) for j, sc in enumerate(scs) for k in (5, 7) for rep in range(reps)]
    t0 = time.time()
    with ProcessPoolExecutor(workers) as ex:
        rows = list(ex.map(_h_raw, jobs, chunksize=4))
    print(f"{len(rows)} fits in {time.time() - t0:.0f} s")
    for k in (5, 7):
        for trend in (False, True):
            for acq in (True, False):
                print(f"--- K={k} trend={trend} acq_runs={acq}")
                for sc in scs:
                    rs = [r for r in rows if r["scenario"] == sc and r["k"] == k]
                    dec = [apply_rule(r, trend=trend, acq=acq) for r in rs]
                    ok = [(r, ci) for r, (st, ci) in zip(rs, dec) if st == "ok"]
                    truth = rs[0]["truth"]
                    hit = [ci[0] <= truth <= ci[1] for _, ci in ok]
                    print(
                        f"   {sc:<5} not_ok={1 - len(ok) / len(rs):.3f} false_conf={(len(ok) - sum(hit)) / len(rs):.3f} "
                        f"cov_ok={(sum(hit) / len(ok)) if ok else float('nan'):.3f}"
                    )
    return rows


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "hv":
    out = main_hv()
    Path(sys.argv[2]).write_text(json.dumps(out))
