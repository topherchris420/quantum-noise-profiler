"""Threshold-crossing forecasts with explicit statuses and predictive intervals.

A forecast is offered only when (1) there is enough history, (2) a worsening
linear trend is supported by an anytime-valid e-value, (3) the linear model
is not contradicted by the residual structure, (4) the slope is consistent
over the history, and (5) the projected crossing lies within what the data
span can support. Every rejection carries machine-readable ``Reason`` codes.

The crossing-time distribution combines parameter uncertainty (intercept,
slope, error scale from their joint posterior) with future process
variation (the excess scatter of the series beyond its reported measurement
uncertainty), so the reported interval is a *predictive* interval for the
time at which the underlying level crosses the threshold, not a confidence
band on fitted parameters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy import stats as sps

from .models import ForecastStatus, Reason
from .sequential import RegressionEvidence, gaussian_regression_evalue, gaussian_regression_mixture_evalue

__all__ = ["ForecastConfig", "ForecastReport", "forecast_series", "runs_test_pvalue"]


@dataclass
class ForecastConfig:
    min_points: int = 6
    min_span_hours: float = 1.0
    horizon_hours: float = 24.0
    # Never project further ahead than this multiple of the observed span.
    max_extrapolation_factor: float = 1.0
    g_prior: tuple[float, ...] = (1.0, 10.0, 100.0)  # g-prior mixture for the trend *evidence* (any g > 0 is valid)
    g_forecast: float = 1e6  # near-flat prior for the *predictive* crossing distribution
    lack_of_fit_alpha: float = 0.01  # runs test on residual signs
    curvature_e_threshold: float = 20.0  # e-value for a quadratic term vs the linear model
    unstable_z: float = 3.0  # |first-half slope - second-half slope| / se
    forecast_probability: float = 0.5  # alert only if P(cross within horizon) >= this
    n_draws: int = 20_000
    rng_seed: int = 0


@dataclass(frozen=True)
class ForecastReport:
    status: ForecastStatus
    reasons: tuple[Reason, ...]
    n_points: int
    span_hours: float
    log_e: float
    log_e_threshold: float | None
    slope_per_hour: float | None
    slope_scale: float | None
    crossing: dict[str, Any] | None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return self.status is ForecastStatus.VALID_FORECAST

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reasons": [r.to_dict() for r in self.reasons],
            "n_points": self.n_points,
            "span_hours": self.span_hours,
            "log_e": self.log_e,
            "log_e_threshold": self.log_e_threshold,
            "slope_per_hour": self.slope_per_hour,
            "slope_scale": self.slope_scale,
            "crossing": self.crossing,
            "diagnostics": self.diagnostics,
        }


def runs_test_pvalue(signs: np.ndarray) -> float:
    """Two-sided Wald-Wolfowitz runs test on a sequence of +/-1 (normal approximation)."""
    s = np.asarray(signs)
    s = s[s != 0]
    n1, n2 = int((s > 0).sum()), int((s < 0).sum())
    n = n1 + n2
    if n1 == 0 or n2 == 0 or n < 4:
        return 1.0
    runs = 1 + int((s[1:] != s[:-1]).sum())
    mu = 1 + 2 * n1 * n2 / n
    var = 2 * n1 * n2 * (2 * n1 * n2 - n) / (n * n * (n - 1))
    if var <= 0:
        return 1.0
    z = (runs - mu) / np.sqrt(var)
    return float(2 * sps.norm.sf(abs(z)))


def _quantile_with_inf(x: np.ndarray, q: float) -> float:
    """Quantile of a sample that may contain +inf (no crossing): finite below
    the finite mass, +inf above it, without numpy's inf-inf warnings."""
    finite = x[np.isfinite(x)]
    frac = finite.size / x.size
    if finite.size == 0 or q > frac:
        return float("inf")
    return float(np.quantile(finite, min(1.0, q / frac)))


def _wls(t, y, w):
    """Weighted least squares slope and its standard error (scale from residuals)."""
    sw = w.sum()
    tb, yb = (w * t).sum() / sw, (w * y).sum() / sw
    sxx = (w * (t - tb) ** 2).sum()
    if sxx <= 0 or t.size < 3:
        return float("nan"), float("nan")
    b = (w * (t - tb) * (y - yb)).sum() / sxx
    resid = y - yb - b * (t - tb)
    s2 = (w * resid**2).sum() / (t.size - 2)
    return float(b), float(np.sqrt(s2 / sxx))


