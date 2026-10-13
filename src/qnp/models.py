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
from typing import Any, cast


class Provenance(str, Enum):
    OBSERVED = "observed"  # read from backend calibration data / metadata
    INFERRED = "inferred"  # identified from workload results under stated assumptions
    MEASURED = "measured"  # determined by dedicated characterization sequences


class Status(str, Enum):
    OK = "ok"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"  # the data cannot support a number
    MODEL_MISSPECIFICATION = "model_misspecification"  # the data contradict the model that would produce it


class ForecastStatus(str, Enum):
    """Why a forecast is, or is not, offered. Every non-valid status comes
    with machine-readable ``Reason`` entries."""

    VALID_FORECAST = "VALID_FORECAST"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"  # trend not statistically supported
    MODEL_MISSPECIFICATION = "MODEL_MISSPECIFICATION"  # linear-trend model does not fit
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"  # too few points or too short a span
    UNSTABLE_TREND = "UNSTABLE_TREND"  # slope not consistent over the history
    UNSUPPORTED_HORIZON = "UNSUPPORTED_HORIZON"  # crossing lies beyond what the data can support


@dataclass(frozen=True)
class Reason:
    """Machine-readable reason attached to a rejected forecast or estimate."""

    code: str
    message: str
    value: float | None = None
    limit: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "value": self.value, "limit": self.limit}


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
    # Structured diagnostics (e.g. goodness-of-fit results for MEASURED fits).
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Fail explicitly on inconsistent input instead of carrying it into
        the analysis (invalid timestamps, impossible counts, NaN values)."""
        import math

        if not isinstance(self.metric, Metric):
            raise TypeError(f"metric must be a Metric, got {self.metric!r}")
        if not isinstance(self.provenance, Provenance):
            raise TypeError(f"provenance must be a Provenance, got {self.provenance!r}")
        if not isinstance(self.status, Status):
            raise TypeError(f"status must be a Status, got {self.status!r}")
        if isinstance(self.qubits, list):
            object.__setattr__(self, "qubits", tuple(self.qubits))
        if (
            not isinstance(self.qubits, tuple)
            or not self.qubits
            or not all(isinstance(q, int) and not isinstance(q, bool) and q >= 0 for q in self.qubits)
        ):
            raise ValueError(f"qubits must be a non-empty tuple of non-negative ints, got {self.qubits!r}")
        if len(set(self.qubits)) != len(self.qubits):
            raise ValueError(f"duplicate qubit index in {self.qubits!r}")
        if not isinstance(self.timestamp, datetime):
            raise TypeError(f"timestamp must be a datetime, got {type(self.timestamp).__name__}")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware (naive datetimes are ambiguous)")
        if isinstance(self.assumptions, list):
            object.__setattr__(self, "assumptions", tuple(self.assumptions))
        for name in ("value", "ci_low", "ci_high", "ci_level"):
            v = getattr(self, name)
            if v is not None:
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    raise TypeError(f"{name} must be a number or None, got {v!r}")
                if not math.isfinite(v):
                    raise ValueError(f"{name} must be finite, got {v!r}")
        if self.status is Status.OK:
            if self.value is None:
                raise ValueError("status OK requires a value")
        else:
            if self.value is not None:
                raise ValueError("INSUFFICIENT_EVIDENCE estimates must not carry a value")
            if not self.reason:
                raise ValueError("INSUFFICIENT_EVIDENCE estimates must give a reason")
        if (self.ci_low is None) != (self.ci_high is None):
            raise ValueError("ci_low and ci_high must be given together")
        if self.ci_low is not None:
            ci_high = cast(float, self.ci_high)  # given together with ci_low (checked above)
            if self.ci_low > ci_high:
                raise ValueError(f"ci_low {self.ci_low} > ci_high {self.ci_high}")
            if self.value is not None and not (self.ci_low - 1e-12 <= self.value <= ci_high + 1e-12):
                raise ValueError(f"value {self.value} outside its interval [{self.ci_low}, {self.ci_high}]")
            if self.ci_level is None or not 0 < self.ci_level < 1:
                raise ValueError("an interval needs ci_level in (0, 1)")
        if (self.successes is None) != (self.trials is None):
            raise ValueError("successes and trials must be given together")
        if self.trials is not None:
            if isinstance(self.trials, bool) or isinstance(self.successes, bool):
                raise TypeError("counts must be ints")
            if not (isinstance(self.trials, int) and isinstance(self.successes, int)):
                raise TypeError("successes and trials must be ints")
            if self.trials < 0 or self.successes < 0 or self.successes > self.trials:
                raise ValueError(f"impossible counts successes={self.successes}, trials={self.trials}")

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
    def from_dict(cls, d: dict[str, Any]) -> Estimate:
        d = dict(d)
        d["metric"] = Metric(d["metric"])
        d["provenance"] = Provenance(d["provenance"])
        d["status"] = Status(d["status"])
        d["timestamp"] = datetime.fromisoformat(d["timestamp"])
        d["qubits"] = tuple(d["qubits"])
        d["assumptions"] = tuple(d["assumptions"])
        d.setdefault("diagnostics", {})
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
