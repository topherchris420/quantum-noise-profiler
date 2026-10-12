"""Drift, threshold and forecast analysis over one estimate series.

A series is one (metric, qubits, context, provenance). Three evidence paths:

* binomial  -- estimates carry (successes, trials): exact Beta posteriors,
               batches pooled by summing counts.
* interval  -- estimates carry a credible interval: Gaussian approximation in
               log space (decay-time intervals are asymmetric).
* point     -- vendor values with no uncertainty: the baseline's own scatter
               defines a Student-t posterior predictive for new values.

Alerts require both a posterior probability and a minimum effect size, so
large shot counts cannot turn a trivial change into an alert.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Sequence

import numpy as np
from scipy import stats as sps

from .models import Alert, AlertLevel, Estimate, Metric, Status
from .stats import beta_posterior, prob_ratio_exceeds, weighted_linear_trend

HIGHER_IS_WORSE = {Metric.EFFECTIVE_FLIP, Metric.READOUT_ERROR, Metric.GATE_ERROR}


@dataclass
class DriftConfig:
    recent_batches: int = 3
    min_baseline_batches: int = 3
    min_relative_change: float = 0.10
    change_probability: float = 0.95
    # Recalibration thresholds. Error metrics: alert above. T1/T2: alert below.
    thresholds: dict[Metric, float] = field(
        default_factory=lambda: {Metric.EFFECTIVE_FLIP: 0.05, Metric.READOUT_ERROR: 0.05}
    )
    threshold_probability: float = 0.95
    forecast_horizon_hours: float = 24.0
    # Never project further ahead than this multiple of the observed time span:
    # a trend fitted to 2 h of data says nothing about hour 20.
    max_extrapolation_factor: float = 1.0
    forecast_probability: float = 0.5
    trend_probability: float = 0.9
    min_forecast_points: int = 4
    rng_seed: int = 0


def _worse(metric: Metric, new: float, ref: float, rel: float) -> bool:
    return new > ref * (1 + rel) if metric in HIGHER_IS_WORSE else new < ref * (1 - rel)


def _log_bound(metric: Metric, rel: float) -> float:
    """Log-ratio beyond which a change counts as a degradation of size ``rel``."""
    return np.log1p(rel) if metric in HIGHER_IS_WORSE else np.log1p(-rel)


def _sigma_log(e: Estimate) -> float:
    z = sps.norm.ppf(0.5 + (e.ci_level or 0.95) / 2)
    return (np.log(e.ci_high) - np.log(e.ci_low)) / (2 * z)


def _pool_log(es: Sequence[Estimate]) -> tuple[float, float]:
    """Precision-weighted mean and sd of log values."""
    sig = np.array([_sigma_log(e) for e in es])
    w = 1 / sig**2
    mu = float(np.sum(w * np.log([e.value for e in es])) / w.sum())
    return mu, float(1 / np.sqrt(w.sum()))


def _kind(es: Sequence[Estimate]) -> str:
    if all(e.trials for e in es):
        return "binomial"
    if all(e.ci_low and e.ci_high and e.ci_low > 0 for e in es):
        return "interval"
    return "point"


def analyze_series(
    estimates: Sequence[Estimate],
    config: DriftConfig,
    now: datetime | None = None,
    baseline_since: datetime | None = None,
) -> list[Alert]:
    es = sorted((e for e in estimates if e.status is Status.OK and e.value is not None),
                key=lambda e: e.timestamp)
    if baseline_since is not None:
        es = [e for e in es if e.timestamp >= baseline_since]
    if not es:
        return []
    latest = es[-1]
    now = now or latest.timestamp
    kind = _kind(es)
    alerts: list[Alert] = []

    def alert(level, kind_, msg, **details):
        alerts.append(Alert(level, kind_, latest.metric, latest.qubits, latest.provenance,
                            latest.context, msg, now, {"evidence": kind, **details}))

    recent = es[-config.recent_batches:]
    baseline = es[: -config.recent_batches]
    metric = latest.metric
    label = f"q{','.join(map(str, latest.qubits))} {metric.value}" + (f" [{latest.context}]" if latest.context else "")
    higher_bad = metric in HIGHER_IS_WORSE
    thr = config.thresholds.get(metric)

    # ---- threshold --------------------------------------------------------
    if thr is not None:
        if kind == "binomial":
            k, n = sum(e.successes for e in recent), sum(e.trials for e in recent)
            post = beta_posterior(k, n)
            p_beyond = float(post.sf(thr) if higher_bad else post.cdf(thr))
            current = float(post.mean())
        elif kind == "interval":
            mu, sd = _pool_log(recent)
            p_beyond = float(sps.norm.sf(np.log(thr), mu, sd) if higher_bad else sps.norm.cdf(np.log(thr), mu, sd))
            current = float(np.exp(mu))
        else:
            current = es[-1].value
            p_beyond = 1.0 if _worse(metric, current, thr, 0.0) else 0.0
        if p_beyond >= config.threshold_probability:
            note = "" if kind != "point" else " (source reports no uncertainty)"
            alert(AlertLevel.CRITICAL, "threshold",
                  f"{label} = {current:.4g} is beyond recalibration threshold {thr:g} "
                  f"(P={p_beyond:.3f}){note}",
                  threshold=thr, current=current, probability=p_beyond)

    # ---- drift vs baseline --------------------------------------------------
    if len(baseline) >= config.min_baseline_batches:
        rel = config.min_relative_change
        if kind == "binomial":
            kb, nb = sum(e.successes for e in baseline), sum(e.trials for e in baseline)
            kr, nr = sum(e.successes for e in recent), sum(e.trials for e in recent)
            rng = np.random.default_rng(config.rng_seed)
            # Higher-is-worse is the only binomial direction we produce.
            p = prob_ratio_exceeds(kr, nr, kb, nb, 1 + rel, rng=rng)
            base_v, new_v = (kb + 0.5) / (nb + 1), (kr + 0.5) / (nr + 1)
            stat = {"probability": p}
            fire = p >= config.change_probability
        elif kind == "interval":
            mb, sb = _pool_log(baseline)
            mr, sr = _pool_log(recent)
            d_mu, d_sd = mr - mb, float(np.hypot(sb, sr))
            bound = _log_bound(metric, rel)
            p = float(sps.norm.sf(bound, d_mu, d_sd) if higher_bad else sps.norm.cdf(bound, d_mu, d_sd))
            base_v, new_v = float(np.exp(mb)), float(np.exp(mr))
            stat = {"probability": p}
            fire = p >= config.change_probability
        else:
            logs = np.log([e.value for e in baseline])
            nb = len(logs)
            scale = logs.std(ddof=1) * np.sqrt(1 + 1 / nb)
            new_v, base_v = es[-1].value, float(np.exp(logs.mean()))
            x = np.log(new_v)
            if scale == 0:
                tail = 0.0 if x != logs.mean() else 1.0
            else:
                t_dist = sps.t(nb - 1, logs.mean(), scale)
                tail = float(t_dist.sf(x) if higher_bad else t_dist.cdf(x))
            stat = {"predictive_tail_probability": tail}
            fire = tail <= 1 - config.change_probability and _worse(metric, new_v, base_v, rel)
        if fire:
            direction = "up" if new_v > base_v else "down"
            alert(AlertLevel.WARNING, "drift",
                  f"{label} drifted {direction}: baseline {base_v:.4g} -> recent {new_v:.4g} "
                  f"({(new_v / base_v - 1):+.0%}; " + ", ".join(f"{k}={v:.3g}" for k, v in stat.items()) + ")",
                  baseline=base_v, recent=new_v, min_relative_change=rel, **stat)

    # ---- forecast -----------------------------------------------------------
    if thr is not None and len(es) >= config.min_forecast_points:
        _forecast(es, kind, metric, thr, config, now, label, alert)
    return alerts


def _forecast(es, kind, metric, thr, config, now, label, alert) -> None:
    t0 = es[0].timestamp
    t = np.array([(e.timestamp - t0).total_seconds() / 3600 for e in es])
    if np.ptp(t) == 0:
        return
    y = np.array([e.value for e in es])
    if kind == "binomial":
        sigma = np.array([beta_posterior(e.successes, e.trials).std() for e in es])
    elif kind == "interval":
        z = sps.norm.ppf(0.5 + (es[0].ci_level or 0.95) / 2)
        sigma = np.array([(e.ci_high - e.ci_low) / (2 * z) for e in es])
    else:
        sigma = None
    fit = weighted_linear_trend(t, y, sigma)
    higher_bad = metric in HIGHER_IS_WORSE
    p_trend = float(sps.norm.sf(0, fit.slope_mean, fit.slope_sd) if higher_bad
                    else sps.norm.cdf(0, fit.slope_mean, fit.slope_sd))
    if p_trend < config.trend_probability:
        return
    t_now = (now - t0).total_seconds() / 3600
    current = fit.intercept_mean + fit.slope_mean * t_now
    if _worse(metric, current, thr, 0.0):
        return  # already beyond: the threshold check owns this case
    rng = np.random.default_rng(config.rng_seed)
    a, b = rng.multivariate_normal([fit.intercept_mean, fit.slope_mean], fit.cov, 20_000).T
    with np.errstate(divide="ignore", invalid="ignore"):
        cross = (thr - a) / b - t_now
    heading = (b > 0) if higher_bad else (b < 0)
    cross = np.where(heading & (cross > 0), cross, np.inf)
    horizon = min(config.forecast_horizon_hours, config.max_extrapolation_factor * float(np.ptp(t)))
    p_cross = float(np.mean(cross <= horizon))
    if p_cross < config.forecast_probability:
        return
    med, lo, hi = (float(np.quantile(cross, q)) for q in (0.5, 0.1, 0.9))
    fmt = lambda h: "beyond horizon" if not np.isfinite(h) else (f"{h * 60:.0f} min" if h < 2 else f"{h:.1f} h")  # noqa: E731
    alert(AlertLevel.WARNING if med <= horizon / 4 else AlertLevel.INFO, "forecast",
          f"{label} projected to cross {thr:g} in ~{fmt(med)} (80% interval {fmt(lo)} - {fmt(hi)}; "
          f"P(cross within {horizon:g} h)={p_cross:.2f})",
          threshold=thr, hours_to_threshold_median=med, hours_to_threshold_p10=lo,
          hours_to_threshold_p90=hi if np.isfinite(hi) else None, probability_within_horizon=p_cross,
          slope_per_hour=fit.slope_mean)
