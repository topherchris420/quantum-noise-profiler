"""Sequentially calibrated drift, threshold and forecast analysis (v0.2).

A monitoring *family* is the set of (qubit, metric) groups the profiler
watches; each group may hold several context series (e.g. ``ideal=0`` and
``ideal=1`` flip rates of one qubit). The session error budget
``alpha_session`` is split explicitly:

* across channels (drift / threshold / forecast) by fixed shares,
* across the declared number of qubits and metrics by a union bound,
* across the contexts of one group by averaging their e-values (the average
  of e-values is an e-value, so no further split is needed).

Within each series the evidence is an e-process (``qnp.sequential``), so the
repeated testing over *time* costs nothing extra: by Ville's inequality the
probability that a series' e-process ever exceeds ``1/alpha_series`` is at
most ``alpha_series`` under its null, for any session length.

An alert additionally requires the deterioration to be *meaningful*:
large enough (posterior probability that the relative change is at least
``min_relative_change``), persistent (at least ``persistence_batches``
since the most probable change point), and, for forecasts, projected to
cross the operational threshold within a defensible horizon.

What the guarantee covers is stated on every alert (``details["guarantee"]``):
``exact`` (binomial threshold; Gaussian with reported sigma),
``bayesian_marginal`` (binomial change: valid under the Beta prior on the
unknown rate, measured empirically at fixed rates), ``gaussian_approx``
(trend on binomial rates), ``plug_in`` (vendor values without uncertainty).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
from scipy import stats as sps
from scipy.special import logsumexp

from .forecast import ForecastConfig, ForecastReport, apply_evidence_gate, forecast_series
from .models import Alert, AlertLevel, Estimate, ForecastStatus, Metric, Provenance, Status
from .sequential import (
    BinomialChangeDetector,
    BinomialThresholdDetector,
    GaussianChangeDetector,
    GaussianThresholdDetector,
    GaussianTrendDetector,
    geometric_log_prior,
)

HIGHER_IS_WORSE = {Metric.EFFECTIVE_FLIP, Metric.READOUT_ERROR, Metric.GATE_ERROR}
LOG_SCALE = {Metric.T1, Metric.T2}
CHANNELS = ("drift", "threshold", "forecast")


@dataclass
class ErrorBudget:
    """Explicit family-wise error budget for one monitoring session."""

    alpha_session: float = 0.10
    shares: dict[str, float] = field(default_factory=lambda: {"drift": 0.5, "threshold": 0.25, "forecast": 0.25})
    n_qubits: int | None = None  # declared family size; None -> frozen at the first check
    n_metrics: int | None = None

    def __post_init__(self) -> None:
        if not 0 < self.alpha_session < 1:
            raise ValueError("alpha_session must be in (0, 1)")
        if set(self.shares) != set(CHANNELS) or any(v < 0 for v in self.shares.values()):
            raise ValueError(f"shares must be non-negative and cover exactly {CHANNELS}")
        if abs(sum(self.shares.values()) - 1.0) > 1e-9:
            raise ValueError("shares must sum to 1")
        for name in ("n_qubits", "n_metrics"):
            v = getattr(self, name)
            if v is not None and (not isinstance(v, int) or v < 1):
                raise ValueError(f"{name} must be a positive int or None")

    def alpha_series(self, channel: str, n_qubits: int, n_metrics: int) -> float:
        return self.alpha_session * self.shares[channel] / (n_qubits * n_metrics)


@dataclass
class DriftConfig:
    budget: ErrorBudget = field(default_factory=ErrorBudget)
    # Recalibration thresholds. Error metrics: alert above. T1/T2: alert below.
    thresholds: dict[Metric, float] = field(
        default_factory=lambda: {Metric.EFFECTIVE_FLIP: 0.05, Metric.READOUT_ERROR: 0.05}
    )
    min_relative_change: float = 0.10
    max_relative_change: float = 3.0
    min_baseline_batches: int = 3
    change_prior_mean_batches: float = 48.0
    persistence_batches: int = 2
    effect_gate_probability: float = 0.5
    combine_contexts: str = "mixture"  # "mixture": 1/2 average + 1/2 shared-change; "average"
    g_prior: tuple[float, ...] = (1.0, 10.0, 100.0)
    max_lookback: int | None = None
    forecast: ForecastConfig = field(default_factory=ForecastConfig)
    # Empirical calibration: every e-value threshold is divided by
    # exp(log_e_offset). 0 keeps the anytime-valid thresholds; a positive
    # value trades the theoretical guarantee for an empirically calibrated
    # false-alert rate (see experiments/V02_PREREGISTRATION.md) and is
    # reported on every alert as guarantee "...+calibrated".
    log_e_offset: float = 0.0

    def __post_init__(self) -> None:
        if self.combine_contexts not in ("mixture", "average"):
            raise ValueError("combine_contexts must be 'mixture' or 'average'")
        if not 0 < self.min_relative_change < self.max_relative_change:
            raise ValueError("need 0 < min_relative_change < max_relative_change")
        if self.persistence_batches < 1:
            raise ValueError("persistence_batches must be >= 1")
        if not np.isfinite(self.log_e_offset) or self.log_e_offset < 0:
            raise ValueError("log_e_offset must be finite and >= 0")
        for m, thr in self.thresholds.items():
            if not isinstance(m, Metric) or not np.isfinite(thr) or thr <= 0:
                raise ValueError(f"invalid threshold {thr!r} for {m!r}")


# --------------------------------------------------------------------------- series state


def _z(level: float | None) -> float:
    return float(sps.norm.ppf(0.5 + (level or 0.95) / 2))


def series_kind(es: Sequence[Estimate]) -> str:
    if all(e.trials is not None for e in es):
        return "binomial"
    if all(e.ci_low is not None and e.ci_high is not None for e in es):
        return "interval"
    return "point"


class SeriesState:
    """Incremental sequential state for one series (metric, qubits, context, provenance)."""

    def __init__(self, key, metric: Metric, config: DriftConfig, threshold: float | None):
        self.key = key
        self.metric = metric
        self.config = config
        self.higher_is_worse = metric in HIGHER_IS_WORSE
        self.log_scale = metric in LOG_SCALE
        self.threshold = threshold
        self.kind: str | None = None
        self.signature: list[tuple] = []
        self.t0: datetime | None = None
        self.t_hours: list[float] = []
        self.y: list[float] = []
        self.w: list[float] = []
        self.sigma_known: list[bool] = []
        self.change: Any = None
        self.thr: Any = None
        self.trend: GaussianTrendDetector | None = None
        self.thr_log_e: list[float] = []
        self.guarantee = {"drift": "", "threshold": "", "forecast": ""}

    # -- construction -------------------------------------------------------
    def _reset(self, kind: str, t0: datetime) -> None:
        c = self.config
        self.kind, self.t0 = kind, t0
        self.signature, self.t_hours, self.y, self.w, self.thr_log_e = [], [], [], [], []
        sign = +1 if self.higher_is_worse else -1
        if kind == "binomial":
            self.change = BinomialChangeDetector(
                c.min_relative_change,
                c.max_relative_change,
                10,
                16,
                c.min_baseline_batches,
                c.change_prior_mean_batches,
                max_lookback=c.max_lookback,
            )
            self.thr = (
                BinomialThresholdDetector(self.threshold, change_prior_mean=c.change_prior_mean_batches)
                if self.threshold is not None
                else None
            )
            self.guarantee = {"drift": "bayesian_marginal", "threshold": "exact", "forecast": "gaussian_approx"}
        else:
            self.change = GaussianChangeDetector(c.g_prior, sign, c.change_prior_mean_batches, c.max_lookback)
            self.thr = None  # built lazily (needs sigma)
            if kind == "interval":
                self.guarantee = {"drift": "exact", "threshold": "exact", "forecast": "exact"}
            else:
                self.guarantee = {"drift": "exact", "threshold": "plug_in", "forecast": "exact"}
        self.trend = GaussianTrendDetector(c.g_prior, sign)

    def _analysis_space(self, e: Estimate) -> tuple[float, float, bool]:
        """(y, w, sigma_known) for one estimate."""
        if self.kind == "binomial":
            k, n = e.successes, e.trials
            a, b = k + 0.5, n - k + 0.5
            mean = a / (a + b)
            var = a * b / ((a + b) ** 2 * (a + b + 1))
            return float(mean), float(1 / var), True
        if self.log_scale:
            if e.value <= 0 or (e.ci_low is not None and e.ci_low <= 0):
                raise ValueError(f"non-positive value/interval for log-scale metric {self.metric.value}: {e}")
            y = float(np.log(e.value))
            if self.kind == "interval":
                sig = (np.log(e.ci_high) - np.log(e.ci_low)) / (2 * _z(e.ci_level))
                return y, float(1 / sig**2), True
            return y, 1.0, False
        y = float(e.value)
        if self.kind == "interval":
            sig = (e.ci_high - e.ci_low) / (2 * _z(e.ci_level))
            if sig <= 0:
                raise ValueError(f"degenerate interval for {e}")
            return y, float(1 / sig**2), True
        return y, 1.0, False

    def _plug_in_sigma(self) -> float | None:
        if len(self.y) < 3:
            return None
        mad = float(np.median(np.abs(np.array(self.y) - np.median(self.y))))
        return 1.4826 * mad if mad > 0 else float(np.std(self.y, ddof=1)) or None

    def feed(self, es: Sequence[Estimate]) -> None:
        """Extend the state with ``es`` (sorted, OK only); rebuild if ``es`` is not an extension."""
        sig = [(e.timestamp.isoformat(), e.value, e.successes, e.trials, e.ci_low, e.ci_high) for e in es]
        kind = series_kind(es)
        if self.kind != kind or sig[: len(self.signature)] != self.signature or len(sig) < len(self.signature):
            self._reset(kind, es[0].timestamp)
        for e, s in zip(es[len(self.signature) :], sig[len(self.signature) :], strict=True):
            if self.signature and s[0] == self.signature[-1][0]:
                raise ValueError(f"duplicate observation at {s[0]} in series {self.key}")
            self._push(e)
            self.signature.append(s)

    def _push(self, e: Estimate) -> None:
        y, w, known = self._analysis_space(e)
        t = (e.timestamp - self.t0).total_seconds() / 3600
        self.t_hours.append(t)
        self.y.append(y)
        self.w.append(w)
        self.sigma_known.append(known)
        if self.kind == "binomial":
            self.change.update(e.successes, e.trials)
            if self.thr is not None:
                self.thr_log_e.append(self.thr.update(e.successes, e.trials))
        else:
            self.change.update(y, w)
            if self.threshold is not None:
                theta = float(np.log(self.threshold)) if self.log_scale else float(self.threshold)
                sign = +1 if self.higher_is_worse else -1
                if self.kind == "interval":
                    if self.thr is None:
                        eps_max = 1.5 if self.log_scale else max(0.02, 5 * theta)
                        self.thr = GaussianThresholdDetector(
                            theta, sign, 0.02, eps_max, 24, self.config.change_prior_mean_batches
                        )
                    self.thr_log_e.append(self.thr.update(y, 1 / np.sqrt(w)))
                else:
                    sigma = self._plug_in_sigma()
                    if sigma is not None:
                        if self.thr is None:
                            eps_max = 1.5 if self.log_scale else max(0.02, 5 * theta)
                            self.thr = GaussianThresholdDetector(
                                theta, sign, 0.02, eps_max, 24, self.config.change_prior_mean_batches
                            )
                        self.thr_log_e.append(self.thr.update(y, sigma))
        self.trend.update(t, y, w)

    # -- evidence -----------------------------------------------------------
    @property
    def n(self) -> int:
        return len(self.y)

    def drift_log_e(self) -> float:
        return self.change.log_e[-1] if self.change.log_e else 0.0

    def threshold_log_e(self) -> float | None:
        return self.thr_log_e[-1] if self.thr_log_e else None

    def trend_log_e(self) -> float:
        return self.trend.log_e[-1] if self.trend and self.trend.log_e else 0.0

    def effect_probability(self) -> tuple[float | None, dict]:
        """Posterior P(relative deterioration >= min_relative_change) across the
        most probable change point, and a summary of the effect."""
        last = self.change.last
        s = last.get("change_time_map")
        if s is None:
            return None, {}
        rel = self.config.min_relative_change
        if self.kind == "binomial":
            ks, ns = np.array(self.change.ks), np.array(self.change.ns)
            k1, n1 = ks[: s - 1].sum(), ns[: s - 1].sum()
            k2, n2 = ks[s - 1 :].sum(), ns[s - 1 :].sum()
            if n1 == 0 or n2 == 0:
                return None, {}
            a1, b1, a2, b2 = k1 + 0.5, n1 - k1 + 0.5, k2 + 0.5, n2 - k2 + 0.5
            q = (np.arange(400) + 0.5) / 400
            p1 = sps.beta.ppf(q, a1, b1)
            prob = float(np.mean(sps.beta.sf(np.clip((1 + rel) * p1, 0, 1), a2, b2)))
            base, recent = a1 / (a1 + b1), a2 / (a2 + b2)
            return prob, {
                "baseline": float(base),
                "recent": float(recent),
                "relative_change": float(recent / base - 1),
                "baseline_batches": int(s - 1),
                "recent_batches": int(len(ks) - s + 1),
            }
        shift, scale, nu = last.get("shift_posterior_mean"), last.get("shift_posterior_scale"), last.get("shift_nu")
        if shift is None or scale is None or not np.isfinite(scale) or scale <= 0:
            return None, {}
        bound = (
            float(np.log1p(rel) if self.higher_is_worse else np.log1p(-rel))
            if self.log_scale
            else rel * abs(np.mean(self.y[: s - 1]))
        )
        if self.higher_is_worse:
            prob = float(sps.t.sf((bound - shift) / scale, nu))
        else:
            prob = float(sps.t.cdf((bound - shift) / scale, nu))
        base = float(np.exp(np.mean(self.y[: s - 1])) if self.log_scale else np.mean(self.y[: s - 1]))
        recent = float(np.exp(np.mean(self.y[s - 1 :])) if self.log_scale else np.mean(self.y[s - 1 :]))
        return prob, {
            "baseline": base,
            "recent": recent,
            "relative_change": float(recent / base - 1) if base else None,
            "baseline_batches": int(s - 1),
            "recent_batches": int(self.n - s + 1),
        }

    def current(self) -> tuple[float, float | None]:
        """Current level in metric units and, if a threshold exists, the
        posterior probability of being beyond it (Bayesian evidence, not a test)."""
        if self.kind == "binomial":
            m = min(3, self.n)
            k = sum(self.change.ks[-m:])
            n = sum(self.change.ns[-m:])
            a, b = k + 0.5, n - k + 0.5
            p = float(sps.beta.sf(self.threshold, a, b)) if self.threshold is not None else None
            return float(a / (a + b)), p
        y = float(self.y[-1])
        val = float(np.exp(y)) if self.log_scale else y
        if self.threshold is None:
            return val, None
        theta = np.log(self.threshold) if self.log_scale else self.threshold
        sigma = 1 / np.sqrt(self.w[-1]) if self.sigma_known[-1] else self._plug_in_sigma()
        if sigma is None:
            return val, None
        p = float(sps.norm.sf(theta, y, sigma) if self.higher_is_worse else sps.norm.cdf(theta, y, sigma))
        return val, p

    def forecast(self, now: datetime, log_e_threshold: float | None) -> ForecastReport:
        thr_y = None
        if self.threshold is not None:
            thr_y = float(np.log(self.threshold)) if self.log_scale else float(self.threshold)
        now_h = (now - self.t0).total_seconds() / 3600
        return forecast_series(
            np.array(self.t_hours),
            np.array(self.y),
            np.array(self.w),
            self.higher_is_worse,
            thr_y,
            now_h,
            self.config.forecast,
            log_e_threshold,
        )


# --------------------------------------------------------------------------- group analysis


def _shared_change_log_e(states: list[SeriesState], config: DriftConfig) -> float | None:
    """Shared (s, delta) change across synchronous binomial contexts: product
    over contexts of node-averaged likelihood ratios, mixed over (s, delta)."""
    if len(states) < 2 or any(st.kind != "binomial" for st in states):
        return None
    terms_list, s_ref = [], None
    for st in states:
        s_idx, terms = st.change.log_terms()
        if s_ref is None:
            s_ref = s_idx
        elif s_idx.shape != s_ref.shape or not np.array_equal(s_idx, s_ref):
            return None
        terms_list.append(terms)
    T = states[0].change.t
    if any(st.change.t != T for st in states):
        return None
    log_pi, log_tail = geometric_log_prior(T, 1.0 / config.change_prior_mean_batches)
    if s_ref.size == 0:
        return 0.0
    inactive = np.ones(T, dtype=bool)
    inactive[s_ref - 1] = False
    if inactive.any():
        log_tail = float(np.logaddexp(log_tail, logsumexp(log_pi[inactive])))
    D = terms_list[0].shape[1]
    joint = log_pi[s_ref - 1][:, None] - np.log(D) + sum(terms_list)
    return float(np.logaddexp(logsumexp(joint), log_tail))


def _g(label: str, config: DriftConfig) -> str:
    return f"{label}+calibrated" if config.log_e_offset > 0 else label


def _log_mean_exp(logs: Sequence[float]) -> float:
    return float(logsumexp(np.asarray(logs, float)) - np.log(len(logs)))


@dataclass
class GroupReport:
    metric: Metric
    qubits: tuple[int, ...]
    provenance: Provenance
    contexts: list[str]
    kind: str
    n_batches: int
    alpha: dict[str, float]
    drift: dict[str, Any]
    threshold: dict[str, Any]
    forecast: dict[str, Any]
    alerts: list[Alert]

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric.value,
            "qubits": list(self.qubits),
            "provenance": self.provenance.value,
            "contexts": self.contexts,
            "kind": self.kind,
            "n_batches": self.n_batches,
            "alpha": self.alpha,
            "drift": self.drift,
            "threshold": self.threshold,
            "forecast": self.forecast,
            "alerts": [a.to_dict() for a in self.alerts],
        }


def analyze_group(
    series: dict[str, Sequence[Estimate]],
    config: DriftConfig,
    now: datetime | None,
    baseline_since: datetime | None,
    alpha: dict[str, float],
    states: dict[Any, SeriesState],
) -> GroupReport | None:
    """Analyse all context series of one (metric, qubits, provenance) group.

    ``alpha`` holds the per-group error rates for the three channels;
    ``states`` is the caller's cache of ``SeriesState`` keyed by series key.
    """
    live: dict[str, tuple[list[Estimate], SeriesState]] = {}
    for ctx, es in series.items():
        ok = sorted((e for e in es if e.status is Status.OK and e.value is not None), key=lambda e: e.timestamp)
        if baseline_since is not None:
            ok = [e for e in ok if e.timestamp >= baseline_since]
        if not ok:
            continue
        key = ok[0].series_key
        thr = config.thresholds.get(ok[0].metric)
        st = states.get(key)
        if st is None or st.threshold != thr:
            st = states[key] = SeriesState(key, ok[0].metric, config, thr)
        st.feed(ok)
        live[ctx] = (ok, st)
    if not live:
        return None
    ctxs = sorted(live)
    sts = [live[c][1] for c in ctxs]
    latest = max((live[c][0][-1] for c in ctxs), key=lambda e: e.timestamp)
    now = now or latest.timestamp
    metric, qubits, prov = latest.metric, latest.qubits, latest.provenance
    label = f"q{','.join(map(str, qubits))} {metric.value}"
    kind = sts[0].kind if len({s.kind for s in sts}) == 1 else "mixed"
    n_batches = max(s.n for s in sts)
    alerts: list[Alert] = []

    def alert(level, kind_, ctx, msg, **details):
        alerts.append(Alert(level, kind_, metric, qubits, prov, ctx, msg, now, details))

    # ---- threshold (CRITICAL) ---------------------------------------------
    thr = config.thresholds.get(metric)
    thr_report: dict[str, Any] = {"threshold": thr, "per_context": {}}
    if thr is not None:
        logs = [s.threshold_log_e() for s in sts]
        logs_ok = [x for x in logs if x is not None]
        for c, s in zip(ctxs, sts):
            cur, p_beyond = s.current()
            thr_report["per_context"][c] = {
                "log_e": s.threshold_log_e(),
                "current": cur,
                "p_beyond_posterior": p_beyond,
            }
        if logs_ok:
            log_e = _log_mean_exp(logs_ok)
            bar_nominal = float(np.log(1 / alpha["threshold"]))
            bar = bar_nominal - config.log_e_offset
            lead = ctxs[int(np.argmax([x if x is not None else -np.inf for x in logs]))]
            cur, p_beyond = live[lead][1].current()
            thr_report.update(
                log_e=log_e,
                e=float(np.exp(min(log_e, 700))),
                log_e_threshold=bar,
                log_e_threshold_nominal=bar_nominal,
                alarm=log_e >= bar,
                leading_context=lead,
                current=cur,
                p_beyond_posterior=p_beyond,
                guarantee=_g(live[lead][1].guarantee["threshold"], config),
            )
            if log_e >= bar:
                alert(
                    AlertLevel.CRITICAL,
                    "threshold",
                    lead,
                    f"{label} [{lead}] = {cur:.4g} is beyond recalibration threshold {thr:g} "
                    f"(e={np.exp(min(log_e, 700)):.3g} >= {np.exp(bar):.3g}; posterior P={p_beyond:.3f})",
                    threshold=thr,
                    current=cur,
                    probability=p_beyond,
                    e_value=float(np.exp(min(log_e, 700))),
                    e_threshold=float(np.exp(bar)),
                    alpha_series=alpha["threshold"],
                    guarantee=_g(live[lead][1].guarantee["threshold"], config),
                    evidence=kind,
                    contexts=ctxs,
                )

    # ---- drift (WARNING) ----------------------------------------------------
    logs = [s.drift_log_e() for s in sts]
    log_avg = _log_mean_exp(logs)
    log_shared = _shared_change_log_e(sts, config) if config.combine_contexts == "mixture" else None
    log_group = float(np.logaddexp(log_avg - np.log(2), log_shared - np.log(2))) if log_shared is not None else log_avg
    bar_nominal = float(np.log(1 / alpha["drift"]))
    bar = bar_nominal - config.log_e_offset
    i_lead = int(np.argmax(logs))
    lead, lead_st = ctxs[i_lead], sts[i_lead]
    p_effect, effect = lead_st.effect_probability()
    since = lead_st.change.last.get("batches_since_change")
    gates = {
        "evidence": log_group >= bar,
        "effect": p_effect is not None and p_effect >= config.effect_gate_probability,
        "persistence": since is not None and since >= config.persistence_batches,
    }
    drift_report = {
        "log_e": log_group,
        "e": float(np.exp(min(log_group, 700))),
        "log_e_threshold": bar,
        "log_e_threshold_nominal": bar_nominal,
        "log_e_average": log_avg,
        "log_e_shared": log_shared,
        "per_context_log_e": dict(zip(ctxs, logs)),
        "leading_context": lead,
        "change_time_map": lead_st.change.last.get("change_time_map"),
        "batches_since_change": since,
        "p_effect_at_least_min": p_effect,
        "effect": effect,
        "gates": gates,
        "alarm": all(gates.values()),
        "guarantee": _g(lead_st.guarantee["drift"], config),
    }
    if all(gates.values()):
        direction = "up" if effect.get("relative_change", 0) > 0 else "down"
        alert(
            AlertLevel.WARNING,
            "drift",
            lead,
            f"{label} [{lead}] drifted {direction}: baseline {effect['baseline']:.4g} -> recent {effect['recent']:.4g} "
            f"({effect['relative_change']:+.0%} over {since} batches; "
            f"e={np.exp(min(log_group, 700)):.3g} >= {np.exp(bar):.3g}, "
            f"P(change >= {config.min_relative_change:.0%})={p_effect:.2f})",
            baseline=effect["baseline"],
            recent=effect["recent"],
            min_relative_change=config.min_relative_change,
            probability=p_effect,
            e_value=float(np.exp(min(log_group, 700))),
            e_threshold=float(np.exp(bar)),
            alpha_series=alpha["drift"],
            guarantee=_g(lead_st.guarantee["drift"], config),
            evidence=kind,
            contexts=ctxs,
            change_time_map=lead_st.change.last.get("change_time_map"),
            batches_since_change=since,
        )

    # ---- forecast (INFO/WARNING) --------------------------------------------
    fc_bar_nominal = float(np.log(len(ctxs) / alpha["forecast"]))
    fc_bar = fc_bar_nominal - config.log_e_offset
    fc_report: dict[str, Any] = {
        "log_e_threshold": fc_bar,
        "log_e_threshold_nominal": fc_bar_nominal,
        "per_context": {},
    }
    best: tuple[str, ForecastReport] | None = None
    for c, s in zip(ctxs, sts):
        rep = apply_evidence_gate(s.forecast(now, None), fc_bar)
        fc_report["per_context"][c] = rep.to_dict()
        if (
            rep.valid
            and rep.crossing
            and not rep.crossing["already_beyond"]
            and rep.crossing["p_within_horizon"] >= config.forecast.forecast_probability
        ):
            if best is None or rep.log_e > best[1].log_e:
                best = (c, rep)
    fc_report["alarm"] = best is not None
    if best is not None:
        c, rep = best
        cr = rep.crossing
        horizon = cr["horizon_hours"]
        fmt = lambda h: "beyond horizon" if h is None else (f"{h * 60:.0f} min" if h < 2 else f"{h:.1f} h")
        level = (
            AlertLevel.WARNING
            if cr["median_hours"] is not None and cr["median_hours"] <= horizon / 4
            else AlertLevel.INFO
        )
        alert(
            level,
            "forecast",
            c,
            f"{label} [{c}] projected to cross {thr:g} in ~{fmt(cr['median_hours'])} "
            f"(80% predictive interval {fmt(cr['p10_hours'])} - {fmt(cr['p90_hours'])}; "
            f"P(cross within {horizon:.1f} h)={cr['p_within_horizon']:.2f}; trend e={np.exp(min(rep.log_e, 700)):.3g})",
            threshold=thr,
            hours_to_threshold_median=cr["median_hours"],
            hours_to_threshold_p10=cr["p10_hours"],
            hours_to_threshold_p90=cr["p90_hours"],
            probability_within_horizon=cr["p_within_horizon"],
            horizon_hours=horizon,
            slope_per_hour=rep.slope_per_hour,
            e_value=float(np.exp(min(rep.log_e, 700))),
            e_threshold=float(np.exp(fc_bar)),
            alpha_series=alpha["forecast"],
            guarantee=_g(live[c][1].guarantee["forecast"], config),
            evidence=kind,
            contexts=ctxs,
            includes_process_variation=True,
            process_sd=cr["process_sd"],
        )
    return GroupReport(
        metric, qubits, prov, ctxs, kind, n_batches, dict(alpha), drift_report, thr_report, fc_report, alerts
    )


def analyze_series(
    estimates: Sequence[Estimate],
    config: DriftConfig,
    now: datetime | None = None,
    baseline_since: datetime | None = None,
    alpha: dict[str, float] | None = None,
    states: dict | None = None,
) -> list[Alert]:
    """Convenience wrapper: analyse a single series as its own group with the
    whole budget (n_qubits = n_metrics = 1). Returns the alerts."""
    b = config.budget
    alpha = alpha or {ch: b.alpha_series(ch, 1, 1) for ch in CHANNELS}
    es = list(estimates)
    if not es:
        return []
    ctx = es[0].context
    rep = analyze_group({ctx: es}, config, now, baseline_since, alpha, {} if states is None else states)
    return rep.alerts if rep else []


__all__ = [
    "CHANNELS",
    "HIGHER_IS_WORSE",
    "DriftConfig",
    "ErrorBudget",
    "ForecastStatus",
    "GroupReport",
    "SeriesState",
    "analyze_group",
    "analyze_series",
    "series_kind",
]
