"""Append-only SQLite store of estimates and recalibration marks."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime

from .models import Estimate

_SCHEMA = """
CREATE TABLE IF NOT EXISTS estimates (
    id INTEGER PRIMARY KEY,
    metric TEXT NOT NULL, qubits TEXT NOT NULL, context TEXT NOT NULL,
    provenance TEXT NOT NULL, status TEXT NOT NULL, ts TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS estimates_series ON estimates (metric, qubits, context, provenance, ts);
CREATE TABLE IF NOT EXISTS recalibrations (
    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, qubits TEXT NOT NULL, note TEXT NOT NULL
);
"""


class EstimateStore:
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path)
        self.conn.executescript(_SCHEMA)

    def add(self, estimates: Iterable[Estimate]) -> int:
        rows = [
            (
                e.metric.value,
                json.dumps(list(e.qubits)),
                e.context,
                e.provenance.value,
                e.status.value,
                e.timestamp.isoformat(),
                json.dumps(e.to_dict()),
            )
            for e in estimates
        ]
        with self.conn:
            self.conn.executemany(
                "INSERT INTO estimates (metric, qubits, context, provenance, status, ts, body) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        return len(rows)

    def all(self) -> list[Estimate]:
        cur = self.conn.execute("SELECT body FROM estimates ORDER BY ts, id")
        return [Estimate.from_dict(json.loads(b)) for (b,) in cur]

    def series(self) -> dict[tuple, list[Estimate]]:
        out: dict[tuple, list[Estimate]] = {}
        for e in self.all():
            out.setdefault(e.series_key, []).append(e)
        return out

    def mark_recalibrated(self, ts: datetime, qubits: Iterable[int] | None = None, note: str = "") -> None:
        """Baselines restart after a recalibration. ``qubits=None`` means all."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO recalibrations (ts, qubits, note) VALUES (?, ?, ?)",
                (ts.isoformat(), json.dumps(None if qubits is None else sorted(qubits)), note),
            )

    def last_recalibration(self, qubits: tuple[int, ...]) -> datetime | None:
        latest = None
        for ts, qs in self.conn.execute("SELECT ts, qubits FROM recalibrations"):
            qs = json.loads(qs)
            if qs is None or set(qubits) & set(qs):
                t = datetime.fromisoformat(ts)
                latest = t if latest is None or t > latest else latest
        return latest
