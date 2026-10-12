"""The v0.2 experiment harness: surrogate/Aer equivalence and exactness of
post-hoc threshold rescaling."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

from v02.harness import (
    EngineSpec,
    aer_batches,
    first_alarm,
    first_alarm_rescaled,
    run_engine,
    seed_for,
    surrogate_batches,
)


def test_surrogate_matches_aer_count_distribution():
    p = [np.full(40, 0.03), np.full(40, 0.02)]
    sur = surrogate_batches(p, 2000, 11)
    aer = aer_batches(p, 2000, 11)
    for q, truth in ((0, 0.03), (1, 0.02)):
        for b in (sur, aer):
            ks = np.array([k for x in b for k, _ in x.counts[q].values()])
            # mean and variance of Binomial(2000, p) counts
            assert ks.mean() == pytest.approx(2000 * truth, abs=4 * np.sqrt(2000 * truth / len(ks)))
            assert ks.var(ddof=1) == pytest.approx(2000 * truth * (1 - truth), rel=0.35)
    assert set(aer[0].counts[0]) == set(sur[0].counts[0])  # same contexts


def test_rescaled_rule_reproduces_engine_alarms_and_direct_offset():
    sched = [np.r_[np.full(20, 0.02), np.full(20, 0.026)], np.full(40, 0.02)]
    batches = surrogate_batches(sched, 2000, 5)
    log0 = run_engine(batches, EngineSpec("v02", "v02"))
    for q in (0, 1):
        assert first_alarm_rescaled(log0, q, 0.0) == first_alarm(log0, q)
    c = 2.0
    log_c = run_engine(batches, EngineSpec("v02c", "v02", extra={"log_e_offset": c}))
    for q in (0, 1):
        assert first_alarm_rescaled(log0, q, c) == first_alarm(log_c, q)


def test_seed_layout_is_collision_free():
    seeds = {seed_for(30_000, e, c, r) for e in range(6) for c in range(5) for r in range(200)}
    assert len(seeds) == 6 * 5 * 200
    with pytest.raises(ValueError):
        seed_for(30_000, 0, 0, 200)
