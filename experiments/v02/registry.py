"""Experiment name -> function recomputing the recorded summary from raw trials.
Used by tools/verify_results.py."""

from __future__ import annotations

from . import e2_matched

RECOMPUTE = {
    "E2_matched_comparison": e2_matched.recompute_summary,
}
