"""Regression tests for machine-readable monitoring-family guarantees."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from qnp import DriftConfig, ErrorBudget, Estimate, Metric, Profiler, Provenance, Status

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def observations(qubit=0):
    return [
        Estimate(
            Metric.READOUT_ERROR,
            (qubit,),
            Provenance.MEASURED,
            T0 + timedelta(minutes=10 * i),
            value=k / 4000,
            successes=k,
            trials=4000,
            context="p(1|0)",
        )
        for i, k in enumerate([80] * 12 + [360] * 8)
    ]


def test_exceeded_budget_is_visible_on_every_alert_and_channel():
    prof = Profiler(config=DriftConfig(budget=ErrorBudget(n_qubits=1, n_metrics=1, n_provenances=1)))
    prof.add(observations(0) + observations(1))
    session = prof.session_report()
    assert session["budget_status"] == "family_exceeded"
    alerts = [a for report in session["reports"] for a in report["alerts"]]
    assert alerts
    for a in alerts:
        assert a["details"]["guarantee"] == "unavailable:family_exceeded"
        assert a["details"]["nominal_guarantee"] in {"exact", "bayesian_marginal", "gaussian_approx"}
        assert "descriptive alert only" in a["message"]
    for report in session["reports"]:
        assert report["budget_status"] == "family_exceeded"
        for channel in ("drift", "threshold", "forecast"):
            assert report[channel]["guarantee"] == "unavailable:family_exceeded"
    assert len(prof.notices) == 1
    assert all(a.details["guarantee"] == "unavailable:family_exceeded" for a in prof.check())
    assert len(prof.notices) == 1


def test_inspecting_empty_or_withheld_data_does_not_freeze_family():
    prof = Profiler()
    assert prof.session_report()["budget_status"] == "no_data"
    prof.add(
        Estimate(
            Metric.T1, (0,), Provenance.MEASURED, T0, status=Status.INSUFFICIENT_EVIDENCE, reason="not enough delays"
        )
    )
    report = prof.session_report()
    assert report["budget_status"] == "no_data" and len(report["snapshot"]) == 1
    assert prof.family["frozen_at"] is None
    prof.add(observations(0) + observations(1))
    assert prof.session_report()["budget_status"] == "within_declared_family"
    assert prof.family["n_qubits"] == 2
    assert not prof.family["exceeded"]


def test_session_export_is_strict_json_with_disabled_channels():
    prof = Profiler(config=DriftConfig(budget=ErrorBudget(shares={"drift": 1.0, "threshold": 0.0, "forecast": 0.0})))
    prof.add(observations())
    data = prof.session_report()
    json.dumps(data, allow_nan=False)
    assert data["reports"][0]["forecast"]["log_e_threshold"] is None
    assert prof.report()[0]["forecast"]["log_e_threshold"] == float("inf")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True])
def test_invalid_budget_shares_cannot_create_silent_invalid_thresholds(value):
    with pytest.raises(ValueError, match="finite"):
        ErrorBudget(shares={"drift": value, "threshold": 0.25, "forecast": 0.25})


@pytest.mark.parametrize("field", ["n_qubits", "n_metrics", "n_provenances"])
def test_booleans_are_not_valid_family_dimensions(field):
    with pytest.raises(ValueError, match="positive int"):
        ErrorBudget(**{field: True})
