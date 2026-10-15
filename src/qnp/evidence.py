"""Read recorded Experiment P evidence without provider SDKs or network access.

Checksums establish agreement with the local manifest, not authenticity or
scientific validity. Probe rates and their original homogeneity statistic are
recomputed from counts. Other summaries remain explicitly recorded results.
"""

from __future__ import annotations

import gzip
import hashlib
import itertools
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .stats import reference_homogeneity


class EvidenceError(ValueError):
    """Missing, inconsistent, or unsupported evidence; no report should be emitted."""


def _timestamp(job: dict) -> tuple[str, str]:
    execution = job.get("execution") or {}
    for source, value in (
        ("execution.running", execution.get("running")),
        ("execution.finished", execution.get("finished")),
        ("result_received_at", job.get("result_received_at")),
    ):
        if value:
            try:
                stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            if stamp.tzinfo is not None and stamp.utcoffset() is not None:
                return stamp.astimezone(timezone.utc).isoformat(), source
    raise EvidenceError("probe job has no usable timezone-aware timestamp")


def _manifest(path: Path) -> dict[str, str]:
    entries = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            raise EvidenceError("malformed SHA-256 manifest")
        digest, name = parts
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest) or name in entries:
            raise EvidenceError("malformed or duplicate SHA-256 manifest entry")
        entries[name] = digest
    return entries


def _check(data: bytes, name: str, manifest: dict[str, str]) -> str:
    digest = hashlib.sha256(data).hexdigest()
    if name not in manifest:
        raise EvidenceError(f"not in SHA-256 manifest: {name}; verify the research record first")
    if manifest[name] != digest:
        raise EvidenceError(f"SHA-256 mismatch: {name}; report not generated")
    return digest


def _raw_path(root: Path, name: str) -> Path:
    relative = Path(name)
    if relative.parts[:2] == ("results", "raw"):
        relative = Path(*relative.parts[1:])
    if len(relative.parts) != 2 or relative.parts[0] != "raw":
        raise EvidenceError("raw evidence must be a file directly inside results/raw")
    path = (root / relative).resolve()
    if not path.is_relative_to(root / "raw"):
        raise EvidenceError("raw evidence resolves outside results/raw")
    return path


def _counts(job: dict, prepared: int, width: int) -> tuple[dict[str, int], int]:
    circuits = job["counts"]
    if len(circuits) != 2 or len(circuits[prepared]) != 1:
        raise EvidenceError("expected two parallel probe circuits with one classical register each")
    counts = next(iter(circuits[prepared].values()))
    normalized: dict[str, int] = {}
    for key, value in counts.items():
        bits = key.replace(" ", "")
        if len(bits) != width or set(bits) - {"0", "1"}:
            raise EvidenceError("probe count bitstring does not match the declared qubits")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise EvidenceError("probe counts must be non-negative integers")
        normalized[bits] = normalized.get(bits, 0) + value
    shots = sum(normalized.values())
    if shots <= 0 or shots != job["plan"]["shots"]:
        raise EvidenceError("probe shot count does not match its acquisition plan")
    return normalized, shots


