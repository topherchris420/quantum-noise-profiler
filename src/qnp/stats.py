"""Bayesian toolkit: Beta posteriors for binomial evidence, a grid posterior
for exponential-decay characterization curves with model checking, and the
weighted linear trend used by the frozen v0.1 engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy import stats as sps
from scipy.special import logsumexp

from .models import Reason

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


# --------------------------------------------------------------------------- decay fits


@dataclass
class FitDiagnosticsConfig:
    """Model checks applied to every decay fit. Alphas are per-test; the
    overall rate at which *valid* single-exponential fits are rejected is
    measured in Experiment D (it is roughly their sum)."""

    deviance_alpha: float = 0.01  # chi-square test of the binomial deviance at the MAP
    ppc_alpha: float = 0.01  # posterior-predictive p-value of the deviance
    runs_alpha: float = 0.01  # Wald-Wolfowitz runs test on signed Pearson residuals
    outlier_z: float = 4.0  # |Pearson residual| flagged as a suspected outlier
    min_decay_fraction: float = 0.30  # fraction of the decay the delays must span
    min_informative_points: int = 3  # delays within [0.1 tau, 3 tau]
    compare_biexponential: bool = True
    biexp_log_bf_strong: float = float(np.log(100.0))
    n_ppc_draws: int = 200
    outlier_fraction: float = 0.0  # > 0: contaminated likelihood (opt-in robust fit)
    rng_seed: int = 0
    # Drift during acquisition (v0.3). Used only when the sweep's acquisition
    # order and/or interleaved reference circuits are supplied to the fit.
    reference_alpha: float = 0.01  # homogeneity of repeated reference circuits (G-test)
    # Runs test on residual signs in acquisition order: always reported in the
    # diagnostics; a rejection rule only if > 0. Off by default: in development
    # it added false rejections of valid fits without adding drift detection
    # beyond the references (experiments/v03/DEVELOPMENT_NOTES.md).
    acquisition_runs_alpha: float = 0.0


@dataclass(frozen=True)
class SweepReferences:
    """Repeated reference circuits interleaved in a decay sweep, e.g. ground
    references (prepare |0>, measure) whose outcome probability does not
    depend on the decay at all. ``successes`` count the same outcome as the
    sweep (e.g. ones); ``positions`` are acquisition positions."""

    positions: tuple[int, ...]
    successes: tuple[int, ...]
    shots: tuple[int, ...]

    def __post_init__(self) -> None:
        if not (len(self.positions) == len(self.successes) == len(self.shots)):
            raise ValueError("references need equally many positions, successes and shots")
        if any(n <= 0 or k < 0 or k > n for k, n in zip(self.successes, self.shots)):
            raise ValueError("reference counts must satisfy 0 <= successes <= shots, shots > 0")


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
    status: str = "ok"  # "ok" | "insufficient_evidence" | "model_misspecification"
    reasons: tuple[Reason, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)


def _loglik_grid(k, n, p, outlier_fraction: float = 0.0):
    """Binomial log-likelihood (without the constant) of each delay under rate grid p."""
    p = np.clip(p, 1e-9, 1 - 1e-9)
    ll = k * np.log(p) + (n - k) * np.log1p(-p)
    if outlier_fraction > 0:
        from scipy.special import gammaln

        const = gammaln(n + 1) - gammaln(k + 1) - gammaln(n - k + 1)
        full = ll + const
        ll = np.logaddexp(np.log1p(-outlier_fraction) + full, np.log(outlier_fraction) - np.log(n + 1)) - const
    return ll


def _deviance(k, n, p):
    p = np.clip(p, 1e-12, 1 - 1e-12)
    with np.errstate(divide="ignore", invalid="ignore"):
        t1 = np.where(k > 0, k * np.log(k / (n * p)), 0.0)
        t2 = np.where(n - k > 0, (n - k) * np.log((n - k) / (n * (1 - p))), 0.0)
    return float(2 * np.sum(t1 + t2))


def _runs_pvalue(signs: np.ndarray) -> float:
    from .forecast import runs_test_pvalue

    return runs_test_pvalue(signs)


def reference_homogeneity(successes, shots) -> tuple[float, float, int]:
    """Likelihood-ratio (G) test that repeated reference circuits share one
    outcome probability: returns (statistic, p-value, dof). A significant
    result means the measurement drifted while the sweep was acquired."""
    k = np.asarray(successes, float)
    n = np.asarray(shots, float)
    dof = int(k.size - 1)
    if dof < 1:
        return 0.0, 1.0, 0
    p = float(k.sum() / n.sum())
    stat = _deviance(k, n, np.full(k.size, p)) if 0 < p < 1 else 0.0
    return stat, float(sps.chi2.sf(stat, dof)), dof


def _acquisition_diagnostics(
    cfg: FitDiagnosticsConfig,
    delays: np.ndarray,
    positions: np.ndarray | None,
    references: SweepReferences | None,
    diag: dict[str, Any],
) -> list[Reason]:
    """Checks for measurement drift during acquisition that do not need the
    fit: homogeneity of interleaved reference circuits. Records whether the
    acquisition order confounds slow drift with the decay."""
    reasons: list[Reason] = []
    if positions is None:
        diag["acquisition_order"] = "not supplied"
    else:
        by_time = delays[np.argsort(positions, kind="stable")]
        confounded = bool(np.all(np.diff(by_time) >= 0) or np.all(np.diff(by_time) <= 0))
        diag["acquisition_order"] = "monotone in delay" if confounded else "not monotone in delay"
    if positions is None or diag["acquisition_order"] == "monotone in delay":
        diag["order_note"] = (
            "delays acquired in delay order (or order unknown): slow measurement drift during the sweep is "
            "confounded with the decay and cannot be detected by the fit checks"
        )
    if references is not None:
        stat, p, dof = reference_homogeneity(references.successes, references.shots)
        rates = [k / n for k, n in zip(references.successes, references.shots)]
        diag["references"] = {
            "n": len(rates),
            "positions": [int(x) for x in references.positions],
            "rates": [float(r) for r in rates],
            "g_statistic": float(stat),
            "dof": dof,
            "p": float(p),
        }
        if dof >= 1 and p < cfg.reference_alpha:
            reasons.append(
                Reason(
                    "READOUT_DRIFT",
                    f"interleaved reference circuits disagree (G={stat:.1f} on {dof} dof, p={p:.2g}): "
                    "the measurement drifted while the sweep was acquired",
                    float(p),
                    cfg.reference_alpha,
                )
            )
    return reasons


def _biexponential_log_evidence(
    delays,
    k,
    n,
    amp_range: tuple[float, float],
    offset_range: tuple[float, float],
    tau_range,
    n_tau=40,
    n_amp=15,
    n_off=15,
):
    """Log marginal likelihood of p(t) = A [f e^{-t/tau_s} + (1-f) e^{-t/tau_f}] + B
    with tau_f < tau_s, log-uniform taus, uniform f in [0.1, 0.9], A and B
    uniform on the given ranges. Returns (log evidence, posterior summaries)."""
    taus = np.geomspace(tau_range[0], tau_range[1], n_tau)
    i_f, i_s = np.triu_indices(n_tau, k=1)  # row < col: fast (shorter) tau first
    tau_s, tau_f = taus[i_s], taus[i_f]
    fs = np.linspace(0.1, 0.9, 9)
    amps = np.linspace(*amp_range, n_amp)
    offs = np.linspace(*offset_range, n_off)
    n_pairs = tau_s.size
    loglik = np.zeros((n_pairs, fs.size, n_amp, n_off))
    for j in range(delays.size):
        shape = (
            fs[None, :] * np.exp(-delays[j] / tau_s)[:, None] + (1 - fs[None, :]) * np.exp(-delays[j] / tau_f)[:, None]
        )
        p = amps[None, None, :, None] * shape[:, :, None, None] + offs[None, None, None, :]
        loglik += _loglik_grid(k[j], n[j], p)
    log_z = float(logsumexp(loglik) - np.log(loglik.size))
    post = np.exp(loglik - logsumexp(loglik))
    pair_post = post.sum(axis=(1, 2, 3))
    f_post = post.sum(axis=(0, 2, 3))
    ratio = tau_f / tau_s
    p_separated = float(pair_post[ratio < 0.5].sum())
    f_mean = float(np.sum(f_post * fs))
    i_map = int(np.argmax(pair_post))
    return log_z, {
        "tau_slow_map": float(tau_s[i_map]),
        "tau_fast_map": float(tau_f[i_map]),
        "p_ratio_below_half": p_separated,
        "f_slow_posterior_mean": f_mean,
        "identifiable": p_separated > 0.9 and 0.15 < f_mean < 0.85,
    }


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
    diagnostics: FitDiagnosticsConfig | bool | None = True,
    acquisition_positions=None,
    references: SweepReferences | None = None,
) -> DecayFit:
    """Grid posterior for p(t) = A*exp(-t/tau) + B under a binomial likelihood,
    with model checking.

    ``acquisition_positions`` (the order in which the sweep points were
    acquired) and ``references`` (interleaved reference circuits) enable the
    checks for measurement drift during the sweep: a runs test on the
    residuals in acquisition order and a homogeneity test of the references.
    Both need a design whose acquisition order is not monotone in delay
    (``qnp.measured.decay_sweep_plan``); with delays acquired in order, a
    slow drift bends the curve smoothly and is indistinguishable from the
    decay (v0.2 Experiment D11).

    Prior: log-uniform on tau over ``tau_range`` (default: 1/20 of the shortest
    non-zero delay to 20x the longest), uniform on A and B over the given
    ranges. A and B absorb SPAM error and are marginalized out.

    The fit is reported as ``insufficient_evidence`` when the delays do not
    resolve tau (posterior mass piled at the edge of the tau prior, or the
    delays span too little of the decay) and as ``model_misspecification``
    when the data contradict a single exponential (binomial deviance at the
    MAP against chi-square, posterior-predictive deviance check, runs test
    on the signed residuals). In neither case is a value returned. A
    bi-exponential alternative is scored for *diagnosis only*; it is never
    substituted for the single-exponential estimate.
    """
    cfg = (
        diagnostics
        if isinstance(diagnostics, FitDiagnosticsConfig)
        else (FitDiagnosticsConfig() if diagnostics else None)
    )
    delays = np.asarray(delays, dtype=float)
    k = np.asarray(successes, dtype=float)
    n = np.broadcast_to(np.asarray(shots, dtype=float), k.shape).astype(float)
    if delays.shape != k.shape or k.ndim != 1:
        raise ValueError("delays and successes must be 1-d arrays of equal length")
    if not np.all(np.isfinite(delays)) or np.any(delays < 0):
        raise ValueError("delays must be finite and non-negative")
    if np.any(k < 0) or np.any(k > n) or np.any(n <= 0):
        raise ValueError("successes must satisfy 0 <= successes <= shots with shots > 0")
    if delays.size < 3 or np.unique(delays).size < 3:
        r = Reason("TOO_FEW_DELAYS", "need at least 3 distinct delays", float(np.unique(delays).size), 3)
        return DecayFit(False, None, None, None, level, r.message, status="insufficient_evidence", reasons=(r,))
    positions = None
    if acquisition_positions is not None:
        positions = np.asarray(acquisition_positions)
        if positions.shape != delays.shape or np.unique(positions).size != positions.size:
            raise ValueError("acquisition_positions must give one distinct position per delay")

    if tau_range is None:
        positive = delays[delays > 0]
        if positive.size == 0:
            raise ValueError("all delays are zero")
        tau_range = (positive.min() / 20, delays.max() * 20)
    taus = np.geomspace(tau_range[0], tau_range[1], n_tau)
    amps = np.linspace(*amp_range, n_amp)
    offs = np.linspace(*offset_range, n_off)
    of = cfg.outlier_fraction if cfg is not None else 0.0

    loglik = np.zeros((n_tau, n_amp, n_off))
    decay = np.exp(-delays[None, :] / taus[:, None])  # (n_tau, n_delays)
    for j in range(delays.size):
        p = amps[None, :, None] * decay[:, j][:, None, None] + offs[None, None, :]
        loglik += _loglik_grid(k[j], n[j], p, of)

    log_marg = logsumexp(loglik, axis=(1, 2))  # log-uniform prior == uniform on grid
    post = np.exp(log_marg - logsumexp(log_marg))
    log_evidence_single = float(logsumexp(loglik) - np.log(loglik.size))

    edge = max(1, int(0.02 * n_tau))
    edge_mass = float(post[:edge].sum() + post[-edge:].sum())
    diag: dict[str, Any] = {"edge_mass": edge_mass, "tau_prior_range": [float(tau_range[0]), float(tau_range[1])]}
    drift_reasons = _acquisition_diagnostics(cfg, delays, positions, references, diag) if cfg is not None else []
    if edge_mass > edge_mass_limit:
        r = Reason(
            "TAU_AT_PRIOR_EDGE",
            f"{edge_mass:.0%} of posterior mass at the edge of the tau prior range; "
            "delays do not bracket the decay time",
            edge_mass,
            edge_mass_limit,
        )
        rs = (r, *drift_reasons)
        msg = "; ".join(x.message for x in rs)
        return DecayFit(False, None, None, None, level, msg, taus, post, "insufficient_evidence", rs, diag)

    cdf = np.cumsum(post)
    log_t = np.log(taus)
    a = (1 - level) / 2
    q = lambda x: float(np.exp(np.interp(x, cdf, log_t)))
    med, lo, hi = q(0.5), q(a), q(1 - a)

    if cfg is None:
        return DecayFit(True, med, lo, hi, level, "", taus, post, "ok", (), diag)

    # ---------------------------------------------------------------- diagnostics
    reasons: list[Reason] = []
    i_t, i_a, i_o = np.unravel_index(int(np.argmax(loglik)), loglik.shape)
    tau_map, a_map, b_map = float(taus[i_t]), float(amps[i_a]), float(offs[i_o])
    p_hat = np.clip(a_map * np.exp(-delays / tau_map) + b_map, 1e-9, 1 - 1e-9)
    diag["map"] = {"tau": tau_map, "amplitude": a_map, "offset": b_map}
    # marginal posteriors of the nuisance parameters, for transparency
    post_ab = np.exp(loglik - logsumexp(loglik))
    pa, pb = post_ab.sum(axis=(0, 2)), post_ab.sum(axis=(0, 1))
    diag["amplitude_posterior_mean"] = float(np.sum(pa * amps))
    diag["offset_posterior_mean"] = float(np.sum(pb * offs))
    diag["amplitude_edge_mass"] = float(pa[0] + pa[-1])
    diag["offset_edge_mass"] = float(pb[0] + pb[-1])

    # delay-range coverage
    order = np.argsort(delays)
    t_min, t_max = float(delays[order][0]), float(delays[order][-1])
    frac = float(np.exp(-t_min / med) - np.exp(-t_max / med))
    informative = int(np.sum((delays >= 0.1 * med) & (delays <= 3 * med)))
    diag["decay_fraction_spanned"] = frac
    diag["informative_points"] = informative
    if frac < cfg.min_decay_fraction:
        reasons.append(
            Reason(
                "DELAY_RANGE_COVERAGE",
                f"delays span {frac:.0%} of the decay (< {cfg.min_decay_fraction:.0%})",
                frac,
                cfg.min_decay_fraction,
            )
        )
    if informative < cfg.min_informative_points:
        reasons.append(
            Reason(
                "FEW_INFORMATIVE_DELAYS",
                f"{informative} delays within [0.1, 3] x tau (< {cfg.min_informative_points})",
                float(informative),
                cfg.min_informative_points,
            )
        )
    if reasons:
        reasons += drift_reasons
        return DecayFit(
            False,
            None,
            None,
            None,
            level,
            "; ".join(r.message for r in reasons),
            taus,
            post,
            "insufficient_evidence",
            tuple(reasons),
            diag,
        )

    # goodness of fit: deviance at the MAP vs chi-square
    dev = _deviance(k, n, p_hat)
    dof = int(delays.size - 3)
    p_dev = float(sps.chi2.sf(dev, dof)) if dof > 0 else float("nan")
    diag["deviance"] = dev
    diag["deviance_dof"] = dof
    diag["deviance_p"] = p_dev
    # residual structure
    resid = (k - n * p_hat) / np.sqrt(n * p_hat * (1 - p_hat))
    runs_p = _runs_pvalue(np.sign(resid[order]))
    diag["pearson_residuals"] = [float(x) for x in resid]
    diag["runs_test_p"] = runs_p
    acq_runs_p = None
    if positions is not None and diag["acquisition_order"] == "not monotone in delay":
        acq_runs_p = _runs_pvalue(np.sign(resid[np.argsort(positions, kind="stable")]))
        diag["acquisition_runs_test_p"] = acq_runs_p
    outliers = [int(i) for i in np.flatnonzero(np.abs(resid) > cfg.outlier_z)]
    diag["suspected_outliers"] = outliers
    diag["max_abs_residual"] = float(np.max(np.abs(resid)))
    if of > 0:
        from scipy.special import gammaln

        const = gammaln(n + 1) - gammaln(k + 1) - gammaln(n - k + 1)
        full = k * np.log(p_hat) + (n - k) * np.log1p(-p_hat) + const
        p_out = of / (n + 1) / ((1 - of) * np.exp(full) + of / (n + 1))
        diag["outlier_posterior_probability"] = [float(x) for x in p_out]
    # posterior predictive check of the deviance
    rng = np.random.default_rng(cfg.rng_seed)
    flat = post_ab.ravel()
    idx = rng.choice(flat.size, size=cfg.n_ppc_draws, p=flat / flat.sum())
    it, ia, io = np.unravel_index(idx, loglik.shape)
    ge = 0
    for s in range(cfg.n_ppc_draws):
        p_s = np.clip(amps[ia[s]] * np.exp(-delays / taus[it[s]]) + offs[io[s]], 1e-9, 1 - 1e-9)
        k_rep = rng.binomial(n.astype(int), p_s)
        ge += _deviance(k_rep, n, p_s) >= _deviance(k, n, p_s)
    p_ppc = (ge + 1) / (cfg.n_ppc_draws + 1)
    diag["ppc_p"] = float(p_ppc)

    if dof > 0 and p_dev < cfg.deviance_alpha:
        reasons.append(
            Reason("DEVIANCE", f"binomial deviance {dev:.1f} on {dof} dof, p={p_dev:.2g}", p_dev, cfg.deviance_alpha)
        )
    if p_ppc < cfg.ppc_alpha:
        reasons.append(
            Reason("POSTERIOR_PREDICTIVE", f"posterior-predictive p={p_ppc:.2g}", float(p_ppc), cfg.ppc_alpha)
        )
    if runs_p < cfg.runs_alpha:
        reasons.append(Reason("RESIDUAL_RUNS", f"runs test on residual signs p={runs_p:.2g}", runs_p, cfg.runs_alpha))
    if acq_runs_p is not None and acq_runs_p < cfg.acquisition_runs_alpha:
        reasons.append(
            Reason(
                "ACQUISITION_RUNS",
                f"runs test on residual signs in acquisition order p={acq_runs_p:.2g}: "
                "the misfit follows acquisition time, not delay",
                acq_runs_p,
                cfg.acquisition_runs_alpha,
            )
        )
    reasons += drift_reasons

    # bi-exponential comparison, diagnosis only
    if cfg.compare_biexponential:
        log_z2, bi = _biexponential_log_evidence(delays, k, n, amp_range, offset_range, tau_range)
        log_bf = log_z2 - log_evidence_single
        diag["biexponential"] = {"log_bf_vs_single": float(log_bf), **bi}
        if reasons and log_bf >= cfg.biexp_log_bf_strong and bi["identifiable"]:
            reasons.append(
                Reason(
                    "BI_EXPONENTIAL_PREFERRED",
                    f"two-component decay preferred (log BF {log_bf:.1f}); "
                    "no single relaxation time describes the data",
                    float(log_bf),
                    cfg.biexp_log_bf_strong,
                )
            )
    if reasons:
        if 0 < len(outliers) <= 2:
            reasons.append(
                Reason("OUTLIERS", f"suspected outliers at delay indices {outliers}", float(len(outliers)), 0)
            )
        return DecayFit(
            False,
            None,
            None,
            None,
            level,
            "; ".join(r.message for r in reasons),
            taus,
            post,
            "model_misspecification",
            tuple(reasons),
            diag,
        )
    return DecayFit(True, med, lo, hi, level, "", taus, post, "ok", (), diag)


# --------------------------------------------------------------------------- legacy trend


@dataclass(frozen=True)
class TrendFit:
    slope_mean: float
    slope_sd: float
    intercept_mean: float
    cov: np.ndarray
    n: int


def weighted_linear_trend(t: np.ndarray, y: np.ndarray, sigma: np.ndarray | None) -> TrendFit:
    """Bayesian linear regression with flat prior (used by the frozen v0.1 engine).

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
