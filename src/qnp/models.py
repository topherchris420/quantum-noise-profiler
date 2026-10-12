"""Core data model.

Every number the profiler emits is an ``Estimate`` that carries its provenance
(how we know it), its uncertainty, and the assumptions it rests on. When the
data cannot support a number, the estimate's status is INSUFFICIENT_EVIDENCE
and ``value`` is None -- we never fill the gap with a guess.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Provenance(str, Enum):
    OBSERVED = "observed"  # read from backend calibration data / metadata
    INFERRED = "inferred"  # identified from workload results under stated assumptions
    MEASURED = "measured"  # determined by dedicated characterization sequences


class Status(str, Enum):
    OK = "ok"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class Metric(str, Enum):
    T1 = "t1_s"
    T2 = "t2_s"  # Hahn-echo T2 (what IBM reports); T2* (Ramsey) is not T2
    READOUT_ERROR = "readout_error"  # vendor-reported assignment error
    GATE_ERROR = "gate_error"  # vendor-reported, per instruction + qubits
    # Inferred from workload: probability that a qubit whose ideal outcome is a
    # deterministic bit is observed flipped. Conflates SPAM, gate and
    # decoherence error for that circuit context -- it is NOT readout error.
    EFFECTIVE_FLIP = "effective_flip_rate"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Estimate:
    metric: Metric
    qubits: tuple[int, ...]
    provenance: Provenance
    timestamp: datetime
    status: Status = Status.OK
    value: float | None = None
    # Credible (MEASURED/INFERRED) or vendor-reported (OBSERVED) interval. None
    # when the source provides no uncertainty -- not "zero uncertainty".
    ci_low: float | None = None
    ci_high: float | None = None
    ci_level: float | None = None
    # Sufficient statistics for binomial metrics (flips, shots); lets drift
    # detection pool batches exactly instead of averaging point estimates.
    successes: int | None = None
    trials: int | None = None
    # Distinguishes non-comparable series, e.g. instruction name for gate
    # errors, or circuit-context bucket and ideal bit for EFFECTIVE_FLIP.
    context: str = ""
    source: str = ""
    assumptions: tuple[str, ...] = ()
    reason: str = ""  # why INSUFFICIENT_EVIDENCE, when it is

    @property
    def series_key(self) -> tuple[str, tuple[int, ...], str, str]:
        """Estimates are only compared within one series: same metric, qubits,
        context AND provenance. Observed and measured T1 are never mixed."""
        return (self.metric.value, self.qubits, self.context, self.provenance.value)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["metric"] = self.metric.value
        d["provenance"] = self.provenance.value
        d["status"] = self.status.value
        d["timestamp"] = self.timestamp.isoformat()
        d["qubits"] = list(self.qubits)
        d["assumptions"] = list(self.assumptions)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Estimate":
        d = dict(d)
        d["metric"] = Metric(d["metric"])
        d["provenance"] = Provenance(d["provenance"])
        d["status"] = Status(d["status"])
        d["timestamp"] = datetime.fromisoformat(d["timestamp"])
        d["qubits"] = tuple(d["qubits"])
        d["assumptions"] = tuple(d["assumptions"])
        return cls(**d)


def insufficient(
    metric: Metric,
    qubits: tuple[int, ...],
    provenance: Provenance,
    reason: str,
    timestamp: datetime | None = None,
    **kw: Any,
) -> Estimate:
    return Estimate(
        metric=metric,
        qubits=qubits,
        provenance=provenance,
        timestamp=timestamp or utcnow(),
        status=Status.INSUFFICIENT_EVIDENCE,
        reason=reason,
        **kw,
    )


class AlertLevel(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class Alert:
    level: AlertLevel
    kind: str  # "drift" | "threshold" | "forecast"
    metric: Metric
    qubits: tuple[int, ...]
    provenance: Provenance
    context: str
    message: str
    timestamp: datetime
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "kind": self.kind,
            "metric": self.metric.value,
            "qubits": list(self.qubits),
            "provenance": self.provenance.value,
            "context": self.context,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
        }
