"""Regression tests for descriptive pilot diagnostics; no QPU calls."""

import json

import pytest

from tools.pilot_diagnostics import describe_rates, load_hardware_pilot


def test_steady_series_has_no_excess_variance():
    d = describe_rates([0.02] * 12)
    assert d["variance_ratio"] == 0.0
    assert d["lag1_descriptive"] is None


def test_excursion_series_shows_excess_variance():
    d = describe_rates([0.01] * 6 + [0.03] * 6)
    assert d["mean"] == pytest.approx(0.02)
    assert d["variance_ratio"] > 10
    assert d["max"] == pytest.approx(0.03)


@pytest.mark.parametrize("rates,shots", [
    ([0.1, 0.2], 4000),
    ([0.1, -0.2, 0.3], 4000),
    ([0.1, 0.2, 0.3], 0),
])
def test_malformed_rates_fail_closed(rates, shots):
    with pytest.raises(ValueError):
        describe_rates(rates, shots)


def test_only_completed_real_hardware_record_is_selected(tmp_path):
    path = tmp_path / "runs.jsonl"
    records = [
        {"experiment": "V03_P_pilot", "run_id": "fake", "config": {"local_simulation": True}},
        {"experiment": "V03_P_pilot", "run_id": "real", "config": {"local_simulation": False}},
    ]
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    assert load_hardware_pilot(path)["run_id"] == "real"
    with pytest.raises(ValueError, match="no completed"):
        load_hardware_pilot(path, "fake")
