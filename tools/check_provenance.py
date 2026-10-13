"""Schema and provenance checks for results/runs.jsonl.

* every entry validates against schemas/run_entry.schema.json;
* run IDs are unique and every raw file exists;
* v0.2-era entries (those carrying ``environment_at_start``) must have been
  produced from a clean, unchanged source tree: ``git_dirty`` false at start
  and end, identical source-tree hashes at start and end, identical commits;
* entries in the repository's results/ must not be smoke tests;
* confirmatory v0.2 and v0.3 entries must name their protocol and seed
  block, and their seeds must lie in the preregistered confirmatory ranges;
  a hardware-pilot rehearsal on a fake backend must not be in results/.

    python tools/check_provenance.py [--results-dir DIR] [--allow-smoke]
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIRMATORY = (30_000, 39_999)
D_RANGE = (40_000, 54_999)
CALIBRATION = (20_000, 21_999)
# v0.3 (experiments/V03_PREREGISTRATION.md section 1)
V03_RANGES = {
    "V03_G_workload_probes": (60_000, 69_999),
    "V03_I_operational": (60_000, 69_999),
    "V03_H_sweep_drift": (70_000, 84_999),
}
V03_NEEDS_CALIBRATION = ("V03_G_workload_probes", "V03_I_operational")


def _seeds(entry, results):
    path = results / "raw" / Path(entry["raw"]).name
    data = gzip.decompress(path.read_bytes()).decode() if path.suffix == ".gz" else path.read_text()
    for line in data.splitlines():
        if line.strip():
            t = json.loads(line)
            if "seed" in t:
                yield t["seed"]


def tree_hash_at(commit: str) -> str:
    """source_tree_sha256 (as in experiments/common.py) of src/ and experiments/ at a commit."""
    import hashlib
    import subprocess

    h = hashlib.sha256()
    for sub in ("src", "experiments"):  # same order and path sort as source_tree_hash()
        out = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", commit, "--", sub],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        for f in sorted((x for x in out if x.endswith(".py") and "__pycache__" not in x), key=Path):
            h.update(f.encode())
            h.update(subprocess.run(["git", "show", f"{commit}:{f}"], cwd=ROOT, capture_output=True, check=True).stdout)
    return h.hexdigest()


def main(argv=None) -> int:
    import jsonschema

    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", default=str(ROOT / "results"))
    ap.add_argument("--allow-smoke", action="store_true")
    ap.add_argument("--allow-rehearsal", action="store_true", help="accept fake-backend pilot rehearsals (CI)")
    args = ap.parse_args(argv)
    results = Path(args.results_dir)
    schema = json.loads((ROOT / "schemas" / "run_entry.schema.json").read_text())
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    errors: list[str] = []
    seen: set[str] = set()
    entries = [json.loads(ln) for ln in (results / "runs.jsonl").read_text().splitlines() if ln.strip()]
    exc_path = results / "provenance_exceptions.json"
    exceptions = {x["run_id"]: x for x in json.loads(exc_path.read_text())} if exc_path.exists() else {}
    for e in entries:
        rid = e.get("run_id", "?")
        for err in validator.iter_errors(e):
            errors.append(f"{rid}: schema: {err.message} at {list(err.absolute_path)}")
        if rid in seen:
            errors.append(f"{rid}: duplicate run_id")
        seen.add(rid)
        raw = results / "raw" / Path(e.get("raw", "")).name
        if not raw.exists():
            errors.append(f"{rid}: raw file missing")
        smoke = e.get("config", {}).get("smoke") or "SMOKE" in e.get("notes", "")
        if smoke and not args.allow_smoke:
            errors.append(f"{rid}: smoke-test entry in a results directory that holds evidence")
        start = e.get("environment_at_start")
        if start is not None:
            end = e["environment"]
            if start["git_dirty"] or end["git_dirty"]:
                exc = exceptions.get(rid)
                if exc is None:
                    errors.append(f"{rid}: source tree was dirty (start={start['git_dirty']}, end={end['git_dirty']})")
                elif tree_hash_at(exc["commit"]) != start.get("source_tree_sha256"):
                    errors.append(f"{rid}: documented exception does not verify: tree of {exc['commit'][:8]} differs")
                else:
                    print(f"{rid}: dirty-tree exception verified against commit {exc['commit'][:8]}")
            if start.get("source_tree_sha256") != end.get("source_tree_sha256"):
                errors.append(f"{rid}: source changed while the run was in progress")
            if start["git_commit"] != end["git_commit"] and start.get("source_tree_sha256") == end.get(
                "source_tree_sha256"
            ):
                # commits that do not touch src/ or experiments/ (docs, results) may land during a long run
                print(f"{rid}: note: HEAD moved during the run, source tree unchanged")
        if e["experiment"].startswith("V02_") and not smoke:
            if not e.get("protocol"):
                errors.append(f"{rid}: no protocol recorded")
            lo, hi = (
                CALIBRATION
                if e["experiment"] == "V02_calibration"
                else (D_RANGE if e["experiment"] == "V02_D_misspecification" else CONFIRMATORY)
            )
            bad = [s for s in _seeds(e, results) if not lo <= s <= hi]
            if bad:
                errors.append(f"{rid}: {len(bad)} seeds outside the preregistered range [{lo}, {hi}], e.g. {bad[:3]}")
            if e["experiment"] != "V02_calibration" and e["experiment"] != "V02_D_misspecification":
                if not e["config"].get("calibration_run_id") or e["config"]["calibration_run_id"] not in seen:
                    errors.append(f"{rid}: calibration run missing or recorded after this run")
        if e["experiment"].startswith("V03_") and not smoke:
            if e.get("protocol") != "experiments/V03_PREREGISTRATION.md":
                errors.append(f"{rid}: protocol is not the v0.3 preregistration")
            if e["experiment"] in V03_RANGES:
                lo, hi = V03_RANGES[e["experiment"]]
                bad = [s for s in _seeds(e, results) if not lo <= s <= hi]
                if bad:
                    errors.append(
                        f"{rid}: {len(bad)} seeds outside the preregistered range [{lo}, {hi}], e.g. {bad[:3]}"
                    )
            if e["experiment"] in V03_NEEDS_CALIBRATION:
                if not e["config"].get("calibration_run_id") or e["config"]["calibration_run_id"] not in seen:
                    errors.append(f"{rid}: calibration run missing or recorded after this run")
        if e["experiment"] == "V03_P_pilot" and e["config"].get("rehearsal") and not args.allow_rehearsal:
            errors.append(f"{rid}: a fake-backend rehearsal is not evidence")
    print(f"{len(entries)} entries checked, {len(errors)} problem(s)")
    for x in errors:
        print("  " + x)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
