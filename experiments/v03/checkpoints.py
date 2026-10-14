"""Crash-resilient, local-only journal for an authorized Experiment P run.

A job's ID is fsynced immediately after submission; its counts are fsynced
after completion. Files are atomic JSON events in one unique directory per
run. A partial run is NOT a preregistered complete observation and is never
stitched into another run or automatically resumed.

No credentials are recorded. This is a local recovery trail, not a public
research result. Review and sanitize files before sharing them.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common import _jsonable


class PilotCheckpoint:
    """Write individual events atomically to a private per-run directory."""

    def __init__(self, root: str | Path | None = None):
        base = Path(root).expanduser() if root is not None else Path.home() / ".qnp" / "pilot-checkpoints"
        base.mkdir(parents=True, exist_ok=True)
        self.directory = base / f"pilot-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:10]}"
        self.directory.mkdir(mode=0o700)
        if os.name == "posix":
            self.directory.chmod(0o700)
        self._counter = 0

    def record(self, stage: str, payload: dict[str, Any]) -> Path:
        if not stage or not all(c.islower() or c == "_" for c in stage):
            raise ValueError("stage must be a lowercase identifier")
        path = self.directory / f"{self._counter:03d}_{stage}.json"
        fd, tmp = tempfile.mkstemp(prefix=".partial-", suffix=".json", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(
                    {"stage": stage, "payload": payload},
                    stream,
                    default=_jsonable,
                    allow_nan=False,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, path)
            self._counter += 1
            return path
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
