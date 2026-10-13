"""Experiment H: T1 fits when the measurement drifts during the sweep.

Each repetition simulates one T1 sweep acquired under a design:

* ``sequential``  -- delays acquired in delay order, no references (v0.2);
* ``randomized``  -- delays acquired in random order, no references;
* ``interleaved`` -- random order plus 5 ground references (prepare |0>,
  measure) spread over the acquisition (the v0.3 default).

Disturbances live on the *acquisition* axis (slot j of the plan), not on the
delay axis: a measurement offset x_j added to P(1) of whatever circuit is
acquired in slot j (references included), or a T1 that changes with slot j.
With the sequential design slot j is delay j, which reproduces v0.2's
Experiment D exactly in distribution.
"""

from __future__ import annotations

import numpy as np

T1 = 100e-6
E = 0.02
SHOTS = 1000
N_DELAYS = 15
DESIGNS = {
    "sequential": {"n_references": 0, "randomize": False},
    "randomized": {"n_references": 0, "randomize": True},
    "interleaved": {"n_references": 5, "randomize": True},
}

# measurement-level disturbances (affect references too) vs qubit-level ones (do not)
SCENARIOS: dict[str, dict] = {
    "H1": {"truth": T1, "r": 3},
    "H2": {"truth": T1, "r": 1},
    "H3": {"truth": T1, "r": 10},
    "H4": {"truth": T1, "r": 0.2},
    "H5": {"truth": T1, "r": 0.05},
    "H6": {"truth": T1, "r": 3, "fluct_sigma": 0.3},
    "H8": {"truth": None, "r": 3, "biexp": (0.7, 100e-6, 15e-6)},
    "H10": {"truth": T1, "r": 3, "heavy_tail": 0.02},
    "H11": {"truth": T1, "r": 3, "ar1": (0.8, 0.01)},  # v0.2 D11 parameters
    "H11s": {"truth": T1, "r": 3, "ar1": (0.95, 0.01 * np.sqrt((1 - 0.95**2) / (1 - 0.8**2)))},  # slower, same sd
    "H11l": {"truth": T1, "r": 3, "ramp": (-0.015, 0.015)},  # linear offset drift across the acquisition
    "H12": {"truth": T1, "r": 3, "drift": (120e-6, 80e-6)},
    "H13": {"truth": T1, "r": 3, "aer": True},
}


def offsets(spec: dict, n_slots: int, rng: np.random.Generator) -> np.ndarray:
    """Measurement offset added to P(1) of the circuit acquired in each slot."""
    if "ar1" in spec:
        phi, sd = spec["ar1"]
        x = np.empty(n_slots)
        x[0] = rng.normal(0, sd / np.sqrt(1 - phi**2))
        for j in range(1, n_slots):
            x[j] = phi * x[j - 1] + rng.normal(0, sd)
        return x
    if "ramp" in spec:
        lo, hi = spec["ramp"]
        return np.linspace(lo, hi, n_slots)
    return np.zeros(n_slots)


def acquisition_probabilities(spec: dict, plan, rng: np.random.Generator) -> np.ndarray:
    """P(outcome 1) of every circuit of ``plan``, in acquisition order."""
    n_slots = len(plan.slots)
    x = offsets(spec, n_slots, rng)
    a = 1 - 2 * E
    delays = np.asarray(plan.delays_s)
    p = np.empty(n_slots)
    for j, (what, i) in enumerate(plan.slots):
        if what == "reference":
            p[j] = E + x[j]
            continue
        t = delays[i]
        if "fluct_sigma" in spec:
            p[j] = a * np.exp(-t / (T1 * rng.lognormal(0, spec["fluct_sigma"]))) + E
        elif "biexp" in spec:
            f, ts, tf = spec["biexp"]
            p[j] = a * (f * np.exp(-t / ts) + (1 - f) * np.exp(-t / tf)) + E
        elif "drift" in spec:
            start, end = spec["drift"]
            p[j] = a * np.exp(-t / (start + (end - start) * j / (n_slots - 1))) + E
        else:
            p[j] = a * np.exp(-t / T1) + E
        p[j] += x[j]
    if "heavy_tail" in spec:
        p += spec["heavy_tail"] * rng.standard_t(3, n_slots)
    return np.clip(p, 0, 1)


def run_rep(scenario: str, design: str, seed: int) -> dict:
    from qnp.measured import decay_sweep_plan, estimate_t1_from_plan

    spec = SCENARIOS[scenario]
    rng = np.random.default_rng(seed)
    delays = np.linspace(0, spec["r"] * T1, N_DELAYS)
    plan = decay_sweep_plan(delays, seed=int(rng.integers(2**31)), **DESIGNS[design])
    if spec.get("aer"):
        from qnp.measured import decay_plan_circuits
        from qnp.sim import DeviceNoise, QubitNoise, aer_run_counts

        dev = DeviceNoise({0: QubitNoise(T1, 80e-6, E, E, 0.0)})
        counts = aer_run_counts(decay_plan_circuits(plan, "t1"), dev, SHOTS, seed)
        ones = [c.get("1", 0) for c in counts]
    else:
        ones = rng.binomial(SHOTS, acquisition_probabilities(spec, plan, rng))
    est = estimate_t1_from_plan(0, plan, ones, SHOTS)
    d = est.diagnostics
    refs = d.get("references") or {}
    return {
        "scenario": scenario,
        "design": design,
        "seed": seed,
        "status": est.status.value,
        "value": est.value,
        "ci_low": est.ci_low,
        "ci_high": est.ci_high,
        "codes": [r["code"] for r in d.get("reasons", [])],
        "deviance_p": d.get("deviance_p"),
        "ppc_p": d.get("ppc_p"),
        "runs_p": d.get("runs_test_p"),
        "acq_runs_p": d.get("acquisition_runs_test_p"),
        "ref_p": refs.get("p"),
        "slots": [list(s) for s in plan.slots],
        "ones": [int(x) for x in ones],
    }
