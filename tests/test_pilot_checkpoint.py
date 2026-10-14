"""Local-only checkpoint guarantees for interrupted Experiment P sessions."""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

from v03 import pilot as P
from v03.checkpoints import PilotCheckpoint


def test_checkpoint_writes_atomic_private_events(tmp_path):
    journal = PilotCheckpoint(tmp_path)
    assert journal.directory.parent == tmp_path
    assert journal.directory.is_dir()
    path = journal.record("job_submitted", {"job_id": "qpu123", "label": "probe0"})
    assert json.loads(path.read_text()) == {
        "payload": {"job_id": "qpu123", "label": "probe0"},
        "stage": "job_submitted",
    }
    path2 = journal.record("job_completed", {"label": "probe0", "counts": [{"c": {"0": 5}}]})
    assert path != path2
    assert sorted(p.name for p in journal.directory.iterdir()) == ["000_job_submitted.json", "001_job_completed.json"]
    assert (os.stat(journal.directory).st_mode & 0o077) == 0 if os.name == "posix" else True


def test_submission_id_is_saved_even_if_result_raises(tmp_path):
    journal = PilotCheckpoint(tmp_path)

    class FailedJob:
        def result(self):
            raise RuntimeError("connection lost after submission")

    class Session:
        def submit(self, plan, authorize=False):
            assert authorize
            return {
                "status": "submitted",
                "job": FailedJob(),
                "job_id": "id-123",
                "requested_at": "2026-10-13T20:00:00+00:00",
            }

    plan = SimpleNamespace(summary=lambda: {"n_circuits": 2})
    with pytest.raises(RuntimeError, match="connection lost"):
        P._run(Session(), plan, "probe0", on_submitted=lambda data: journal.record("job_submitted", data))
    events = [json.loads(p.read_text()) for p in journal.directory.glob("*.json")]
    assert len(events) == 1
    assert events[0]["payload"]["job_id"] == "id-123"


def test_completed_jobs_survive_interrupted_sequence(tmp_path, monkeypatch):
    journal = PilotCheckpoint(tmp_path)

    class Session:
        backend = object()
        log = []

        def snapshot(self, qubits):
            return {"backend_name": "fake", "qubits": {}}

    monkeypatch.setattr(P, "calibration_history_probe", lambda b: {"available": False})
    calls = []

    def fail_third(session, plan, label, on_submitted=None):
        if on_submitted is not None:
            on_submitted({"label": label, "job_id": "id-" + label})
        calls.append(label)
        if len(calls) == 3:
            raise KeyboardInterrupt()
        return {"label": label, "counts": []}

    monkeypatch.setattr(P, "_run", fail_third)
    plans = {"sweep0": object(), "sweep1": object(), "probe": object()}
    with pytest.raises(KeyboardInterrupt):
        P.execute(Session(), plans, [0], interval_s=0, checkpoint=journal.record)

    records = [json.loads(p.read_text()) for p in sorted(journal.directory.glob("*.json"))]
    labels = [r["payload"]["label"] for r in records if r["stage"] == "job_completed"]
    assert labels == ["sweep0", "probe0"]
    assert any(r["stage"] == "job_submitted" and r["payload"]["label"] == "probe1" for r in records)
    assert not any(r["stage"] == "session_completed" for r in records)


def test_invalid_stage_is_rejected(tmp_path):
    journal = PilotCheckpoint(tmp_path)
    with pytest.raises(ValueError, match="stage"):
        journal.record("../unsafe", {"ok": True})
