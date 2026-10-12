"""INFERRED mode: what workload results can actually identify.

From ordinary circuit results we can identify, per qubit, the probability that
a qubit whose *ideal* outcome is a deterministic bit is observed flipped. That
rate is a property of (qubit, circuit context): it lumps together state prep,
gate, decoherence and readout error along that qubit's path. It is reported
as ``Metric.EFFECTIVE_FLIP``, never as T1, T2 or readout error.

Qubits whose ideal outcome is not deterministic give no per-qubit evidence and
are reported as INSUFFICIENT_EVIDENCE.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models import Estimate, Metric, Provenance, Status, insufficient
from .stats import beta_interval

FLIP_ASSUMPTIONS = (
    "ideal outcome computed by noiseless simulation of the submitted circuit",
    "rate lumps state-prep, gate, decoherence and readout error for this circuit context",
    "shots are independent and the rate is constant within the batch",
)

# Bucket edges for per-qubit operation counts. Rates are only comparable
# within a bucket: a qubit behind 30 CX gates flips more than an idle one.
_ONEQ_EDGES = (0, 1, 4, 16)
_TWOQ_EDGES = (0, 2, 8)


def _bucket(count: int, edges: tuple[int, ...]) -> str:
    for edge in edges:
        if count <= edge:
            return f"<={edge}"
    return f">{edges[-1]}"


@dataclass(frozen=True)
class QubitIdeal:
    """What the noiseless circuit predicts for one measured qubit."""

    bit: int | None  # deterministic ideal bit, or None if not deterministic
    n_1q: int = 0
    n_2q: int = 0
    reason: str = ""  # why bit is None

    @property
    def context(self) -> str:
        return f"ideal={self.bit}|1q{_bucket(self.n_1q, _ONEQ_EDGES)}|2q{_bucket(self.n_2q, _TWOQ_EDGES)}"


@dataclass
class FlipTally:
    flips: int = 0
    shots: int = 0


def flip_estimates(
    tallies: dict[tuple[int, str], FlipTally],
    unidentified: dict[int, str],
    timestamp: datetime,
    source: str,
    min_shots: int = 200,
    level: float = 0.95,
) -> list[Estimate]:
    """Turn pooled per-(qubit, context) flip tallies into estimates.

    ``unidentified`` maps qubits that were measured but never had a
    deterministic ideal outcome to the reason; they get one
    INSUFFICIENT_EVIDENCE estimate each.
    """
    out: list[Estimate] = []
    covered: set[int] = set()
    for (q, ctx), t in sorted(tallies.items()):
        covered.add(q)
        if t.shots < min_shots:
            out.append(
                insufficient(
                    Metric.EFFECTIVE_FLIP, (q,), Provenance.INFERRED,
                    f"{t.shots} shots < min_shots={min_shots}",
                    timestamp, successes=t.flips, trials=t.shots,
                    context=ctx, source=source, assumptions=FLIP_ASSUMPTIONS,
                )
            )
            continue
        mean, lo, hi = beta_interval(t.flips, t.shots, level)
        out.append(
            Estimate(
                metric=Metric.EFFECTIVE_FLIP, qubits=(q,), provenance=Provenance.INFERRED,
                timestamp=timestamp, status=Status.OK, value=mean,
                ci_low=lo, ci_high=hi, ci_level=level,
                successes=t.flips, trials=t.shots, context=ctx, source=source,
                assumptions=FLIP_ASSUMPTIONS,
            )
        )
    for q, reason in sorted(unidentified.items()):
        if q not in covered:
            out.append(
                insufficient(
                    Metric.EFFECTIVE_FLIP, (q,), Provenance.INFERRED, reason,
                    timestamp, source=source,
                )
            )
    return out


def tally_marginal(
    tallies: dict[tuple[int, str], FlipTally],
    qubit: int,
    ideal: QubitIdeal,
    shots: int,
    ones: int,
) -> None:
    """Add one circuit's marginal outcome counts for a deterministic qubit."""
    assert ideal.bit is not None
    t = tallies.setdefault((qubit, ideal.context), FlipTally())
    t.flips += ones if ideal.bit == 0 else shots - ones
    t.shots += shots
