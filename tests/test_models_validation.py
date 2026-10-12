from datetime import datetime, timezone

import pytest

from qnp import Estimate, Metric, Provenance, Status

TS = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _kw(**over):
    kw = dict(metric=Metric.T1, qubits=(0,), provenance=Provenance.MEASURED, timestamp=TS, value=1e-4)
    kw.update(over)
    return kw


def test_valid_estimate_roundtrips():
    e = Estimate(**_kw(ci_low=9e-5, ci_high=1.1e-4, ci_level=0.95))
    assert Estimate.from_dict(e.to_dict()) == e


@pytest.mark.parametrize(
    "over, exc",
    [
        (dict(timestamp=datetime(2026, 10, 1)), ValueError),  # naive timestamp
        (dict(timestamp="2026-10-01"), TypeError),
        (dict(qubits=(0, 0)), ValueError),
        (dict(qubits=(-1,)), ValueError),
        (dict(qubits=()), ValueError),
        (dict(value=float("nan")), ValueError),
        (dict(value=float("inf")), ValueError),
        (dict(value=None), ValueError),  # OK without a value
        (dict(status=Status.INSUFFICIENT_EVIDENCE), ValueError),  # value with INSUFFICIENT
        (dict(status=Status.INSUFFICIENT_EVIDENCE, value=None), ValueError),  # no reason
        (dict(ci_low=1e-4), ValueError),  # half an interval
        (dict(ci_low=2e-4, ci_high=3e-4, ci_level=0.95), ValueError),  # value outside
        (dict(ci_low=9e-5, ci_high=1.1e-4), ValueError),  # no level
        (dict(successes=5, trials=3), ValueError),
        (dict(successes=1.0, trials=3), TypeError),
        (dict(metric="t1_s"), TypeError),
    ],
)
def test_invalid_estimates_fail_explicitly(over, exc):
    with pytest.raises(exc):
        Estimate(**_kw(**over))


def test_lists_are_coerced_to_tuples():
    e = Estimate(**_kw(qubits=[1, 2], assumptions=["a"]))
    assert e.qubits == (1, 2) and e.assumptions == ("a",)
