"""Regression tests for descriptive pilot diagnostics; no QPU calls."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.pilot_diagnostics import describe_rates, load_hardware_pilot, multiplicity_sensitivity


def test_steady_series_has_no_excess_variance():
    d = describe_rates([0.02] * 12)
    assert d["variance_ratio"] == 0.0
    assert d["lag1_descriptive"] is None


def test_excursion_series_shows_excess_variance():
    d = describe_rates([0.01] * 6 + [0.03] * 6)
    assert d["mean"] == pytest.approx(0.02)
    assert d["variance_ratio"] > 10
    assert d["max"] == pytest.approx(0.03)


@pytest.mark.parametrize(
    "rates,shots",
    [
        ([0.1, 0.2], 4000),
        ([0.1, -0.2, 0.3], 4000),
        ([0.1, 0.2, 0.3], 0),
    ],
)
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


def test_multiplicity_handles_monotonicity_and_zero_observed():
    got = multiplicity_sensitivity({"last": 0.006, "first": 0.004, "middle": 0.005})
    assert got["holm_adjusted_p_values"] == pytest.approx({"first": 0.012, "middle": 0.012, "last": 0.012})
    assert got["markov_upper_at_observed"] == pytest.approx(0.01)
    assert multiplicity_sensitivity({"a": 0.01, "b": 1.0})["markov_upper_at_observed"] == 1.0
    with pytest.raises(ValueError, match="finite"):
        multiplicity_sensitivity({"a": float("nan"), "b": 1.0})


def test_recorded_fez_pilot_sensitivity_preserves_the_six_series():
    path = Path(__file__).resolve().parents[1] / "results/runs.jsonl"
    summary = load_hardware_pilot(path, "V03_P_pilot-20261013T234830-220ff3")["summary"]
    series = {label: entry["p"] for label, entry in summary["P1_probe_homogeneity"].items()}
    got = multiplicity_sensitivity(series)
    assert got["n"] == 10
    assert got["observed_rejections"] == summary["P1_n_rejected"] == 6
    assert got["independence_reference_at_least_two"] == pytest.approx(0.00426620024283142)
    assert got["markov_upper_at_observed"] == pytest.approx(1 / 60)
    assert {label for label, p in got["holm_adjusted_p_values"].items() if p <= 0.05} == {
        label for label, p in series.items() if p < 0.01
    }
