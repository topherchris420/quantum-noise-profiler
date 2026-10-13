"""Anytime-valid sequential evidence for monitoring: e-processes.

An *e-process* is a non-negative process ``E_t`` with ``E[E_tau] <= 1`` under
the null for every stopping time ``tau``. Ville's inequality then gives

    P_H0( exists t : E_t >= 1/alpha ) <= alpha,

uniformly over the (unknown, unbounded) length of a monitoring session. That
is the property a continuously re-tested monitor needs and a per-check
posterior bar does not have (docs/V01_AUDIT.md, D2).

What each detector guarantees, and under which null
-----------------------------------------------------

``BinomialThresholdDetector``
    H0: every batch rate ``p_t <= theta`` (error metrics) or ``>= theta``
    (decay times are handled on the log scale by the Gaussian detectors).
    Exact frequentist guarantee: each per-batch likelihood ratio against a
    fixed ``theta`` has expectation <= 1 for all ``p <= theta`` (monotone
    likelihood ratio of the binomial family), mixtures and products of such
    ratios keep that property, and the change-time mixture is a convex
    combination of supermartingales. No plug-in, no approximation.

``gaussian_regression_evalue`` / ``GaussianChangeDetector`` / ``GaussianTrendDetector``
    Linear model ``y_u = a + b x_u + eps_u``, ``eps_u ~ N(0, sigma^2 / w_u)``
    with *unknown* scale ``sigma`` and known relative weights ``w_u``. H0:
    ``b = 0`` (and, for the one-sided versions, the composite ``sign * b <= 0``).
    Flat prior on the nuisance intercept ``a`` and on ``log sigma``, Zellner
    g-prior on ``b``. The sequential Bayes factor is a test martingale under
    H0 for every ``(a, sigma)`` (Lindon & Malek 2022, anytime-valid linear
    models; the two-sided closed form is Liang et al. 2008 eq. 5). Exact for
    Gaussian errors; for binomial rates it relies on the normal
    approximation, so its calibration is checked empirically.

``BinomialChangeDetector``
    H0: all batches share one rate ``p``. The null predictive is the
    Beta-binomial under the running Jeffreys posterior; the alternative is a
    mixture over change times ``s`` (geometric prior) and relative increases
    ``delta >= delta_min`` of predictives fixed at time ``s-1``. The
    resulting Bayes-factor process is a test martingale under the *Bayesian
    marginal* null (``p`` drawn from the prior). For a *fixed* unknown ``p``
    this is a Bayesian statement, not a frequentist guarantee: the run-level
    false-alert probability at fixed ``p`` is what Experiment A of the v0.2
    preregistration measures.

All detectors are incremental: ``update(...)`` consumes one batch and
returns the current log e-value; ``log_e`` holds the full trajectory so a
caller can apply a stopping rule to the supremum, not only to the latest
value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

import numpy as np
from scipy import stats as sps
from scipy.special import betaln, logsumexp

__all__ = [
    "BinomialChangeDetector",
    "BinomialThresholdDetector",
    "GaussianChangeDetector",
    "GaussianThresholdDetector",
    "GaussianTrendDetector",
    "RegressionEvidence",
    "gaussian_regression_evalue",
    "gaussian_regression_mixture_evalue",
    "geometric_log_prior",
]

_CLIP = 1e-12


def _check_counts(k: int, n: int) -> None:
    if not (isinstance(k, (int, np.integer)) and isinstance(n, (int, np.integer))):
        raise TypeError(f"counts must be integers, got k={k!r}, n={n!r}")
    if n <= 0 or k < 0 or k > n:
        raise ValueError(f"invalid binomial counts k={k}, n={n}")


def geometric_log_prior(t: int, rho: float) -> tuple[np.ndarray, float]:
    """log pi(s) for change times s = 1..t under pi(s) = rho (1-rho)^(s-1),
    and the log tail mass sum_{s>t} pi(s) = (1-rho)^t ("no change yet")."""
    if not 0 < rho < 1:
        raise ValueError("rho must be in (0, 1)")
    s = np.arange(1, t + 1)
    return np.log(rho) + (s - 1) * np.log1p(-rho), float(t * np.log1p(-rho))


def _binom_loglik(k: float, n: float, p: np.ndarray) -> np.ndarray:
    p = np.clip(p, _CLIP, 1 - _CLIP)
    return k * np.log(p) + (n - k) * np.log1p(-p)


# --------------------------------------------------------------------------- binomial change


def _betabinom_logkernel(k: int, n: int, a: float, b: float) -> float:
    """log P(k | n) under p ~ Beta(a, b) *without* the binomial coefficient,
    matching ``_binom_loglik`` so that likelihood ratios are consistent."""
    return float(betaln(k + a, n - k + b) - betaln(a, b))


@dataclass
class BinomialChangeDetector:
    """Sequential Bayes factor for a relative increase of a binomial rate.

    Null predictive: Beta-binomial with the running Jeffreys posterior of the
    common rate ``p``. Alternative for a change at batch ``s``: the rate
    becomes ``p (1 + delta)`` where ``p`` is drawn from the null posterior
    *frozen at batch s-1* (represented by ``n_nodes`` quantile nodes) and
    ``delta`` is on a log-spaced grid in ``[delta_min, delta_max]``; ``s`` has a
    geometric prior with mean ``change_prior_mean``. Each alternative is a
    proper predictive fixed at time ``s-1``, so every mixture term is a
    likelihood-ratio martingale under the Bayesian null and the mixture is a
    test martingale (prequential form; see the module docstring for what
    this does and does not guarantee at a fixed ``p``).

    Changes can only start after ``min_baseline_batches`` batches; the prior
    mass of earlier change times is counted as "no change" (ratio 1).
    """

    delta_min: float = 0.10
    delta_max: float = 3.0
    n_delta: int = 10
    n_nodes: int = 16
    min_baseline_batches: int = 3
    change_prior_mean: float = 48.0
    prior: tuple[float, float] = (0.5, 0.5)
    max_lookback: int | None = None  # cap on candidate change times kept (None: all)

    def __post_init__(self) -> None:
        if not 0 < self.delta_min < self.delta_max:
            raise ValueError("need 0 < delta_min < delta_max")
        if self.change_prior_mean < 1:
            raise ValueError("change_prior_mean must be >= 1 batch")
        if self.min_baseline_batches < 1:
            raise ValueError("min_baseline_batches must be >= 1")
        self.deltas = np.geomspace(self.delta_min, self.delta_max, self.n_delta)
        self.rho = 1.0 / self.change_prior_mean
        self.ks: list[int] = []
        self.ns: list[int] = []
        self._K = 0
        self._N = 0
        # per candidate change time s: alternative rates (D, J) and cumulative log LR (D, J)
        self._s: list[int] = []
        self._rates: list[np.ndarray] = []
        self._L: list[np.ndarray] = []
        self.log_e: list[float] = []
        self.last: dict = {}

    @property
    def t(self) -> int:
        return len(self.ks)

    def _add_candidate(self, s: int) -> None:
        a, b = self.prior[0] + self._K, self.prior[1] + self._N - self._K
        q = (np.arange(self.n_nodes) + 0.5) / self.n_nodes
        nodes = sps.beta.ppf(q, a, b)
        rates = np.clip(nodes[None, :] * (1 + self.deltas[:, None]), _CLIP, 1 - _CLIP)
        self._s.append(s)
        self._rates.append(rates)
        self._L.append(np.zeros((self.n_delta, self.n_nodes)))

    def update(self, k: int, n: int) -> float:
        _check_counts(k, n)
        T = self.t + 1
        if T - 1 >= self.min_baseline_batches:
            self._add_candidate(T)  # change starting at this batch, baseline frozen at T-1
        a, b = self.prior[0] + self._K, self.prior[1] + self._N - self._K
        log_p0 = _betabinom_logkernel(int(k), int(n), a, b)
        for i in range(len(self._s)):
            self._L[i] += _binom_loglik(k, n, self._rates[i]) - log_p0
        self.ks.append(int(k))
        self.ns.append(int(n))
        self._K += int(k)
        self._N += int(n)
        if self.max_lookback is not None:
            while self._s and self._s[0] < T - self.max_lookback + 1:
                self._s.pop(0)
                self._rates.pop(0)
                self._L.pop(0)
        log_pi_all, log_tail = geometric_log_prior(T, self.rho)
        # prior mass of change times without a usable baseline (or dropped) -> "no change"
        active = np.array(self._s, dtype=int)
        inactive_mask = np.ones(T, dtype=bool)
        if active.size:
            inactive_mask[active - 1] = False
        if inactive_mask.any():
            log_tail = float(np.logaddexp(log_tail, logsumexp(log_pi_all[inactive_mask])))
        if active.size:
            L = np.stack(self._L)  # (S, D, J)
            terms = log_pi_all[active - 1][:, None, None] - np.log(self.n_delta * self.n_nodes) + L
            log_sum = float(logsumexp(terms))
            log_bf = float(np.logaddexp(log_sum, log_tail))
            log_post = terms - log_bf
            post_s = np.exp(logsumexp(log_post, axis=(1, 2)))
            post_d = np.exp(logsumexp(log_post, axis=(0, 2)))
            p_change = float(post_s.sum())
            i_map = int(np.argmax(post_s))
            s_map = int(active[i_map])
            cdf = np.cumsum(post_d) / max(post_d.sum(), 1e-300)
            delta_median = float(np.interp(0.5, cdf, self.deltas))
        else:
            log_bf, p_change, s_map, delta_median = 0.0, 0.0, None, None
        self.log_e.append(log_bf)
        self.last = {
            "log_e": log_bf,
            "e": float(np.exp(min(log_bf, 700))),
            "p_change": p_change,
            "change_time_map": s_map,
            "batches_since_change": None if s_map is None else T - s_map + 1,
            "delta_posterior_median": delta_median,
            "t": T,
        }
        return log_bf

    def extend(self, ks, ns) -> float:
        out = float("nan")
        for k, n in zip(ks, ns, strict=True):
            out = self.update(k, n)
        return out

    def log_terms(self) -> tuple[np.ndarray, np.ndarray]:
        """Candidate change times and, per (s, delta), the log of the
        node-averaged cumulative likelihood ratio. Used to combine several
        synchronous context series under a shared (s, delta) alternative:
        the product over independent contexts of these node-mixtures is a
        martingale, so the shared-change mixture stays a test martingale."""
        if not self._s:
            return np.zeros(0, dtype=int), np.zeros((0, self.n_delta))
        L = np.stack(self._L)  # (S, D, J)
        return np.array(self._s, dtype=int), logsumexp(L, axis=2) - np.log(self.n_nodes)


# --------------------------------------------------------------------------- binomial threshold


@dataclass
class BinomialThresholdDetector:
    """Exact e-process for H0: p_t <= theta for all t (higher is worse).

    Alternative rates ``theta (1 + eps)`` for ``eps`` log-spaced in
    ``[eps_min, eps_max]`` (equal weights), mixed over a geometric change time.
    """

    theta: float
    eps_min: float = 0.02
    eps_max: float = 5.0
    n_eps: int = 24
    change_prior_mean: float = 48.0

    def __post_init__(self) -> None:
        if not 0 < self.theta < 1:
            raise ValueError("theta must be in (0, 1)")
        eps = np.geomspace(self.eps_min, self.eps_max, self.n_eps)
        self.alts = np.clip(self.theta * (1 + eps), _CLIP, 1 - _CLIP)
        self.alts = np.unique(self.alts)
        self.rho = 1.0 / self.change_prior_mean
        self._C: list[np.ndarray] = [np.zeros(self.alts.size)]
        self.ks: list[int] = []
        self.ns: list[int] = []
        self.log_e: list[float] = []
        self.last: dict = {}

    @property
    def t(self) -> int:
        return len(self.ks)

    def update(self, k: int, n: int) -> float:
        _check_counts(k, n)
        self.ks.append(int(k))
        self.ns.append(int(n))
        self._C.append(self._C[-1] + _binom_loglik(k, n, self.alts) - _binom_loglik(k, n, np.array([self.theta]))[0])
        T = self.t
        C = np.stack(self._C)  # (T+1, J)
        log_pi_s, log_tail = geometric_log_prior(T, self.rho)
        terms = log_pi_s[:, None] - np.log(self.alts.size) + C[T][None, :] - C[:T]  # s = 1..T
        log_e = float(np.logaddexp(logsumexp(terms), log_tail))
        self.log_e.append(log_e)
        self.last = {"log_e": log_e, "e": float(np.exp(min(log_e, 700))), "t": T}
        return log_e

    def extend(self, ks, ns) -> float:
        out = float("nan")
        for k, n in zip(ks, ns, strict=True):
            out = self.update(k, n)
        return out


# --------------------------------------------------------------------------- gaussian regression


@dataclass(frozen=True)
class RegressionEvidence:
    log_e: float  # one-sided (if sign != 0) or two-sided log Bayes factor
    log_e_two_sided: float
    b_hat: float  # weighted least-squares slope
    b_post_mean: float  # posterior mean under the g-prior (shrunk)
    b_post_scale: float  # scale of the Student-t posterior of b
    nu: int  # degrees of freedom
    sigma2_scale: float  # RSS_g / nu: posterior scale of the error variance factor
    rss_null: float
    r2: float
    n: int
    sxx: float
    x_bar: float
    y_bar: float
    sum_w: float


def gaussian_regression_evalue(
    y, x, w, g: float = 1.0, intercept: bool = True, sign: int = 0, theta: float = 0.0, extra_dof_lost: int = 0
) -> RegressionEvidence:
    """Sequential-Bayes-factor e-value for the slope of ``y ~ a + b x``.

    ``w`` are known relative precisions (``1/sigma_u^2`` up to the unknown
    common factor). ``sign=+1`` tests ``b > 0`` against ``b <= 0``, ``-1``
    tests ``b < 0``, ``0`` is two-sided. With ``intercept=False`` the
    intercept is fixed at ``theta`` (one-sample mean test when ``x == 1``).

    Two-sided closed form (Liang et al. 2008, eq. 5, with p = 1):
    ``BF = (1+g)^((nu-1)/2) (1 + g (1 - R^2))^(-nu/2)``, ``nu = n - 1`` with a
    flat intercept, ``n`` without. One-sided: ``2 BF P(sign b > 0 | data)``,
    the posterior sign probability being a Student-t tail (verified against
    brute-force integration in tests/test_sequential.py). ``extra_dof_lost``
    accounts for nuisance regressors already partialled out of ``y`` and
    ``x`` (Frisch-Waugh), e.g. 1 when testing curvature after removing a
    linear trend.
    """
    y = np.asarray(y, float)
    x = np.asarray(x, float)
    w = np.asarray(w, float)
    if not (y.shape == x.shape == w.shape) or y.ndim != 1:
        raise ValueError("y, x, w must be 1-d arrays of equal length")
    if not np.all(np.isfinite(y)) or not np.all(np.isfinite(x)) or not np.all(np.isfinite(w)) or np.any(w <= 0):
        raise ValueError("y, x must be finite and w strictly positive")
    if g <= 0:
        raise ValueError("g must be positive")
    n = y.size
    sum_w = float(w.sum())
    if intercept:
        x_bar = float((w * x).sum() / sum_w)
        y_bar = float((w * y).sum() / sum_w)
        nu = n - 1
    else:
        x_bar, y_bar, nu = 0.0, theta, n
    nu -= int(extra_dof_lost)
    xt, yt = x - x_bar, y - y_bar
    sxx = float((w * xt * xt).sum())
    rss0 = float((w * yt * yt).sum())
    null = RegressionEvidence(
        0.0, 0.0, float("nan"), float("nan"), float("nan"), nu, float("nan"), rss0, 0.0, n, sxx, x_bar, y_bar, sum_w
    )
    if nu < 2 or sxx <= 0 or rss0 <= 0:
        return null
    b_hat = float((w * xt * yt).sum() / sxx)
    r2 = min(1.0, b_hat * b_hat * sxx / rss0)
    shrink = g / (1 + g)
    log_bf2 = 0.5 * (nu - 1) * np.log1p(g) - 0.5 * nu * np.log1p(g * (1 - r2))
    rss_g = rss0 * (1 - r2 * shrink)
    sigma2_scale = rss_g / nu
    b_mean = b_hat * shrink
    b_scale = float(np.sqrt(sigma2_scale * shrink / sxx))
    if sign == 0:
        log_e = float(log_bf2)
    else:
        z = sign * b_mean / b_scale
        log_e = float(np.log(2) + log_bf2 + sps.t.logcdf(z, nu))
    return RegressionEvidence(
        log_e,
        float(log_bf2),
        b_hat,
        b_mean,
        b_scale,
        nu,
        float(sigma2_scale),
        rss0,
        float(r2),
        n,
        sxx,
        x_bar,
        y_bar,
        sum_w,
    )


def _as_gs(g) -> tuple[float, ...]:
    gs = (float(cast(float, g)),) if np.isscalar(g) else tuple(float(v) for v in g)
    if not gs or any(v <= 0 for v in gs):
        raise ValueError("g must be a positive number or a non-empty tuple of positive numbers")
    return gs


def gaussian_regression_mixture_evalue(
    y, x, w, gs, intercept: bool = True, sign: int = 0, theta: float = 0.0, extra_dof_lost: int = 0
) -> tuple[float, RegressionEvidence]:
    """Equal-weight mixture over several g-prior scales. A g-prior with a
    single g caps the attainable Bayes factor at ``(1+g)^((nu-1)/2)``, so
    large effects seen on few points cannot produce strong evidence with
    g = 1, while large g loses sensitivity to small effects; the mixture of
    e-values (itself an e-value) is robust to both. Returns the mixture log
    e-value and the evidence object of the largest g (least shrinkage), used
    for effect estimates."""
    gs = _as_gs(gs)
    evs = [gaussian_regression_evalue(y, x, w, g, intercept, sign, theta, extra_dof_lost) for g in gs]
    log_e = float(logsumexp([e.log_e for e in evs]) - np.log(len(evs)))
    return log_e, evs[int(np.argmax(gs))]


@dataclass
class GaussianTrendDetector:
    """E-process for a worsening linear trend of ``y`` against time ``x``."""

    g: float | tuple[float, ...] = (1.0, 10.0, 100.0)
    sign: int = +1
    xs: list[float] = field(default_factory=list)
    ys: list[float] = field(default_factory=list)
    ws: list[float] = field(default_factory=list)
    log_e: list[float] = field(default_factory=list)
    last: RegressionEvidence | None = None

    def update(self, x: float, y: float, w: float) -> float:
        self.xs.append(float(x))
        self.ys.append(float(y))
        self.ws.append(float(w))
        log_e, ev = gaussian_regression_mixture_evalue(self.ys, self.xs, self.ws, self.g, True, self.sign)
        self.last = ev
        self.log_e.append(log_e)
        return log_e


@dataclass
class GaussianChangeDetector:
    """E-process for a level shift of ``y`` in the worsening direction, mixed
    over geometric change times (step regressor ``1{u >= s}``)."""

    g: float | tuple[float, ...] = (1.0, 10.0, 100.0)
    sign: int = +1
    change_prior_mean: float = 48.0
    max_lookback: int | None = None
    ys: list[float] = field(default_factory=list)
    ws: list[float] = field(default_factory=list)
    log_e: list[float] = field(default_factory=list)
    last: dict = field(default_factory=dict)

    def update(self, y: float, w: float) -> float:
        self.ys.append(float(y))
        self.ws.append(float(w))
        T = len(self.ys)
        rho = 1.0 / self.change_prior_mean
        log_pi, log_tail = geometric_log_prior(T, rho)
        s_lo = 2 if self.max_lookback is None else max(2, T - self.max_lookback + 1)
        y_arr, w_arr = np.asarray(self.ys), np.asarray(self.ws)
        logs, b_means, b_scales, nus, ss = [], [], [], [], []
        for s in range(s_lo, T + 1):
            x = (np.arange(1, T + 1) >= s).astype(float)
            log_e_s, ev = gaussian_regression_mixture_evalue(y_arr, x, w_arr, self.g, True, self.sign)
            logs.append(log_pi[s - 1] + log_e_s)
            b_means.append(ev.b_post_mean)
            b_scales.append(ev.b_post_scale)
            nus.append(ev.nu)
            ss.append(s)
        # change at s = 1 is indistinguishable from "no change": its mass joins the tail
        log_tail = float(np.logaddexp(log_tail, log_pi[0]))
        if logs:
            log_e = float(np.logaddexp(logsumexp(logs), log_tail))
            post = np.exp(np.asarray(logs) - logsumexp(np.concatenate([logs, [log_tail]])))
            i = int(np.argmax(post))
            s_map, shift, scale, nu = ss[i], b_means[i], b_scales[i], nus[i]
            p_change = float(post.sum())
        else:
            log_e, s_map, shift, scale, nu, p_change = 0.0, None, None, None, None, 0.0
        self.log_e.append(log_e)
        self.last = {
            "log_e": log_e,
            "e": float(np.exp(min(log_e, 700))),
            "t": T,
            "change_time_map": s_map,
            "batches_since_change": None if s_map is None else T - s_map + 1,
            "shift_posterior_mean": shift,
            "shift_posterior_scale": scale,
            "shift_nu": nu,
            "p_change": p_change,
        }
        return log_e


@dataclass
class GaussianThresholdDetector:
    """Exact e-process for H0: ``mu_t`` on the safe side of ``theta`` for all
    t, for Gaussian observations with *known* standard deviations.

    ``sign=+1``: worsening means ``mu > theta``; ``-1``: ``mu < theta``. The
    alternative means are ``theta + sign * eps`` for ``eps`` log-spaced in
    ``[eps_min, eps_max]`` (in the units of ``y``), mixed over geometric
    change times. Each per-observation likelihood ratio has expectation
    <= 1 under every ``mu`` on the safe side (monotone likelihood ratio of
    the Gaussian location family), so the guarantee is exact when the
    ``sigma`` values are the true ones; with plug-in ``sigma`` it is
    approximate and labelled as such by the caller.
    """

    theta: float
    sign: int = +1
    eps_min: float = 0.02
    eps_max: float = 1.5
    n_eps: int = 24
    change_prior_mean: float = 48.0

    def __post_init__(self) -> None:
        if self.sign not in (-1, 1):
            raise ValueError("sign must be +1 or -1")
        self.alts = self.theta + self.sign * np.geomspace(self.eps_min, self.eps_max, self.n_eps)
        self.rho = 1.0 / self.change_prior_mean
        self._C: list[np.ndarray] = [np.zeros(self.alts.size)]
        self.log_e: list[float] = []
        self.last: dict = {}

    @property
    def t(self) -> int:
        return len(self.log_e)

    def update(self, y: float, sigma: float) -> float:
        if not np.isfinite(y) or not np.isfinite(sigma) or sigma <= 0:
            raise ValueError("y must be finite and sigma positive")
        lr = sps.norm.logpdf(y, self.alts, sigma) - sps.norm.logpdf(y, self.theta, sigma)
        self._C.append(self._C[-1] + lr)
        T = self.t + 1
        C = np.stack(self._C)
        log_pi_s, log_tail = geometric_log_prior(T, self.rho)
        terms = log_pi_s[:, None] - np.log(self.alts.size) + C[T][None, :] - C[:T]
        log_e = float(np.logaddexp(logsumexp(terms), log_tail))
        self.log_e.append(log_e)
        self.last = {"log_e": log_e, "e": float(np.exp(min(log_e, 700))), "t": T}
        return log_e
