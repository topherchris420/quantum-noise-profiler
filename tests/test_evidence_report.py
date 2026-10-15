"""Evidence export must preserve provenance, reject corruption and work offline."""

import base64
import gzip
import hashlib
import json
import re
from pathlib import Path

import pytest

from qnp.cli import main
from qnp.evidence import EvidenceError, load_evidence
from qnp.reporting import render_evidence, write_evidence_report

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def recorded(tmp_path):
    """A portable copy of the completed pilot, without unrelated large studies."""
    root = tmp_path / "results"
    (root / "raw").mkdir(parents=True)
    lines = (ROOT / "results/runs.jsonl").read_bytes().splitlines()
    line = next(line for line in lines if json.loads(line)["experiment"] == "V03_P_pilot")
    entry = json.loads(line)
    (root / "runs.jsonl").write_bytes(line + b"\n")
    (root / "raw" / Path(entry["raw"]).name).write_bytes((ROOT / entry["raw"]).read_bytes())
    (root / "MANIFEST.sha256").write_bytes((ROOT / "results/MANIFEST.sha256").read_bytes())
    return root


def reseal(root, *, entry=None, raw=None):
    """Create an internally checksummed but inconsistent fixture, not evidence."""
    entry = entry or json.loads((root / "runs.jsonl").read_bytes())
    path = root / "raw" / Path(entry["raw"]).name
    if raw is not None:
        path.write_bytes(gzip.compress((json.dumps(raw) + "\n").encode()))
    line = json.dumps(entry).encode()
    (root / "runs.jsonl").write_bytes(line + b"\n")
    (root / "MANIFEST.sha256").write_text(
        f"{hashlib.sha256(line).hexdigest()}  run:{entry['run_id']}\n"
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  raw/{path.name}\n"
    )


def test_reproduces_physical_counts_and_separates_simulations():
    data = load_evidence(ROOT / "results")
    assert data["evidence_kind"] == "recorded_hardware_pilot"
    assert data["jobs"] == 14 and data["shots"] == 296000
    assert len(data["batches"]) == 12 and len(data["series"]) == 10
    assert sum(s["rejected"] for s in data["series"]) == 6
    excursion = next(s for s in data["series"] if s["key"] == "108:p(0|1)")
    assert excursion["errors"][7] == 119 and excursion["shots"][7] == 4000
    assert excursion["rates"][7] == 119 / 4000
    assert data["batches"][0]["timestamp_source"] == "execution.running"
    assert sum(s["total"] for s in data["studies"]) == 40
    assert sum(s["passed"] for s in data["studies"]) == 40
    assert len(data["receipts"]) == 4
    assert data["verification"]["hardware_detection_accuracy"] == "not_established"


@pytest.mark.parametrize("target", ["raw", "run", "manifest"])
def test_tampered_or_missing_hashes_are_rejected(recorded, target):
    if target == "raw":
        path = next((recorded / "raw").iterdir())
        path.write_bytes(path.read_bytes() + b"tampered")
    elif target == "run":
        path = recorded / "runs.jsonl"
        path.write_bytes(path.read_bytes().replace(b'"ibm_fez"', b'"ibm_other"'))
    else:
        (recorded / "MANIFEST.sha256").write_text("")
    with pytest.raises(EvidenceError, match="SHA-256"):
        load_evidence(recorded)


def test_valid_hashes_do_not_override_disagreement_with_counts(recorded):
    entry = json.loads((recorded / "runs.jsonl").read_bytes())
    entry["summary"]["P1_probe_homogeneity"]["108:p(0|1)"]["rates"][0] = 0.25
    reseal(recorded, entry=entry)
    with pytest.raises(EvidenceError, match="raw probe counts disagree"):
        load_evidence(recorded)


@pytest.mark.parametrize("field,value", [("local_simulation", True), ("smoke", True), ("rehearsal", True)])
def test_rehearsals_never_become_hardware_evidence(recorded, field, value):
    entry = json.loads((recorded / "runs.jsonl").read_bytes())
    entry["config"][field] = value
    reseal(recorded, entry=entry)
    with pytest.raises(EvidenceError, match="no completed physical"):
        load_evidence(recorded)


