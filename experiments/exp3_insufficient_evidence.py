"""Experiment 3 -- does the profiler know when it doesn't know?
See PREREGISTRATION.md (E3). The headline metric is the false-confidence
rate: P(status OK and the truth lies outside the reported 95% interval)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone

import numpy as np

from common import T0, Criterion, print_entry, record, run_batch, workload

REPS = int(sys.argv[1]) if len(sys.argv) > 1 else 100


def e3a_workload_identifiability(trials):
    """Workloads with 0%, 25%, 100% deterministic circuits through Aer + adapter."""
    from qnp import Status
    from qnp.adapters.qiskit_adapter import infer_from_results

    truth, out = 0.03, {}
    for name, (pairs, rand) in {"f=0": (0, 8), "f=0.25": (1, 6), "f=1": (4, 0)}.items():
        circuits = workload(n_det_pairs=pairs, n_random=rand)
        ok = abstain = covered = 0
        for seed in range(min(REPS, 30)):
            counts = run_batch(circuits, truth, truth, 1000, seed)
            es = infer_from_results(circuits, counts, T0)
            for q in (0, 1):
                mine = [e for e in es if e.qubits == (q,)]
                good = [e for e in mine if e.status is Status.OK]
                abstain += not good
                ok += len(good)
                covered += sum(e.ci_low <= truth <= e.ci_high for e in good)
            trials.append({"part": "E3a", "workload": name, "seed": seed,
                           "estimates": [e.to_dict() for e in es]})
        n_qb = 2 * min(REPS, 30)
        out[name] = {"abstention_rate": abstain / n_qb, "n_ok": ok,
                     "coverage_among_ok": covered / ok if ok else None}
    return out


def e3b_binomial_calibration(trials):
    """Credible-interval coverage of the effective flip estimator vs shots."""
    from qnp import Status
    from qnp.inferred import FlipTally, flip_estimates

    rng = np.random.default_rng(3)
    out = {}
    for p in (0.001, 0.005, 0.02, 0.1):
        for n in (50, 100, 200, 500, 2000, 10_000):
            ok = covered = 0
            for k in rng.binomial(n, p, size=REPS * 10):
                (e,) = flip_estimates({(0, "c"): FlipTally(int(k), n)}, {}, T0, "e3b")
                if e.status is Status.OK:
                    ok += 1
                    covered += e.ci_low <= p <= e.ci_high
            cell = {"abstention_rate": 1 - ok / (REPS * 10),
                    "coverage_among_ok": covered / ok if ok else None}
            out[f"p={p},n={n}"] = cell
            trials.append({"part": "E3b", "p": p, "n": n, **cell})
    return out


def _t1_trial(delays, curve, rng, shots=1000):
    from qnp.measured import estimate_t1

    ones = rng.binomial(shots, np.clip(curve, 0, 1))
    return estimate_t1(0, delays, ones, shots, T0)


def e3c_t1_delay_range(trials):
    """T1 = 100 us, 2% symmetric readout error, delays 0..r*T1."""
    from qnp import Status

    T1, e = 100e-6, 0.02
    rng = np.random.default_rng(4)
    out = {}
    for r in (0.01, 0.05, 0.2, 1, 3, 10):
        delays = np.linspace(0, r * T1, 15)
        curve = (1 - 2 * e) * np.exp(-delays / T1) + e
        stats = {"ok": 0, "covered": 0, "false_conf": 0}
        for rep in range(REPS):
            est = _t1_trial(delays, curve, rng)
            ok = est.status is Status.OK
            cov = ok and est.ci_low <= T1 <= est.ci_high
            stats["ok"] += ok
            stats["covered"] += cov
            stats["false_conf"] += ok and not cov
            trials.append({"part": "E3c", "range_over_T1": r, "rep": rep, "estimate": est.to_dict()})
        out[f"r={r}"] = {"abstention_rate": 1 - stats["ok"] / REPS,
                         "coverage_among_ok": stats["covered"] / stats["ok"] if stats["ok"] else None,
                         "false_confidence_rate": stats["false_conf"] / REPS}
    return out


def e3d_misspecification(trials):
    """Data that violate the single-exponential model."""
    from qnp import Status

    T1, e, r = 100e-6, 0.02, 3
    delays = np.linspace(0, r * T1, 15)
    rng = np.random.default_rng(5)
    out = {}
    # (i) T1 fluctuating between sweep points (TLS-like), median 100 us.
    stats = {"ok": 0, "false_conf": 0}
    for rep in range(REPS):
        t1s = T1 * rng.lognormal(0, 0.3, delays.size)
        est = _t1_trial(delays, (1 - 2 * e) * np.exp(-delays / t1s) + e, rng)
        ok = est.status is Status.OK
        stats["ok"] += ok
        stats["false_conf"] += ok and not (est.ci_low <= T1 <= est.ci_high)
        trials.append({"part": "E3d-fluct", "rep": rep, "estimate": est.to_dict()})
    out["fluctuating_T1"] = {"abstention_rate": 1 - stats["ok"] / REPS,
                             "false_confidence_rate": stats["false_conf"] / REPS}
    # (ii) bi-exponential: no single T1 exists; abstaining is the right answer.
    ok, values = 0, []
    for rep in range(REPS):
        curve = (1 - 2 * e) * (0.7 * np.exp(-delays / T1) + 0.3 * np.exp(-delays / 15e-6)) + e
        est = _t1_trial(delays, curve, rng)
        ok += est.status is Status.OK
        if est.value is not None:
            values.append(est.value)
        trials.append({"part": "E3d-biexp", "rep": rep, "estimate": est.to_dict()})
    out["bi_exponential"] = {"abstention_rate": 1 - ok / REPS,
                             "median_reported_T1_us": float(np.median(values) * 1e6) if values else None}
    return out


def main():
    started = datetime.now(timezone.utc)
    trials: list[dict] = []
    summary = {
        "E3a": e3a_workload_identifiability(trials),
        "E3b": e3b_binomial_calibration(trials),
        "E3c": e3c_t1_delay_range(trials),
        "E3d": e3d_misspecification(trials),
    }
    b_reported = [c["coverage_among_ok"] for c in summary["E3b"].values() if c["coverage_among_ok"] is not None]
    b_low_n = [c["abstention_rate"] for k, c in summary["E3b"].items() if int(k.split("n=")[1]) < 200]
    criteria = [
        Criterion("E3.C1", "f=0 workload: abstention rate", 1.0, summary["E3a"]["f=0"]["abstention_rate"], ">="),
        Criterion("E3.C2", "f>0 workloads: min coverage among OK", 0.90,
                  min(summary["E3a"][k]["coverage_among_ok"] or 0 for k in ("f=0.25", "f=1")), ">="),
        Criterion("E3.C3", "binomial: min coverage over reported cells", 0.90, min(b_reported), ">="),
        Criterion("E3.C4", "binomial: abstention when n < min_shots", 1.0, min(b_low_n), ">="),
        Criterion("E3.C5", "T1 delay range: max false-confidence rate", 0.10,
                  max(c["false_confidence_rate"] for c in summary["E3c"].values()), "<="),
        Criterion("E3.C6", "fluctuating T1: false-confidence rate", 0.10,
                  summary["E3d"]["fluctuating_T1"]["false_confidence_rate"], "<="),
        Criterion("E3.C7", "bi-exponential: abstention rate", 0.50,
                  summary["E3d"]["bi_exponential"]["abstention_rate"], ">="),
    ]
    entry = record("E3_insufficient_evidence", {"reps": REPS}, summary, criteria, trials, started)
    print_entry(entry)


if __name__ == "__main__":
    main()