def load_evidence(results_dir: Path, run_id: str | None = None) -> dict[str, Any]:
    """Build portable evidence data; fake/smoke runs cannot become hardware evidence.

    Selects the last eligible completed pilot in append order, or an exact ID.
    Every displayed run entry and its raw file must match the existing manifest.
    """
    root = results_dir.resolve()
    try:
        manifest = _manifest(root / "MANIFEST.sha256")
        rows = []
        seen = set()
        for line in (root / "runs.jsonl").read_bytes().splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry["run_id"] in seen:
                raise EvidenceError("duplicate run ID in research log")
            seen.add(entry["run_id"])
            rows.append((entry, line))

        def eligible(entry: dict) -> bool:
            config = entry.get("config", {})
            return bool(entry.get("finished")) and not any(
                config.get(k) or entry.get(k) for k in ("smoke", "rehearsal")
            )

        pilots = [
            (entry, line)
            for entry, line in rows
            if entry.get("experiment") == "V03_P_pilot"
            and entry.get("config", {}).get("local_simulation") is False
            and eligible(entry)
            and (run_id is None or entry["run_id"] == run_id)
        ]
        if not pilots:
            raise EvidenceError("no completed physical-QPU pilot found; fake and smoke runs are excluded")
        pilot, pilot_line = pilots[-1]
        receipts = []

        def verify(entry: dict, line: bytes) -> bytes:
            entry_hash = _check(line, f"run:{entry['run_id']}", manifest)
            raw_path = _raw_path(root, entry["raw"])
            raw = raw_path.read_bytes()
            name = f"raw/{raw_path.name}"
            raw_hash = _check(raw, name, manifest)
            receipts.append(
                {"run_id": entry["run_id"], "entry_sha256": entry_hash, "raw": name, "raw_sha256": raw_hash}
            )
            return gzip.decompress(raw) if raw_path.suffix == ".gz" else raw

        raw_rows = [json.loads(line) for line in verify(pilot, pilot_line).splitlines() if line.strip()]
        if len(raw_rows) != 1:
            raise EvidenceError("expected one complete pilot record")
        raw = raw_rows[0]
        config, summary = pilot["config"], pilot["summary"]
        qubits = config["qubits"]
        if not qubits or len(set(qubits)) != len(qubits):
            raise EvidenceError("pilot qubits must be distinct and nonempty")
        if summary["qubits"] != qubits or summary["backend"] != config["backend"]:
            raise EvidenceError("pilot identity differs between config and summary")
        if any(j.get("local_simulation") is not False for j in raw["jobs"]):
            raise EvidenceError("hardware record contains a simulated or unclassified job")
        if len(raw["jobs"]) != config["planned"]["jobs"] or len(raw["jobs"]) != summary["timing"]["n_jobs"]:
            raise EvidenceError("completed job count differs from the pilot plan or summary")
        total_shots = sum(j["plan"]["total_shots"] for j in raw["jobs"])
        if total_shots != config["planned"]["shots"]:
            raise EvidenceError("completed shot budget differs from the pilot plan")
        criteria = {c["name"]: c for c in pilot["criteria"]}
        if len(pilot["criteria"]) != 2 or set(criteria) != {"P.C1", "P.C2"}:
            raise EvidenceError("the original P.C1/P.C2 decisions must both be present")
        for name, observed in (("P.C1", summary["P1_n_rejected"]), ("P.C2", summary["P2_n_reference_rejected"])):
            criterion = criteria[name]
            if (
                criterion["observed"] != observed
                or criterion["comparison"] != "<="
                or criterion["threshold"] != 1
                or criterion["passed"] is not (observed <= 1)
            ):
                raise EvidenceError(f"{name} differs from its original registered decision rule")
        probes = [j for j in raw["jobs"] if j["label"].startswith("probe")]
        expected = config["design"]["n_probe_batches"]
        if len(probes) != expected or [j["label"] for j in probes] != [f"probe{i}" for i in range(expected)]:
            raise EvidenceError("probe batches are missing, duplicated or out of order")
        stamps = [_timestamp(j) for j in probes]
        if any(a[0] >= b[0] for a, b in itertools.pairwise(stamps)):
            raise EvidenceError("probe timestamps must increase")
        t0 = datetime.fromisoformat(stamps[0][0])
        batches = [
            {
                "label": job["label"],
                "timestamp": ts,
                "timestamp_source": source,
                "elapsed_minutes": (datetime.fromisoformat(ts) - t0).total_seconds() / 60,
            }
            for job, (ts, source) in zip(probes, stamps)
        ]
        for job in probes:
            if job["plan"]["physical_qubits"] != qubits or not job["plan"]["parallel"]:
                raise EvidenceError("probe layout differs from the declared parallel acquisition")
        series = []
        for index, qubit in enumerate(qubits):
            for prepared, context in enumerate(("p(1|0)", "p(0|1)")):
                key = f"{qubit}:{context}"
                recorded = summary["P1_probe_homogeneity"][key]
                errors, shots = [], []
                for job in probes:
                    counts, n = _counts(job, prepared, len(qubits))
                    k = sum(count for bits, count in counts.items() if int(bits[::-1][index]) != prepared)
                    errors.append(k)
                    shots.append(n)
                rates = [k / n for k, n in zip(errors, shots)]
                if rates != recorded["rates"]:
                    raise EvidenceError(f"raw probe counts disagree with recorded rates: {key}")
                statistic, p, dof = reference_homogeneity(errors, shots)
                if dof != recorded["dof"] or not math.isclose(
                    statistic, recorded["g_statistic"], rel_tol=1e-8, abs_tol=1e-10
                ):
                    raise EvidenceError(f"raw probe counts disagree with recorded homogeneity statistic: {key}")
                if not math.isclose(p, recorded["p"], rel_tol=1e-7, abs_tol=1e-12):
                    raise EvidenceError(f"homogeneity p-value differs from the recorded value: {key}")
                series.append(
                    {
                        "key": key,
                        "qubit": qubit,
                        "context": context,
                        "prepared": prepared,
                        "rates": rates,
                        "errors": errors,
                        "shots": shots,
                        "p": recorded["p"],
                        "dispersion": recorded["dispersion"],
                        "rejected": recorded["p"] < 0.01,
                        "vendor": recorded["vendor"],
                        "pooled": sum(errors) / sum(shots),
                    }
                )
        if sum(s["rejected"] for s in series) != summary["P1_n_rejected"]:
            raise EvidenceError("P.C1 rejection count differs from its series")
        studies = []
        for experiment, title in (
            ("V03_G_workload_probes", "Workload changes"),
            ("V03_H_sweep_drift", "Readout drift during T1 sweeps"),
            ("V03_I_operational", "Operational value"),
        ):
            candidates = [
                (entry, line) for entry, line in rows if entry.get("experiment") == experiment and eligible(entry)
            ]
            if not candidates:
                continue
            entry, line = candidates[-1]
            verify(entry, line)
            studies.append(
                {
                    "title": title,
                    "run_id": entry["run_id"],
                    "criteria": entry["criteria"],
                    "passed": sum(c["passed"] for c in entry["criteria"]),
                    "total": len(entry["criteria"]),
                }
            )
        return {
            "schema_version": 1,
            "evidence_kind": "recorded_hardware_pilot",
            "run_id": pilot["run_id"],
            "backend": summary["backend"],
            "started": pilot["started"],
            "finished": pilot["finished"],
            "source_commit": pilot["environment"]["git_commit"],
            "qubits": qubits,
            "batches": batches,
            "series": series,
            "jobs": len(raw["jobs"]),
            "shots": total_shots,
            "criteria": pilot["criteria"],
            "sweeps": summary["P2_P3_sweeps"],
            "alerts": summary["P4_engine_alerts"],
            "studies": studies,
            "receipts": receipts,
            "verification": {
                "artifact_hashes": "matched_local_manifest",
                "probe_rates_and_homogeneity": "recomputed_from_counts",
                "other_summaries": "recorded_not_recomputed_by_report",
                "hardware_detection_accuracy": "not_established",
                "scope": (
                    "Checksums detect changes against this manifest; "
                    "they are not independent authentication or replication."
                ),
            },
        }
    except EvidenceError:
        raise
    except (OSError, KeyError, TypeError, ValueError, IndexError, EOFError) as exc:
        raise EvidenceError(f"cannot read complete evidence from {root}: {exc}") from exc
