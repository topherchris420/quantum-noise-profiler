"""Small Bayesian toolkit: Beta posteriors for binomial evidence and a grid
posterior for exponential-decay characterization curves."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats as sps
from scipy.special import logsumexp

JEFFREYS = (0.5, 0.5)


def beta_posterior(k: int, n: int, prior: tuple[float, float] = JEFFREYS):
    return sps.beta(prior[0] + k, prior[1] + n - k)


def beta_interval(k: int, n: int, level: float = 0.95, prior=JEFFREYS):
    """Posterior mean and equal-tailed credible interval for a binomial rate."""
    post = beta_posterior(k, n, prior)
    a = (1 - level) / 2
    return float(post.mean()), float(post.ppf(a)), float(post.ppf(1 - a))


def prob_ratio_exceeds(
    k_new: int,
    n_new: int,
    k_ref: int,
    n_ref: int,
    ratio: float,
    draws: int = 40_000,
    rng: np.random.Generator | None = None,
    prior=JEFFREYS,
) -> float:
    """Posterior P(p_new > ratio * p_ref) for two independent binomial rates."""
    rng = rng or np.random.default_rng(0)
    p_new = rng.beta(prior[0] + k_new, prior[1] + n_new - k_new, draws)
    p_ref = rng.beta(prior[0] + k_ref, prior[1] + n_ref - k_ref, draws)
    return float(np.mean(p_new > ratio * p_ref))


@dataclass(frozen=True)
class DecayFit:
    ok: bool
    median: float | None
    ci_low: float | None
    ci_high: float | None
    level: float
    reason: str = ""
    grid: np.ndarray | None = None
    posterior: np.ndarray | None = None


def fit_exponential_decay(
    delays: np.ndarray,
    successes: np.ndarray,
    shots: np.ndarray | int,
    amp_range: tuple[float, float],
    offset_range: tuple[float, float],
    tau_range: tuple[float, float] | None = None,
    n_tau: int = 400,
    n_amp: int = 41,
    n_off: int = 41,
    level: float = 0.95,
    edge_mass_limit: float = 0.05,
) -> DecayFit:
    """Grid posterior for p(t) = A*exp(-t/tau) + B under a binomial likelihood.

    Prior: log-uniform on tau over ``tau_range`` (default: 1/20 of the shortest
    non-zero delay to 20x the longest), uniform on A and B over the given
    ranges. A and B absorb SPAM error and are marginalized out.

    If more than ``edge_mass_limit`` of the posterior sits on the outer 2% of
    the tau grid, the delays do not bracket tau and the fit is reported as
    not ok rather than returning an interval clipped by the prior.
    """
    delays = np.asarray(delays, dtype=float)
    k = np.asarray(successes, dtype=float)
    n = np.broadcast_to(np.asarray(shots, dtype=float), k.shape)
    if delays.size < 3 or np.unique(delays).size < 3:
        return DecayFit(False, None, None, None, level, "need at least 3 distinct delays")

    if tau_range is None:
        positive = delays[delays > 0]
        tau_range = (positive.min() / 20, delays.max() * 20)
    taus = np.geomspace(tau_range[0], tau_range[1], n_tau)
    amps = np.linspace(*amp_range, n_amp)
    offs = np.linspace(*offset_range, n_off)

    loglik = np.zeros((n_tau, n_amp, n_off))
    decay = np.exp(-delays[None, :] / taus[:, None])  # (n_tau, n_delays)
    for j in range(delays.size):
        p = amps[None, :, None] * decay[:, j][:, None, None] + offs[None, None, :]
        p = np.clip(p, 1e-9, 1 - 1e-9)
        loglik += k[j] * np.log(p) + (n[j] - k[j]) * np.log1p(-p)

    log_marg = logsumexp(loglik, axis=(1, 2))  # log-uniform prior == uniform on grid
    post = np.exp(log_marg - logsumexp(log_marg))

    edge = max(1, int(0.02 * n_tau))
    edge_mass = post[:edge].sum() + post[-edge:].sum()
    if edge_mass > edge_mass_limit:
        return DecayFit(
            False, None, None, None, level,
            f"{edge_mass:.0%} of posterior mass at the edge of the tau prior range; "
            "delays do not bracket the decay time",
            taus, post,
        )

    cdf = np.cumsum(post)
    log_t = np.log(taus)
    a = (1 - level) / 2
    q = lambda x: float(np.exp(np.interp(x, cdf, log_t)))  # noqa: E731
    return DecayFit(True, q(0.5), q(a), q(1 - a), level, "", taus, post)


@dataclass(frozen=True)
class TrendFit:
    slope_mean: float
    slope_sd: float
    intercept_mean: float
    cov: np.ndarray
    n: int


def weighted_linear_trend(t: np.ndarray, y: np.ndarray, sigma: np.ndarray | None) -> TrendFit:
    """Bayesian linear regression with flat prior.

    With per-point ``sigma`` the noise scale is inflated by the reduced
    chi-square when the scatter exceeds the reported uncertainties (model
    misfit), never deflated. With ``sigma=None`` (source reports no
    uncertainty) the noise is estimated from the residuals.
    """
    t = np.asarray(t, float)
    y = np.asarray(y, float)
    known = sigma is not None
    w = 1.0 / np.asarray(sigma, float) ** 2 if known else np.ones_like(t)
    X = np.column_stack([np.ones_like(t), t])
    XtW = X.T * w
    cov = np.linalg.inv(XtW @ X)
    beta = cov @ (XtW @ y)
    dof = len(t) - 2
    if dof > 0:
        chi2 = float(np.sum(w * (y - X @ beta) ** 2)) / dof
        cov = cov * (max(1.0, chi2) if known else chi2)
    return TrendFit(float(beta[1]), float(np.sqrt(cov[1, 1])), float(beta[0]), cov, len(t))
