"""Experiment I scenarios and calibration policies (V03_PREREGISTRATION.md section 6)."""

from __future__ import annotations

from dataclasses import asdict

from .operational import ChartMonitor, EngineMonitor, NaiveMonitor, OpsScenario, OracleMonitor, Policy

OPS_SCENARIOS = {
    "I0": OpsScenario("I0", drift_per_day=0.0, jump_per_day=0.0),  # stable: only stationary fluctuation
    "I1": OpsScenario("I1", drift_per_day=0.5, jump_per_day=0.0),  # gradual degradation
    "I2": OpsScenario("I2", drift_per_day=0.0, jump_per_day=1.0),  # abrupt degradation
    "I3": OpsScenario("I3", drift_per_day=0.5, jump_per_day=0.5),  # both
    "I4": OpsScenario("I4", drift_per_day=0.1, jump_per_day=0.1),  # rare degradation
}
FIXED_HOURS = (48, 24, 12, 8, 6, 4, 3, 2)
FRONTIER = ["none", *(f"fixed{h}" for h in FIXED_HOURS)]
MONITORS = ["eng_cross+24", "eng_any+24", "eng_cross_only", "eng_any_only", "cusum+24", "cusum_only"]
# reported differences (policy a - policy b), with paired bootstrap intervals; no criteria
PAIRED = [
    ("eng_any+24", "eng_cross+24"),  # early (drift) warnings vs crossing alerts only
    ("eng_any_only", "eng_cross_only"),
    ("eng_any+24", "cusum+24"),  # v0.3 engine vs a calibrated CUSUM
    ("eng_any_only", "cusum_only"),
    ("eng_any+24", "fixed24"),
    ("eng_any_only", "fixed24"),
]


def scenario_to_config(sc: OpsScenario) -> dict:
    return {k: (list(v) if isinstance(v, tuple) else v) for k, v in asdict(sc).items()}


def scenario_from_config(d: dict) -> OpsScenario:
    return OpsScenario(**{k: (tuple(v) if isinstance(v, list) else v) for k, v in d.items()})


def build_policies(calibrated: dict) -> dict[str, Policy]:
    c, h, k = float(calibrated["c_star"]), float(calibrated["h_star"]), float(calibrated["k_star"])
    pols = {"none": Policy("none", schedule_hours=None)}
    for hours in FIXED_HOURS:
        pols[f"fixed{hours}"] = Policy(f"fixed{hours}", schedule_hours=float(hours))
    pols["eng_cross+24"] = Policy("eng_cross+24", lambda: EngineMonitor(c, "crossing"), 24.0)
    pols["eng_any+24"] = Policy("eng_any+24", lambda: EngineMonitor(c, "any"), 24.0)
    pols["eng_cross_only"] = Policy("eng_cross_only", lambda: EngineMonitor(c, "crossing"), None)
    pols["eng_any_only"] = Policy("eng_any_only", lambda: EngineMonitor(c, "any"), None)
    pols["cusum+24"] = Policy("cusum+24", lambda: ChartMonitor("cusum", h), 24.0)
    pols["cusum_only"] = Policy("cusum_only", lambda: ChartMonitor("cusum", h), None)
    pols["shewhart+24"] = Policy("shewhart+24", lambda: ChartMonitor("shewhart", k), 24.0)
    pols["naive+24"] = Policy("naive+24", NaiveMonitor, 24.0)
    pols["oracle+24"] = Policy("oracle+24", OracleMonitor, 24.0)
    pols["oracle_only"] = Policy("oracle_only", OracleMonitor, None)
    return pols


def policy_descriptions() -> dict[str, str]:
    d = {"none": "never calibrate"}
    for hours in FIXED_HOURS:
        d[f"fixed{hours}"] = f"calibrate every qubit every {hours} h"
    d.update(
        {
            "eng_cross+24": "daily calibration + recalibrate a qubit on a v0.3 (calibrated) CRITICAL threshold or "
            "WARNING forecast alert on its readout probes",
            "eng_any+24": "daily calibration + recalibrate on any v0.3 WARNING/CRITICAL alert (drift, threshold, forecast)",
            "eng_cross_only": "no schedule; recalibrate on v0.3 threshold or WARNING forecast alerts only",
            "eng_any_only": "no schedule; recalibrate on any v0.3 WARNING/CRITICAL alert",
            "cusum+24": "daily calibration + recalibrate on a CUSUM alarm (h*, reference = first 10 batches)",
            "cusum_only": "no schedule; recalibrate on CUSUM alarms",
            "shewhart+24": "daily calibration + recalibrate on a Shewhart alarm (k*)",
            "naive+24": "daily calibration + recalibrate when a batch's point estimate exceeds 5%",
            "oracle+24": "daily calibration + recalibrate as soon as the true error exceeds 5% (not realisable)",
            "oracle_only": "no schedule; recalibrate as soon as the true error exceeds 5% (not realisable)",
        }
    )
    return d
