"""Experiment name -> function recomputing the recorded summary from raw trials
(v0.3). Used by tools/verify_results.py."""

from __future__ import annotations

from .analysis import SUMMARY
from .pilot import recompute_summary as _pilot

RECOMPUTE = {**SUMMARY, "V03_P_pilot": _pilot}
