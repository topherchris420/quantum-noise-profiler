"""Experiment D scenario generators (V02_PREREGISTRATION.md §6)."""

from __future__ import annotations

import numpy as np

T1 = 100e-6
E = 0.02
SHOTS = 1000
N_DELAYS = 15

SCENARIOS = {
    "D1": {"truth": T1, "r": 3},
    "D2": {"truth": T1, "r": 1},
    "D3": {"truth": T1, "r": 10},
    "D4": {"truth": T1, "r": 0.2},
    "D5": {"truth": T1, "r": 0.05},
    "D6": {"truth": T1, "r": 3, "fluct_sigma": 0.3},
    "D7": {"truth": T1, "r": 3, "fluct_sigma": 0.1},
    "D8": {"truth": None, "r": 3, "biexp": (0.7, 100e-6, 15e-6)},
    "D9": {"truth": None, "r": 3, "biexp": (0.9, 100e-6, 50e-6)},
    "D10": {"truth": T1, "r": 3, "heavy_tail": 0.02},
    "D11": {"truth": T1, "r": 3, "ar1": (0.8, 0.01)},
    "D12": {"truth": T1, "r": 3, "drift": (120e-6, 80e-6)},
    "D13": {"truth": T1, "r": 3, "aer": True},
}
SCENARIO_INDEX = {name: i + 1 for i, name in enumerate(SCENARIOS)}
REPS = {name: (100 if spec.get("aer") else 200) for name, spec in SCENARIOS.items()}


def seed_d(scenario: str, rep: int) -> int:
    if not 0 <= rep < 1000:
        raise ValueError("rep must be < 1000")
    return 40_000 + 1000 * SCENARIO_INDEX[scenario] + rep


def curve(spec: dict, delays: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    a = 1 - 2 * E
    if "fluct_sigma" in spec:
        t1s = T1 * rng.lognormal(0, spec["fluct_sigma"], delays.size)
        return a * np.exp(-delays / t1s) + E
    if "biexp" in spec:
        f, ts, tf = spec["biexp"]
        return a * (f * np.exp(-delays / ts) + (1 - f) * np.exp(-delays / tf)) + E
    if "heavy_tail" in spec:
        p = a * np.exp(-delays / T1) + E + spec["heavy_tail"] * rng.standard_t(3, delays.size)
        return np.clip(p, 0, 1)
    if "ar1" in spec:
        phi, sd = spec["ar1"]
        x = np.empty(delays.size)
        x[0] = rng.normal(0, sd / np.sqrt(1 - phi**2))
        for j in range(1, delays.size):
            x[j] = phi * x[j - 1] + rng.normal(0, sd)
        return np.clip(a * np.exp(-delays / T1) + E + x, 0, 1)
    if "drift" in spec:
        start, end = spec["drift"]
        t1s = np.linspace(start, end, delays.size)
        return a * np.exp(-delays / t1s) + E
    return a * np.exp(-delays / T1) + E


def run_rep(scenario: str, rep: int) -> dict:
    from qnp.measured import estimate_t1

    spec = SCENARIOS[scenario]
    seed = seed_d(scenario, rep)
    rng = np.random.default_rng(seed)
    delays = np.linspace(0, spec["r"] * T1, N_DELAYS)
    if spec.get("aer"):
        from qnp.measured import t1_circuits
        from qnp.sim import DeviceNoise, QubitNoise, aer_run_counts

        dev = DeviceNoise({0: QubitNoise(T1, 80e-6, E, E, 0.0)})
        counts = aer_run_counts(t1_circuits(delays), dev, SHOTS, seed)
        ones = [c.get("1", 0) for c in counts]
    else:
        ones = rng.binomial(SHOTS, np.clip(curve(spec, delays, rng), 0, 1))
    est = estimate_t1(0, delays, ones, SHOTS)
    d = est.diagnostics
    return {
        "scenario": scenario,
        "rep": rep,
        "seed": seed,
        "status": est.status.value,
        "value": est.value,
        "ci_low": est.ci_low,
        "ci_high": est.ci_high,
        "codes": [r["code"] for r in d.get("reasons", [])],
        "deviance_p": d.get("deviance_p"),
        "ppc_p": d.get("ppc_p"),
        "runs_p": d.get("runs_test_p"),
        "decay_fraction": d.get("decay_fraction_spanned"),
        "biexp_log_bf": (d.get("biexponential") or {}).get("log_bf_vs_single"),
        "ones": [int(x) for x in ones],
    }