def test_rejects_simulated_job_inside_real_record(recorded):
    raw = json.loads(gzip.decompress(next((recorded / "raw").iterdir()).read_bytes()))
    raw["jobs"][0]["local_simulation"] = True
    reseal(recorded, raw=raw)
    with pytest.raises(EvidenceError, match="simulated or unclassified"):
        load_evidence(recorded)


def test_rejects_wrong_shot_counts_even_if_checksums_match(recorded):
    raw = json.loads(gzip.decompress(next((recorded / "raw").iterdir()).read_bytes()))
    probe = next(j for j in raw["jobs"] if j["label"] == "probe0")
    probe["counts"][0]["c"]["00000"] += 1
    reseal(recorded, raw=raw)
    with pytest.raises(EvidenceError, match="shot count"):
        load_evidence(recorded)


def test_missing_sweep_job_is_not_a_complete_pilot(recorded):
    raw = json.loads(gzip.decompress(next((recorded / "raw").iterdir()).read_bytes()))
    raw["jobs"] = [j for j in raw["jobs"] if j["label"] != "sweep1"]
    reseal(recorded, raw=raw)
    with pytest.raises(EvidenceError, match="completed job count"):
        load_evidence(recorded)


def test_missing_preregistered_decision_cannot_generate_broken_report(recorded):
    entry = json.loads((recorded / "runs.jsonl").read_bytes())
    entry["criteria"] = []
    reseal(recorded, entry=entry)
    with pytest.raises(EvidenceError, match=r"P\.C1/P\.C2 decisions"):
        load_evidence(recorded)


def test_unknown_run_does_not_fall_back_to_a_different_pilot(recorded):
    with pytest.raises(EvidenceError, match="no completed physical"):
        load_evidence(recorded, "unknown")


def test_raw_path_traversal_is_rejected(recorded):
    entry = json.loads((recorded / "runs.jsonl").read_bytes())
    entry["raw"] = "../private.jsonl"
    line = json.dumps(entry).encode()
    (recorded / "runs.jsonl").write_bytes(line)
    (recorded / "MANIFEST.sha256").write_text(f"{hashlib.sha256(line).hexdigest()}  run:{entry['run_id']}\n")
    with pytest.raises(EvidenceError, match="directly inside results/raw"):
        load_evidence(recorded)


def test_html_escapes_metadata_and_hashes_only_executable_script(recorded):
    data = load_evidence(recorded)
    data["backend"] = '</script><script>alert("unsafe")</script>&'
    html = render_evidence(data)
    assert data["backend"] not in html
    payload = re.search(r'<script id="evidence-data" type="application/json">(.*?)</script>', html, re.S)[1]
    assert json.loads(payload)["backend"] == data["backend"]
    script = re.search(r"<script>(.*?)</script>", html, re.S)[1]
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    assert f"script-src 'sha256-{digest}'" in html
    assert "connect-src 'none'" in html and "<script src=" not in html
    assert render_evidence(data) == html


def test_report_never_overwrites_evidence_and_never_clobbers_by_default(recorded, tmp_path):
    with pytest.raises(EvidenceError, match="outside the results"):
        write_evidence_report(recorded, recorded / "evidence.html", force=True)
    output = tmp_path / "evidence.html"
    write_evidence_report(recorded, output)
    before = output.read_bytes()
    with pytest.raises(EvidenceError, match="already exists"):
        write_evidence_report(recorded, output)
    write_evidence_report(recorded, output, force=True)
    assert output.read_bytes() == before


def test_failed_verification_leaves_existing_report_untouched(recorded, tmp_path):
    output = tmp_path / "evidence.html"
    output.write_text("previous report")
    (recorded / "MANIFEST.sha256").write_text("")
    with pytest.raises(EvidenceError):
        write_evidence_report(recorded, output, force=True)
    assert output.read_text() == "previous report"


def test_cli_demo_is_strict_json_and_explicitly_synthetic(capsys):
    assert main(["demo"]) == 0
    output = capsys.readouterr().out
    data = json.loads(output, parse_constant=lambda value: pytest.fail(f"non-JSON constant: {value}"))
    assert data["evidence_kind"] == "synthetic_demonstration"
    assert data["session"]["reports"][0]["alerts"]


def test_cli_errors_are_actionable_and_nonzero(tmp_path, capsys):
    assert main(["report", "--results-dir", str(tmp_path)]) == 2
    assert "cannot read complete evidence" in capsys.readouterr().err
