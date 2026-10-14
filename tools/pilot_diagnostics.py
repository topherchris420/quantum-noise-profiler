"""Read-only exploratory diagnostics of a recorded physical-QPU pilot.

Descriptive between-batch variance and lag correlation are NOT independent
tests or guarantees. The original preregistered P.C1/P.C2 decisions are
unchanged; no new hardware jobs, file writes, or model refits occur.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path


def describe_rates(rates: list[float], shots_per_batch: int = 4000) -> dict:
    """Descriptive variance-vs-binomial and lag-1 correlation.

    D uses equal shot counts. Correlation is too noisy with 12 batches to
    infer a temporal noise model. Neither estimate calibrates an alert.
    """
    if shots_per_batch < 1 or len(rates) < 3 or any(not 0 <= p <= 1 or not math.isfinite(p) for p in rates):
        raise ValueError("provide at least three finite probabilities in [0,1] and positive shots")
    mean = statistics.fmean(rates)
    observed = statistics.variance(rates)
    predicted = mean * (1 - mean) / shots_per_batch
    ratio = observed / predicted if predicted > 0 else None

    x, y = rates[:-1], rates[1:]
    xbar, ybar = statistics.fmean(x), statistics.fmean(y)
    dx, dy = [a - xbar for a in x], [a - ybar for a in y]
    denom = math.sqrt(sum(z * z for z in dx) * sum(z * z for z in dy))
    lag1 = sum(a * b for a, b in zip(dx, dy)) / denom if denom else None
    return {
        "mean": mean,
        "observed_between_batch_variance": observed,
        "binomial_expected_batch_variance": predicted,
        "variance_ratio": ratio,
        "lag1_descriptive": lag1,
        "min": min(rates),
        "max": max(rates),
    }


def load_hardware_pilot(path: Path, run_id: str | None = None) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"missing {path}; no pilot entries available")
    runs = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    candidates = [
        r
        for r in runs
        if r.get("experiment") == "V03_P_pilot"
        and r.get("config", {}).get("local_simulation") is False
        and (run_id is None or r.get("run_id") == run_id)
    ]
    if not candidates:
        raise ValueError("no completed real-device pilot found")
    return candidates[-1]


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results-dir", type=Path, default=Path(__file__).resolve().parents[1] / "results")
    parser.add_argument("--run-id", default=None, help="completed real-device pilot ID (default: last)")
    args = parser.parse_args(argv)
    entry = load_hardware_pilot(args.results_dir / "runs.jsonl", args.run_id)
    s = entry["summary"]
    print(f"Experiment P: {entry['run_id']} on {s['backend']}")
    print(
        f"Original registered results: P.C1 {s['P1_n_rejected']}/10 rejected; P.C2 "
        f"{s['P2_n_reference_rejected']}/10 rejected"
    )
    print("EXPLORATORY only: variance ratios and lag-1 correlations use the SAME 12 pilot batches.")
    print("Series | mean % | min % | max % | variance / binomial | lag-1 | G/dof | p")
    print("--- | ---: | ---: | ---: | ---: | ---: | ---: | ---:")
    for key, value in sorted(s["P1_probe_homogeneity"].items()):
        rates = value["rates"]
        if len(rates) != 12:
            raise ValueError(f"{key}: expected 12 batches, got {len(rates)}")
        d = describe_rates(rates)
        ratio = "-" if d["variance_ratio"] is None else f"{d['variance_ratio']:.2f}"
        lag1 = "-" if d["lag1_descriptive"] is None else f"{d['lag1_descriptive']:.2f}"
        label = key.replace("|", "&#124;")
        print(
            f"{label} | {100 * d['mean']:.3f} | {100 * d['min']:.3f} | {100 * d['max']:.3f} | "
            f"{ratio} | {lag1} | {value['dispersion']:.2f} | {value['p']:.3g}"
        )
    print(
        "Neither a variance ratio nor a lag correlation establishes drift, detector accuracy, "
        "a physical mechanism, or an anytime-valid bound."
    )


if __name__ == "__main__":
    main()
