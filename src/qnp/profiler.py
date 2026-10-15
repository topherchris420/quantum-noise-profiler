"""Profiler: the one object most users touch."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime
from typing import Any, cast

from .drift import CHANNELS, DriftConfig, GroupReport, SeriesState, analyze_group
from .legacy.v01_drift import LegacyDriftConfig
from .legacy.v01_drift import analyze_series as _legacy_analyze_series
from .models import Alert, Estimate, Status
from .store import EstimateStore


class Profiler:
    """Collects estimates from all three provenance modes and checks them.

    >>> prof = Profiler()
    >>> prof.observe_qiskit_backend(backend)            # OBSERVED
    >>> prof.ingest_qiskit(isa_circuits, job.result())  # INFERRED (+ MEASURED readout probes)
    >>> prof.add(qnp.measured.run_t1(backend, 0, delays))  # MEASURED
    >>> alerts = prof.check()
    >>> reports = prof.report()   # per-group e-values, gates and forecast statuses

    Readout probes (``qnp.measured.readout_probe_circuits``) in a job become
    MEASURED ``readout_error`` series, which carry the absolute recalibration
    threshold; workload circuits become INFERRED effective flip rates with
    exact contexts, monitored for relative change only (v0.3 defaults; see
    ``qnp.drift.WORKLOAD_DEPENDENT``).

    The monitoring family (number of qubits and metrics) is frozen at the
    first ``check()`` unless declared in ``config.budget``; if it later grows,
    ``family["exceeded"]`` is set and the stated error budget no longer holds.
    Pass a ``LegacyDriftConfig`` to run the frozen v0.1 decision rules.
    """

    def __init__(self, store: EstimateStore | None = None, config: DriftConfig | LegacyDriftConfig | None = None):
        self.store = store or EstimateStore()
        self.config = config or DriftConfig()
        self._states: dict[Any, SeriesState] = {}
        self.family: dict[str, Any] = {
            "n_qubits": None,
            "n_metrics": None,
            "n_provenances": None,
            "frozen_at": None,
            "exceeded": False,
            "observed_qubits": 0,
            "observed_metrics": 0,
            "observed_provenances": 0,
        }
        self.notices: list[str] = []

    @property
    def legacy(self) -> bool:
        return isinstance(self.config, LegacyDriftConfig)

    def add(self, estimates: Estimate | Iterable[Estimate]) -> list[Estimate]:
        es = [estimates] if isinstance(estimates, Estimate) else list(estimates)
        self.store.add(es)
        return es

    # -- adapters -------------------------------------------------------------
    def ingest_qiskit(self, circuits, results, timestamp: datetime | None = None, **kw: Any) -> list[Estimate]:
        """``results``: a SamplerV2 ``PrimitiveResult`` (iterates pub results)
        or a list of counts dicts, one per circuit. Keyword arguments go to
        ``qiskit_adapter.estimates_from_results`` (``context_mode="exact"``
        and ``readout_probes="auto"`` by default; ``context_mode="bucket",
        readout_probes="off"`` is the v0.2 behaviour)."""
        from .adapters.qiskit_adapter import estimates_from_results

        return self.add(estimates_from_results(circuits, results, timestamp, **kw))

    def ingest_cirq(self, circuits, results, timestamp: datetime | None = None, **kw: Any) -> list[Estimate]:
        """As ``ingest_qiskit``, for ``cirq.Result`` objects."""
        from .adapters.cirq_adapter import estimates_from_results

        return self.add(estimates_from_results(circuits, results, timestamp, **kw))

    def observe_qiskit_backend(self, backend) -> list[Estimate]:
        from .adapters.qiskit_adapter import observe_backend

        return self.add(observe_backend(backend))

    def observe_qiskit_target(self, target, timestamp: datetime | None = None) -> list[Estimate]:
        from .adapters.qiskit_adapter import observe_target

        return self.add(observe_target(target, timestamp))

    # -- analysis -------------------------------------------------------------
    def mark_recalibrated(self, ts: datetime, qubits: Iterable[int] | None = None, note: str = "") -> None:
        self.store.mark_recalibrated(ts, qubits, note)

    def _groups(self) -> dict[tuple, dict[str, list[Estimate]]]:
        groups: dict[tuple, dict[str, list[Estimate]]] = {}
        for (metric, qubits, ctx, prov), es in self.store.series().items():
            groups.setdefault((metric, qubits, prov), {})[ctx] = es
        return groups

    def _alphas(self, groups) -> dict[str, float]:
        b = cast(DriftConfig, self.config).budget  # only called by reports(), which rejects legacy
        live = [(k, v) for k, v in groups.items() if any(e.status is Status.OK for es in v.values() for e in es)]
        n_q = len({k[1] for k, _ in live})
        n_m = len({k[0] for k, _ in live})
        # provenances per (metric, qubits): each is a separate test of the same quantity
        per_qm: dict[tuple, set] = {}
        for (metric, qubits, prov), _ in live:
            per_qm.setdefault((metric, qubits), set()).add(prov)
        n_p = max((len(v) for v in per_qm.values()), default=0)
        fam = self.family
        fam["observed_qubits"], fam["observed_metrics"], fam["observed_provenances"] = n_q, n_m, n_p
        # Inspecting an empty store must not silently freeze a one-qubit family.
        if not live:
            return {ch: b.alpha_series(ch, b.n_qubits or 1, b.n_metrics or 1, b.n_provenances or 1) for ch in CHANNELS}
        if fam["frozen_at"] is None:
            fam["n_qubits"] = b.n_qubits or n_q
            fam["n_metrics"] = b.n_metrics or n_m
            fam["n_provenances"] = b.n_provenances or n_p
            fam["frozen_at"] = datetime.now().astimezone().isoformat()
        if n_q > fam["n_qubits"] or n_m > fam["n_metrics"] or n_p > fam["n_provenances"]:
            if not fam["exceeded"]:
                self.notices.append(
                    f"monitoring family grew beyond its declaration ({n_q} qubits x {n_m} metrics x "
                    f"{n_p} provenances > {fam['n_qubits']} x {fam['n_metrics']} x {fam['n_provenances']}): "
                    "the session error budget no longer holds; declare budget.n_qubits/n_metrics/n_provenances "
                    "up front or start a new session"
                )
            fam["exceeded"] = True
        return {ch: b.alpha_series(ch, fam["n_qubits"], fam["n_metrics"], fam["n_provenances"]) for ch in CHANNELS}

    def reports(self, now: datetime | None = None) -> list[GroupReport]:
        if self.legacy:
            raise TypeError("reports() needs the v0.2 engine; LegacyDriftConfig only produces alerts")
        config = cast(DriftConfig, self.config)  # not legacy (checked above)
        groups = self._groups()
        alpha = self._alphas(groups)
        out = []
        for (_metric, qubits, _prov), series in sorted(
            groups.items(), key=lambda kv: (kv[0][1], str(kv[0][0]), str(kv[0][2]))
        ):
            rep = analyze_group(series, config, now, self.store.last_recalibration(qubits), alpha, self._states)
            if rep is not None:
                if self.family["exceeded"]:
                    rep.budget_status = "family_exceeded"
                    for channel in (rep.drift, rep.threshold, rep.forecast):
                        if "guarantee" in channel:
                            channel["nominal_guarantee"] = channel["guarantee"]
                        channel["guarantee"] = "unavailable:family_exceeded"
                    rep.alerts = [
                        replace(
                            a,
                            message=f"{a.message} [session error budget exceeded; descriptive alert only]",
                            details={
                                **a.details,
                                "nominal_guarantee": a.details.get("guarantee"),
                                "guarantee": "unavailable:family_exceeded",
                                "budget_status": "family_exceeded",
                            },
                        )
                        for a in rep.alerts
                    ]
                out.append(rep)
        return out

    def check(self, now: datetime | None = None) -> list[Alert]:
        if self.legacy:
            legacy_config = cast(LegacyDriftConfig, self.config)
            alerts: list[Alert] = []
            for (_, qubits, _, _), es in self.store.series().items():
                alerts += _legacy_analyze_series(es, legacy_config, now, self.store.last_recalibration(qubits))
            return alerts
        return [a for rep in self.reports(now) for a in rep.alerts]

    def report(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """JSON-ready per-group reports: e-values, gates, forecast statuses with reasons."""
        return [r.to_dict() for r in self.reports(now)]

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

    def session_report(self, now: datetime | None = None) -> dict[str, Any]:
        """Self-contained, strict-JSON session export, including missing evidence.

        ``within_declared_family`` describes allocation only, not whether the
        statistical assumptions hold on a device. Non-finite diagnostic values
        (e.g. an infinite threshold for a disabled channel) become JSON null.
        Historical ``report()``/``reports()`` retain their numeric behavior.
        """
        reports = self.report(now)
        config = cast(DriftConfig, self.config)

        def finite(value: Any) -> Any:
            if isinstance(value, float) and not math.isfinite(value):
                return None
            if isinstance(value, dict):
                return {k: finite(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [finite(v) for v in value]
            return value

        return cast(
            dict[str, Any],
            finite(
                {
                    "schema_version": 1,
                    "budget_status": (
                        "family_exceeded"
                        if self.family["exceeded"]
                        else "within_declared_family"
                        if self.family["frozen_at"]
                        else "no_data"
                    ),
                    "alpha_session": config.budget.alpha_session,
                    "threshold_mode": "empirically_calibrated" if config.log_e_offset else "nominal",
                    "family": dict(self.family),
                    "notices": list(self.notices),
                    "interpretation": (
                        "Budget allocation is not hardware validation. Channel-specific null assumptions apply."
                    ),
                    "nonfinite_values": "Non-finite diagnostics are null; a zero channel alpha disables that channel.",
                    "reports": reports,
                    "snapshot": self.snapshot(),
                }
            ),
        )
