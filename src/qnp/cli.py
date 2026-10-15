"""Local entry points for inspecting evidence and trying the core monitor."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import __version__
from .drift import DriftConfig, ErrorBudget
from .evidence import EvidenceError
from .models import Estimate, Metric, Provenance
from .profiler import Profiler
from .reporting import write_evidence_report


def demo() -> dict:
    """Deterministic synthetic counts: a demonstration, never research evidence."""
    prof = Profiler(config=DriftConfig(budget=ErrorBudget(n_qubits=1, n_metrics=1, n_provenances=1)))
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i, errors in enumerate([80] * 12 + [320] * 8):
        prof.add(
            Estimate(
                Metric.READOUT_ERROR,
                (0,),
                Provenance.MEASURED,
                start + timedelta(minutes=10 * i),
                value=errors / 4000,
                successes=errors,
                trials=4000,
                context="p(1|0)",
                source="synthetic CLI demonstration; not hardware or a validation experiment",
            )
        )
    return {"evidence_kind": "synthetic_demonstration", "session": prof.session_report()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="qnp", description="Inspect qubit-noise evidence locally. No quantum jobs are submitted."
    )
    parser.add_argument("--version", action="version", version=f"qnp {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    report = commands.add_parser("report", help="build an offline explorer of recorded Experiment P evidence")
    report.add_argument(
        "--results-dir",
        type=Path,
        default=Path("results"),
        help="directory containing runs.jsonl, raw/ and MANIFEST.sha256",
    )
    report.add_argument("--run-id", help="exact completed physical-QPU pilot ID (default: last eligible entry)")
    report.add_argument("--output", type=Path, default=Path("qnp-evidence.html"))
    report.add_argument(
        "--force", action="store_true", help="replace an existing HTML report; never the results directory"
    )
    commands.add_parser("demo", help="print a deterministic synthetic session as strict JSON; no SDKs or credentials")
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            print(json.dumps(demo(), indent=2, allow_nan=False))
        else:
            path = write_evidence_report(args.results_dir, args.output, args.run_id, force=args.force)
            print(f"Evidence explorer: {path}")
            print("Open this HTML file in a browser. Works offline; no credentials or quantum SDKs required.")
            print("Hashes checked; probe rates and homogeneity recomputed. Hardware alert accuracy is not established.")
    except (EvidenceError, OSError) as exc:
        print(f"qnp: {exc}", file=sys.stderr)
        return 2
    return 0
