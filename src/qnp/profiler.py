"""Profiler: the one object most users touch."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from .drift import DriftConfig, analyze_series
from .models import Alert, Estimate, Status
from .store import EstimateStore


class Profiler:
    """Collects estimates from all three provenance modes and checks them.

    >>> prof = Profiler()
    >>> prof.observe_qiskit_backend(backend)            # OBSERVED
    >>> prof.ingest_qiskit(isa_circuits, job.result())  # INFERRED
    >>> prof.add(qnp.measured.run_t1(backend, 0, delays))  # MEASURED
    >>> alerts = prof.check()
    """

    def __init__(self, store: EstimateStore | None = None, config: DriftConfig | None = None):
        self.store = store or EstimateStore()
        self.config = config or DriftConfig()

    def add(self, estimates: Estimate | Iterable[Estimate]) -> list[Estimate]:
        es = [estimates] if isinstance(estimates, Estimate) else list(estimates)
        self.store.add(es)
        return es

    # -- adapters -------------------------------------------------------------
    def ingest_qiskit(self, circuits, results, timestamp: datetime | None = None, **kw: Any) -> list[Estimate]:
        """``results``: a SamplerV2 ``PrimitiveResult`` (iterates pub results)
        or a list of counts dicts, one per circuit."""
        from .adapters.qiskit_adapter import infer_from_results

        return self.add(infer_from_results(circuits, results, timestamp, **kw))

    def ingest_cirq(self, circuits, results, timestamp: datetime | None = None, **kw: Any) -> list[Estimate]:
        from .adapters.cirq_adapter import infer_from_results

        return self.add(infer_from_results(circuits, results, timestamp, **kw))

    def observe_qiskit_backend(self, backend) -> list[Estimate]:
        from .adapters.qiskit_adapter import observe_backend

        return self.add(observe_backend(backend))

    def observe_qiskit_target(self, target, timestamp: datetime | None = None) -> list[Estimate]:
        from .adapters.qiskit_adapter import observe_target

        return self.add(observe_target(target, timestamp))

    # -- analysis -------------------------------------------------------------
    def mark_recalibrated(self, ts: datetime, qubits: Iterable[int] | None = None, note: str = "") -> None:
        self.store.mark_recalibrated(ts, qubits, note)

    def check(self, now: datetime | None = None) -> list[Alert]:
        alerts: list[Alert] = []
        for (_, qubits, _, _), es in self.store.series().items():
            alerts += analyze_series(es, self.config, now, self.store.last_recalibration(qubits))
        return alerts

    def snapshot(self) -> list[dict[str, Any]]:
        """Latest estimate per series, including INSUFFICIENT_EVIDENCE ones,
        so gaps in knowledge are visible rather than silently absent."""
        out = []
        for es in self.store.series().values():
            latest = max(es, key=lambda e: e.timestamp)
            ok = [e for e in es if e.status is Status.OK]
            d = latest.to_dict()
            d["n_estimates"], d["n_ok"] = len(es), len(ok)
            out.append(d)
        return sorted(out, key=lambda d: (d["qubits"], d["metric"], d["provenance"], d["context"]))
