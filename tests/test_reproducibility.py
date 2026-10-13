"""R.C1 of the v0.2 preregistration: the same seed gives bit-identical
per-batch logs, through both the surrogate and the Aer pipeline."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

from v02.compact import compact_v01, compact_v02
from v02.harness import V01_DEFAULT, V02_DEFAULT, aer_batches, run_engine, surrogate_batches


def _sched():
    return [np.where(np.arange(30) < 15, 0.02, 0.024), np.full(30, 0.02)]


def test_surrogate_pipeline_is_deterministic():
    a = compact_v02(run_engine(surrogate_batches(_sched(), 2000, 30_000 + 2000 + 200), V02_DEFAULT))
    b = compact_v02(run_engine(surrogate_batches(_sched(), 2000, 30_000 + 2000 + 200), V02_DEFAULT))
    assert a == b


def test_aer_pipeline_is_deterministic_for_both_engines():
    s = [x[:12] for x in _sched()]
    b1, b2 = aer_batches(s, 2000, 7), aer_batches(s, 2000, 7)
    assert [x.counts for x in b1] == [x.counts for x in b2]
    assert compact_v02(run_engine(b1, V02_DEFAULT)) == compact_v02(run_engine(b2, V02_DEFAULT))
    assert compact_v01(run_engine(b1, V01_DEFAULT)) == compact_v01(run_engine(b2, V01_DEFAULT))


def test_different_seeds_differ():
    a = surrogate_batches(_sched(), 2000, 1)
    b = surrogate_batches(_sched(), 2000, 2)
    assert [x.counts for x in a] != [x.counts for x in b]
