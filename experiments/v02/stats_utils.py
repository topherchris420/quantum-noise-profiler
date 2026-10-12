"""Small statistics helpers shared by the v0.2 experiments and the verifier."""

from __future__ import annotations

import numpy as np


def wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (95% by default)."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (float(max(0.0, c - h)), float(min(1.0, c + h)))


def rate_with_ci(flags) -> dict:
    flags = [bool(x) for x in flags]
    k, n = sum(flags), len(flags)
    lo, hi = wilson(k, n)
    return {"rate": k / n if n else float("nan"), "k": k, "n": n, "ci95": [lo, hi]}


def delay_summary(delays) -> dict:
    """Summary of detection delays; ``None`` means never detected."""
    xs = [d for d in delays if d is not None]
    n = len(delays)
    out = {"n": n, "detected": len(xs), "detect_rate": len(xs) / n if n else float("nan")}
    if xs:
        q = np.quantile(xs, [0.25, 0.5, 0.75])
        out.update(median=float(q[1]), q25=float(q[0]), q75=float(q[2]), mean=float(np.mean(xs)))
    else:
        out.update(median=None, q25=None, q75=None, mean=None)
    return out
