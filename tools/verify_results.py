"""Verify the integrity of recorded experimental results.

Two independent checks:

1. **Artifact integrity.** Every raw trial file and every entry of
   ``results/runs.jsonl`` listed in ``results/MANIFEST.sha256`` must still hash
   to the recorded value. ``runs.jsonl`` is append-only: new entries are allowed,
   recorded entries must be byte-identical.
2. **Recomputation.** For the v0.1 experiments (E1, E2, E3) the summary
   statistics and criteria in ``runs.jsonl`` are recomputed from the raw
   per-trial logs with code that is independent of ``experiments/`` and must
   agree to floating-point precision. v0.2 experiments register their own
   ``recompute_summary(trials, config)`` through ``experiments/v02/registry.py``
   and are checked the same way.

Usage::

    python tools/verify_results.py            # verify
    python tools/verify_results.py --update   # add manifest entries for new runs

Exit status is non-zero on any failure, so CI can run it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
MANIFEST = RESULTS / "MANIFEST.sha256"
TOL = 1e-9


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(p.read_bytes())


# --------------------------------------------------------------------------- manifest

def read_manifest() -> dict[str, str]:
    if not MANIFEST.exists():
        return {}
    out = {}
    for line in MANIFEST.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        digest, name = line.split(maxsplit=1)
        out[name.strip()] = digest.strip()
    return out


def write_manifest(entries: dict[str, str]) -> None:
    lines = ["# sha256 of raw result files and of individual runs.jsonl entries (run:<run_id>).",
             "# Append-only: entries are never removed or changed. Verified by tools/verify_results.py."]
    lines += [f"{d}  {n}" for n, d in sorted(entries.items())]
    MANIFEST.write_text("\n".join(lines) + "\n")


def current_entries() -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted((RESULTS / "raw").glob("*.jsonl")):
        out[f"raw/{p.name}"] = sha256_file(p)
    for line in (RESULTS / "runs.jsonl").read_text().splitlines():
        if line.strip():
            out[f"run:{json.loads(line)['run_id']}"] = sha256_bytes(line.encode())
    return out


def check_manifest(errors: list[str]) -> None:
    recorded = read_manifest()
    current = current_entries()
    for name, digest in recorded.items():
        if name not in current:
            errors.append(f"manifest entry missing from results: {name}")
        elif current[name] != digest:
            errors.append(f"hash mismatch: {name}")
    new = sorted(set(current) - set(recorded))
    if new:
        print(f"note: {len(new)} result artifact(s) not yet in the manifest (run with --update): " + ", ".join(new[:5]))
    print(f"manifest: {len(recorded)} entries verified, {len(errors)} problem(s)")


# --------------------------------------------------------------------------- v0.1 recomputation

def _first(log, pred):
    for b in log:
        if any(pred(a) for a in b["alerts"]):
            return b["i"]
    return None


def _finite(xs):
    return [x for x in xs if x is not None]


def recompute_e1(trials, config):
    thr, lo, hi, nb = config["threshold"], *config["ramp"], config["n_batches"]
    i_cross = (thr - lo) / ((hi - lo) / (nb - 1))
    minutes = config["batch_minutes"]

    def q0(kinds, levels=None):
        return lambda a: a["qubit"] == 0 and a["kind"] in kinds and (levels is None or a["level"] in levels)

    early, pl, nl, ca, cw, cn = [], [], [], [], [], []
    for t in trials:
        ip = _first(t["ramp"], q0({"forecast", "threshold"}))
        iv = next((b["i"] for b in t["ramp"] if b["naive"][0] > thr), None)
        early.append(ip is not None and ip < i_cross)
        pl.append(None if ip is None else (i_cross - ip) * minutes)
        nl.append(None if iv is None else (i_cross - iv) * minutes)
        ca.append(_first(t["control"], q0({"forecast", "threshold", "drift"})) is not None)
        cw.append(_first(t["control"], q0({"forecast", "threshold", "drift"}, {"WARNING", "CRITICAL"})) is not None)
        cn.append(any(b["naive"][0] > thr for b in t["control"]))
    return {
        "n_seeds": len(trials),
        "true_crossing_minutes": i_cross * minutes,
        "profiler_early_fraction": float(np.mean(early)),
        "profiler_median_lead_min": float(np.median(_finite(pl))),
        "naive_median_lead_min": float(np.median(_finite(nl))),
        "profiler_never_alerted": sum(x is None for x in pl),
        "control_profiler_any_alert_rate": float(np.mean(ca)),
        "control_profiler_warning_rate": float(np.mean(cw)),
        "control_naive_false_alarm_rate": float(np.mean(cn)),
    }


def recompute_e2(trials, config):
    step, shots, nb = config["step_at"], config["shots"], config["n_batches"]
    ratios = config["ratios"]
    alarm_levels = {"WARNING", "CRITICAL"}

    def alarm(q):
        return lambda a: a["qubit"] == q and a["level"] in alarm_levels and a["kind"] in ("drift", "threshold")

    def shewhart_first(log, qubit=0, ref=10):
        base = np.mean([b["naive"][qubit] for b in log[:ref]])
        sigma = np.sqrt(base * (1 - base) / (2 * shots))
        return next((b["i"] for b in log[ref:] if b["naive"][qubit] > base + 3 * sigma), None)

    delays = {k: [] for k in ratios}
    shew = {k: [] for k in ratios}
    false_runs, shew_false = [], []
    for t in trials:
        name, log = t["condition"], t["log"]
        ratio = ratios[name]
        pre = [b for b in log if b["i"] < step] if ratio != 1.0 else log
        false = any(alarm(0)(a) for b in pre for a in b["alerts"]) or any(alarm(1)(a) for b in log for a in b["alerts"])
        post = [b for b in log if b["i"] >= step]
        i_det = _first(post, alarm(0)) if ratio != 1.0 else None
        i_sh = shewhart_first(log)
        false_runs.append(false)
        shew_false.append(i_sh is not None and (ratio == 1.0 or i_sh < step))
        if ratio != 1.0:
            delays[name].append(None if i_det is None else i_det - step)
            shew[name].append(None if (i_sh is None or i_sh < step) else i_sh - step)

    def within(xs, k):
        return float(np.mean([x is not None and x <= k for x in xs]))

    def med(xs):
        f = _finite(xs)
        return float(np.median(f)) if f else None

    s = {"n_seeds_per_condition": len(trials) // len(ratios)}
    for name in ("x1.5", "x1.2", "x1.1"):
        s[f"{name}_detect_rate_any"] = within(delays[name], nb)
        s[f"{name}_median_delay_batches"] = med(delays[name])
        s[f"{name}_shewhart_detect_rate_any"] = within(shew[name], nb)
        s[f"{name}_shewhart_median_delay_batches"] = med(shew[name])
    s["x1.5_within_6"] = within(delays["x1.5"], 6)
    s["x1.2_within_24"] = within(delays["x1.2"], 24)
    s["x1.1_within_5"] = within(delays["x1.1"], 5)
    s["false_alarm_run_rate"] = float(np.mean(false_runs))
    s["shewhart_false_alarm_run_rate"] = float(np.mean(shew_false))
    return s


def recompute_e3(trials, config):
    t1 = 100e-6
    out: dict = {"E3a": {}, "E3b": {}, "E3c": {}, "E3d": {}}
    for name in ("f=0", "f=0.25", "f=1"):
        ts = [t for t in trials if t["part"] == "E3a" and t["workload"] == name]
        ab = ok = cov = 0
        for t in ts:
            for q in (0, 1):
                good = [e for e in t["estimates"] if e["qubits"] == [q] and e["status"] == "ok"]
                ab += not good
                ok += len(good)
                cov += sum(e["ci_low"] <= 0.03 <= e["ci_high"] for e in good)
        out["E3a"][name] = {"abstention_rate": ab / (2 * len(ts)), "n_ok": ok, "coverage_among_ok": cov / ok if ok else None}
    for t in trials:
        if t["part"] == "E3b":
            out["E3b"][f"p={t['p']},n={t['n']}"] = {"abstention_rate": t["abstention_rate"], "coverage_among_ok": t["coverage_among_ok"]}
    for r in (0.01, 0.05, 0.2, 1, 3, 10):
        ts = [t for t in trials if t["part"] == "E3c" and t["range_over_T1"] == r]
        ok = [t for t in ts if t["estimate"]["status"] == "ok"]
        cov = sum(t["estimate"]["ci_low"] <= t1 <= t["estimate"]["ci_high"] for t in ok)
        out["E3c"][f"r={r}"] = {"abstention_rate": 1 - len(ok) / len(ts),
                                "coverage_among_ok": cov / len(ok) if ok else None,
                                "false_confidence_rate": (len(ok) - cov) / len(ts)}
    fl = [t for t in trials if t["part"] == "E3d-fluct"]
    ok = [t for t in fl if t["estimate"]["status"] == "ok"]
    out["E3d"]["fluctuating_T1"] = {
        "abstention_rate": 1 - len(ok) / len(fl),
        "false_confidence_rate": sum(not (t["estimate"]["ci_low"] <= t1 <= t["estimate"]["ci_high"]) for t in ok) / len(fl),
    }
    bi = [t for t in trials if t["part"] == "E3d-biexp"]
    ok = [t for t in bi if t["estimate"]["status"] == "ok"]
    out["E3d"]["bi_exponential"] = {
        "abstention_rate": 1 - len(ok) / len(bi),
        "median_reported_T1_us": float(np.median([t["estimate"]["value"] for t in ok]) * 1e6) if ok else None,
    }
    return out


V01_RECOMPUTE = {"E1_gradual_drift": recompute_e1, "E2_sudden_degradation": recompute_e2,
                 "E3_insufficient_evidence": recompute_e3}


def _flatten(d, prefix=""):
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        elif isinstance(v, (list, tuple)):
            for i, x in enumerate(v):
                if isinstance(x, dict):
                    out.update(_flatten(x, f"{key}[{i}]."))
                else:
                    out[f"{key}[{i}]"] = x
        else:
            out[key] = v
    return out


def compare(recorded: dict, recomputed: dict, run_id: str, errors: list[str]) -> int:
    a, b = _flatten(recorded), _flatten(recomputed)
    n = 0
    for k, v in b.items():
        if k not in a:
            errors.append(f"{run_id}: recomputed key {k} absent from recorded summary")
            continue
        r = a[k]
        if isinstance(r, str) or isinstance(v, str):
            same = str(r) == str(v)
        else:
            same = (r is None and v is None) or (
                r is not None and v is not None and abs(float(r) - float(v)) <= TOL * max(1.0, abs(float(r)))
            )
        if not same:
            errors.append(f"{run_id}: {k} recorded={r} recomputed={v}")
        n += 1
    return n


def check_criteria(entry: dict, errors: list[str]) -> None:
    for c in entry["criteria"]:
        passed = c["observed"] >= c["threshold"] if c["comparison"] == ">=" else c["observed"] <= c["threshold"]
        if passed != c["passed"]:
            errors.append(f"{entry['run_id']}: criterion {c['name']} recorded passed={c['passed']} but observed {c['observed']} {c['comparison']} {c['threshold']} gives {passed}")
    if entry["passed_all"] != all(c["passed"] for c in entry["criteria"]):
        errors.append(f"{entry['run_id']}: passed_all inconsistent with criteria")


def recompute_functions() -> dict:
    fns = dict(V01_RECOMPUTE)
    try:
        sys.path.insert(0, str(ROOT / "experiments"))
        from v02.registry import RECOMPUTE  # type: ignore

        fns.update(RECOMPUTE)
    except ImportError:
        pass
    return fns


def check_runs(errors: list[str]) -> None:
    fns = recompute_functions()
    for line in (RESULTS / "runs.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        rid = entry["run_id"]
        raw = ROOT / entry["raw"]
        if not raw.exists():
            errors.append(f"{rid}: raw file missing: {entry['raw']}")
            continue
        trials = [json.loads(ln) for ln in raw.read_text().splitlines() if ln.strip()]
        check_criteria(entry, errors)
        fn = fns.get(entry["experiment"])
        if fn is None:
            print(f"{rid}: {len(trials)} raw trials; no recomputation registered for {entry['experiment']}")
            continue
        n = compare(entry["summary"], fn(trials, entry["config"]), rid, errors)
        print(f"{rid}: {len(trials)} raw trials; {n} summary values recomputed")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--update", action="store_true", help="add manifest entries for artifacts not yet listed")
    args = ap.parse_args(argv)
    errors: list[str] = []
    if args.update:
        entries = read_manifest()
        for name, digest in current_entries().items():
            if name in entries and entries[name] != digest:
                errors.append(f"refusing to update: recorded artifact changed: {name}")
            entries.setdefault(name, digest)
        if errors:
            print("\n".join(errors))
            return 1
        write_manifest(entries)
        print(f"manifest written with {len(entries)} entries")
    check_manifest(errors)
    check_runs(errors)
    if errors:
        print("\nFAILED:\n  " + "\n  ".join(errors))
        return 1
    print("\nOK: all recorded results verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
