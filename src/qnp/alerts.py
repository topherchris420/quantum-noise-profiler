"""Alert rendering: JSON for control systems, text for humans."""

from __future__ import annotations

import json
from collections.abc import Iterable

from .models import Alert, AlertLevel

_ORDER = {AlertLevel.CRITICAL: 0, AlertLevel.WARNING: 1, AlertLevel.INFO: 2}


def sort_alerts(alerts: Iterable[Alert]) -> list[Alert]:
    return sorted(alerts, key=lambda a: (_ORDER[a.level], a.qubits, a.metric.value, a.context))


def to_json(alerts: Iterable[Alert], indent: int | None = 2) -> str:
    return json.dumps([a.to_dict() for a in sort_alerts(alerts)], indent=indent, default=str)


def format_text(alerts: Iterable[Alert]) -> str:
    lines = [f"[{a.level.value:<8}] ({a.provenance.value}) {a.message}" for a in sort_alerts(alerts)]
    return "\n".join(lines) if lines else "No alerts."