def forecast_series(
    t_hours: np.ndarray,
    y: np.ndarray,
    w: np.ndarray,
    higher_is_worse: bool,
    threshold_y: float | None,
    now_hours: float,
    config: ForecastConfig,
    log_e_threshold: float | None = None,
) -> ForecastReport:
    """Forecast the crossing of ``threshold_y`` by the trend in ``y``.

    ``y`` is in analysis space (a rate, or log of a decay time) and ``w`` are
    the known relative precisions (``1/sigma^2``). ``log_e_threshold`` is the
    log e-value the trend must reach (``log(1/alpha_series)``); when None the
    evidence gate is not applied.
    """
    t = np.asarray(t_hours, float)
    y = np.asarray(y, float)
    w = np.asarray(w, float)
    n = t.size
    span = float(np.ptp(t)) if n else 0.0
    sign = +1 if higher_is_worse else -1
    reasons: list[Reason] = []
    diag: dict[str, Any] = {}

    if n < config.min_points or span < config.min_span_hours:
        if n < config.min_points:
            reasons.append(
                Reason("TOO_FEW_POINTS", f"{n} points < min_points={config.min_points}", n, config.min_points)
            )
        if span < config.min_span_hours:
            reasons.append(
                Reason(
                    "SPAN_TOO_SHORT",
                    f"span {span:.2f} h < min_span_hours={config.min_span_hours}",
                    span,
                    config.min_span_hours,
                )
            )
        return ForecastReport(
            ForecastStatus.INSUFFICIENT_HISTORY, tuple(reasons), n, span, 0.0, log_e_threshold, None, None, None, diag
        )

    trend_log_e, ev = gaussian_regression_mixture_evalue(y, t, w, config.g_prior, True, sign)
    # Prediction uses a near-flat prior: the g=1 evidence prior shrinks the
    # slope by half, which is fine for testing but biases a forecast.
    evp: RegressionEvidence = gaussian_regression_evalue(y, t, w, config.g_forecast, True, sign)
    slope, slope_scale = evp.b_post_mean, evp.b_post_scale
    diag["trend_log_e"] = trend_log_e
    diag["dispersion_factor"] = evp.sigma2_scale  # 1 == scatter matches reported uncertainty

    # --- residual structure of the linear fit
    xt, yt = t - ev.x_bar, y - ev.y_bar
    resid = yt - ev.b_hat * xt
    runs_p = runs_test_pvalue(np.sign(resid))
    diag["runs_test_p"] = runs_p
    # curvature: quadratic term after partialling out [1, t] (Frisch-Waugh)
    q = xt**2
    qb = (w * q).sum() / w.sum()
    qt = q - qb
    bq = (w * qt * xt).sum() / ev.sxx if ev.sxx > 0 else 0.0
    z = qt - bq * xt
    curv_log_e, _ = gaussian_regression_mixture_evalue(
        resid, z, w, config.g_prior, intercept=False, sign=0, extra_dof_lost=2
    )
    diag["curvature_log_e"] = curv_log_e
    # slope consistency between the two halves of the history
    half = n // 2
    b1, se1 = _wls(t[:half], y[:half], w[:half])
    b2, se2 = _wls(t[half:], y[half:], w[half:])
    if np.isfinite(b1) and np.isfinite(b2) and np.isfinite(se1) and np.isfinite(se2) and (se1 > 0 or se2 > 0):
        z_halves = abs(b1 - b2) / np.hypot(se1, se2)
    else:
        z_halves = 0.0
    diag["half_slopes"] = {"first": b1, "second": b2, "z": float(z_halves)}

    # --- decision ladder
    if log_e_threshold is not None and trend_log_e < log_e_threshold:
        reasons.append(
            Reason(
                "TREND_NOT_SUPPORTED",
                f"trend e-value {np.exp(trend_log_e):.3g} below {np.exp(log_e_threshold):.3g}",
                float(np.exp(min(trend_log_e, 700))),
                float(np.exp(log_e_threshold)),
            )
        )
        return ForecastReport(
            ForecastStatus.INSUFFICIENT_EVIDENCE,
            tuple(reasons),
            n,
            span,
            trend_log_e,
            log_e_threshold,
            slope,
            slope_scale,
            None,
            diag,
        )
    if runs_p < config.lack_of_fit_alpha:
        reasons.append(
            Reason(
                "RESIDUAL_STRUCTURE",
                f"runs test p={runs_p:.3g} < {config.lack_of_fit_alpha}",
                runs_p,
                config.lack_of_fit_alpha,
            )
        )
    if curv_log_e >= np.log(config.curvature_e_threshold):
        reasons.append(
            Reason(
                "CURVATURE",
                f"quadratic term e-value {np.exp(curv_log_e):.3g} >= {config.curvature_e_threshold}",
                float(np.exp(min(curv_log_e, 700))),
                config.curvature_e_threshold,
            )
        )
    if reasons:
        return ForecastReport(
            ForecastStatus.MODEL_MISSPECIFICATION,
            tuple(reasons),
            n,
            span,
            trend_log_e,
            log_e_threshold,
            slope,
            slope_scale,
            None,
            diag,
        )
    if z_halves > config.unstable_z:
        reasons.append(
            Reason(
                "SLOPE_INCONSISTENT",
                f"half-history slopes differ by {z_halves:.1f} se > {config.unstable_z}",
                float(z_halves),
                config.unstable_z,
            )
        )
        return ForecastReport(
            ForecastStatus.UNSTABLE_TREND,
            tuple(reasons),
            n,
            span,
            trend_log_e,
            log_e_threshold,
            slope,
            slope_scale,
            None,
            diag,
        )
    if threshold_y is None:
        reasons.append(Reason("NO_THRESHOLD", "no recalibration threshold configured for this metric"))
        return ForecastReport(
            ForecastStatus.VALID_FORECAST,
            tuple(reasons),
            n,
            span,
            trend_log_e,
            log_e_threshold,
            slope,
            slope_scale,
            None,
            diag,
        )

    # --- predictive crossing-time distribution
    rng = np.random.default_rng(config.rng_seed)
    nd = config.n_draws
    sigma2 = (evp.nu * evp.sigma2_scale / 2) / rng.gamma(evp.nu / 2, 1.0, nd)  # InvGamma(nu/2, RSS_g/2)
    shrink = config.g_forecast / (1 + config.g_forecast)
    b = rng.normal(evp.b_post_mean, np.sqrt(sigma2 * shrink / evp.sxx))
    a = rng.normal(evp.y_bar, np.sqrt(sigma2 / evp.sum_w))  # level at t = x_bar
    w_typical = float(np.exp(np.mean(np.log(w))))
    process_var = np.maximum(sigma2 - 1.0, 0.0) / w_typical
    eta = rng.normal(0.0, np.sqrt(process_var))
    level_now = evp.y_bar + evp.b_post_mean * (now_hours - evp.x_bar)
    already = level_now > threshold_y if higher_is_worse else level_now < threshold_y
    with np.errstate(divide="ignore", invalid="ignore"):
        t_cross = (threshold_y - a - eta) / b + evp.x_bar - now_hours
    heading = (b > 0) if higher_is_worse else (b < 0)
    t_cross = np.where(heading & (t_cross > 0), t_cross, np.inf)
    cap = config.max_extrapolation_factor * span
    horizon_eff = float(min(config.horizon_hours, cap))
    p_within = float(np.mean(t_cross <= horizon_eff))
    med, p10, p90 = (_quantile_with_inf(t_cross, q) for q in (0.5, 0.1, 0.9))
    crossing = {
        "threshold": threshold_y,
        "now_level": float(level_now),
        "already_beyond": bool(already),
        "median_hours": med if np.isfinite(med) else None,
        "p10_hours": p10 if np.isfinite(p10) else None,
        "p90_hours": p90 if np.isfinite(p90) else None,
        "p_within_horizon": p_within,
        "horizon_hours": horizon_eff,
        "requested_horizon_hours": config.horizon_hours,
        "extrapolation_cap_hours": float(cap),
        "process_sd": float(np.sqrt(np.mean(process_var))),
        "includes_process_variation": True,
        "interval_level": 0.80,
    }
    if already:
        reasons.append(
            Reason(
                "ALREADY_BEYOND_THRESHOLD",
                "current level is already beyond the threshold; the threshold channel owns this case",
            )
        )
        return ForecastReport(
            ForecastStatus.VALID_FORECAST,
            tuple(reasons),
            n,
            span,
            trend_log_e,
            log_e_threshold,
            slope,
            slope_scale,
            crossing,
            diag,
        )
    if not np.isfinite(med) or med > cap:
        reasons.append(
            Reason(
                "BEYOND_EXTRAPOLATION_CAP",
                "median crossing "
                + ("beyond horizon" if not np.isfinite(med) else f"{med:.1f} h")
                + f" exceeds the supported {cap:.1f} h",
                med if np.isfinite(med) else None,
                float(cap),
            )
        )
        return ForecastReport(
            ForecastStatus.UNSUPPORTED_HORIZON,
            tuple(reasons),
            n,
            span,
            trend_log_e,
            log_e_threshold,
            slope,
            slope_scale,
            crossing,
            diag,
        )
    return ForecastReport(
        ForecastStatus.VALID_FORECAST, (), n, span, trend_log_e, log_e_threshold, slope, slope_scale, crossing, diag
    )
