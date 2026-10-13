# Sequential methods in v0.2: what is computed and what is guaranteed

This note defines the monitoring statistics of `qnp.sequential`,
`qnp.drift` and `qnp.forecast` precisely enough to be checked, and states
for each one the null hypothesis under which its error guarantee holds.
The paper (`paper/`) gives the derivations; this is the operational
reference.

## 1. The problem v0.1 had

v0.1 re-tested every series after every batch with a fixed posterior bar
(P ≥ 0.95). Over a 48-batch session with 2 contexts × 2 qubits that is
about 190 dependent tests, and the run-level false-alert rates were 0.62
(E1 control) and 0.37 (E2). A per-check bar says nothing about the
probability of *ever* alerting during a session.

## 2. E-processes and Ville's inequality

A non-negative process $E_t$ adapted to the data with $\mathbb{E}_{H_0}[E_\tau] \le 1$
for every stopping time $\tau$ is an **e-process**. Ville's inequality gives

$$
\mathbb{P}_{H_0}\Big(\exists t:\ E_t \ge 1/\alpha\Big) \le \alpha ,
$$

for any session length, known or not. The monitor alerts when $E_t \ge 1/\alpha_{\text{series}}$.
Likelihood ratios against a fixed null are e-processes; products over
independent streams, convex mixtures (over alternatives, change times, or
prior scales), and averages across series preserve the property.

### 2.1 Change-time mixture

All change detectors use the same device. For a candidate change time $s$
the alternative says "null before $s$, changed from $s$ on". With a
geometric prior $\pi(s) = \rho(1-\rho)^{s-1}$, $\rho = 1/\texttt{change\_prior\_mean\_batches}$,

$$
E_t = \sum_{s \le t} \pi(s)\, L_t(s) \;+\; \sum_{s > t} \pi(s),
$$

where $L_t(s)$ is the likelihood-ratio process started at $s$ (equal to 1
before $s$). The second term is the prior mass of "no change yet", whose
ratio is 1. $E_t$ is a convex combination of e-processes, hence an
e-process. The price is explicit: a change at time $s$ must overcome
$1/(\alpha\,\pi(s))$, which grows slowly with $s$ (about 2.5 nats more at
$s = 48$ than at $s = 1$ with the default $\rho = 1/48$).

### 2.2 Binomial threshold (CRITICAL channel) — exact

Data: batches $(k_u, n_u)$, null $H_0$: $p_u \le \theta$ for all $u$. For
alternative rates $q_j = \theta(1+\varepsilon_j)$, $\varepsilon_j$ log-spaced
in $[0.02, 5]$,

$$
L_t(s) = \frac{1}{J}\sum_j \prod_{u=s}^{t} \frac{\mathrm{Bin}(k_u \mid n_u, q_j)}{\mathrm{Bin}(k_u \mid n_u, \theta)} .
$$

Each factor has expectation $\big[p\,q_j/\theta + (1-p)(1-q_j)/(1-\theta)\big]^{n_u} \le 1$
whenever $p \le \theta$ (it equals 1 at $p = \theta$ and is increasing in
$p$), so the product is a supermartingale under every sequence of rates on
the safe side. **Frequentist, exact, no plug-in.** Guarantee label: `exact`.

### 2.3 Binomial change (WARNING channel) — Bayesian marginal

Null $H_0$: all batches share one unknown rate $p$. The null predictive is
the Beta-binomial with the running Jeffreys posterior,
$p_0(k_t \mid \mathcal{F}_{t-1})$. For a change at $s$, the alternative
predictive is fixed at time $s-1$: draw $p$ from the null posterior at
$s-1$ (represented by 16 quantile nodes $p_j^{(s)}$) and a relative
increase $\delta_d$ from a log-spaced grid on $[\delta_{\min}, \delta_{\max}]$
(default $[0.10, 3]$, 10 nodes):

$$
L_t(s) = \frac{1}{DJ}\sum_{d,j} \prod_{u=s}^{t}
\frac{\mathrm{Bin}\big(k_u \mid n_u,\ p_j^{(s)}(1+\delta_d)\big)}{p_0(k_u \mid \mathcal{F}_{u-1})} .
$$

Because every alternative predictive is a proper distribution fixed before
the data it predicts, each term is a likelihood-ratio martingale under the
**Bayesian** null (rate drawn from the Jeffreys prior), and so is the
mixture. For a *fixed* unknown rate this is not a theorem; it is a
hypothesis tested in Experiment A (run-level false-alert probability at
fixed rates from 0.5% to 10%, with confidence intervals). Guarantee label:
`bayesian_marginal`. Monte Carlo in `tests/test_sequential.py` finds the
supremum exceeding 20 in ≤ 1% of null runs of 48 batches (nominal 5%).

### 2.4 Gaussian linear-model e-values — exact for Gaussian errors with unknown scale

Model $y_u = a + b\,x_u + \epsilon_u$, $\epsilon_u \sim \mathcal{N}(0, \sigma^2/w_u)$,
with known relative precisions $w_u$ and unknown $\sigma$. Flat priors on
$a$ and $\log\sigma$, Zellner g-prior $b \mid \sigma \sim \mathcal{N}(0, g\sigma^2/S_{xx})$.
With $\nu = n-1$ (one nuisance regressor) and the weighted $R^2$ of the
regression,

$$
\mathrm{BF}_{10}(g) = (1+g)^{(\nu-1)/2}\,\big(1 + g(1-R^2)\big)^{-\nu/2},
\qquad
E^{\pm} = 2\,\mathrm{BF}_{10}\,\mathbb{P}(\pm b > 0 \mid y),
$$

where the posterior sign probability is a Student-$t_\nu$ tail at
$\hat b\,\sqrt{S_{xx}\,g/(1+g)}\,/\sqrt{\mathrm{RSS}_g/\nu}$,
$\mathrm{RSS}_g = \mathrm{RSS}_0\,(1 - R^2 g/(1+g))$. The sequence of
these Bayes factors over growing $n$ is a test martingale under $b = 0$
for every $(a, \sigma)$ (Lindon & Malek 2022); the one-sided version has
expectation ≤ 1 under $\pm b \le 0$. Verified against brute-force
integration to 5 digits in `tests/test_sequential.py`.

A single $g$ caps the attainable factor at $(1+g)^{(\nu-1)/2}$, so the
detectors mix $g \in \{1, 10, 100\}$ with equal weights (a mixture of
e-values is an e-value).

Uses: **trend** ($x$ = time; forecast channel), **level shift** ($x = 1\{u \ge s\}$,
mixed over $s$ as in §2.1; drift channel for interval and point series),
**curvature** (quadratic term after partialling out the linear trend;
lack-of-fit diagnostic). For binomial rates the Gaussian model is an
approximation (label `gaussian_approx`); for series with reported
intervals it is exact if the intervals are right (label `exact`); for
vendor values without uncertainty the scale is estimated (label `exact`
for the shift test, `plug_in` for the threshold test, which needs a scale).

### 2.5 Gaussian threshold — exact with known scale

$H_0$: $\mu_u$ on the safe side of $\theta$ for all $u$; alternatives
$\theta \pm \varepsilon_j$; per-observation likelihood ratios with the
reported $\sigma_u$; change-time mixture as in §2.1. Exact by the monotone
likelihood ratio of the Gaussian location family. With a plug-in scale
(vendor values) it is labelled `plug_in`.

## 3. The monitoring family and its budget

The session budget $\alpha_{\text{session}}$ (default 0.10) is split:

| Dimension | Rule |
|---|---|
| channel (drift / threshold / forecast) | fixed shares 0.5 / 0.25 / 0.25; a zero share disables that channel (infinite threshold) |
| qubits × metrics × provenances | union bound: $\alpha_{\text{series}} = \alpha_{\text{session}}\,\text{share}/(n_q n_m n_p)$; $n_p$ is the largest number of provenances (observed / inferred / measured) monitored for one (qubit, metric), since each provenance is a separate test |
| contexts of one (qubit, metric) | **average** of context e-values (an e-value), no further split |
| contexts, shared change | ½ average + ½ shared-$(s,\delta)$ product across synchronous contexts |
| time | free: the e-process is anytime-valid |
| forecast horizons | one trend test per series; the horizon only enters the predictive statement |

The family size $(n_q, n_m, n_p)$ is declared in `ErrorBudget` or frozen at
the first `check()`. Every recorded experiment monitored one provenance
($n_p = 1$). If it later grows, `Profiler.family["exceeded"]` is set and
the budget statement is void (the thresholds were computed for a smaller
family).

Under the union bound, if every series' null holds, P(any alert in the
session) ≤ $\alpha_{\text{session}}$ *provided each channel's guarantee holds
under its stated null* (§2). The binomial change channel's guarantee is
Bayesian, so the overall statement for fixed rates is an empirical claim
(Experiment A), not a theorem.

### 3.1 Which series carry an absolute threshold (v0.3)

An absolute recalibration threshold is a statement about the hardware, so it
is applied only to series whose value does not depend on the workload:

| Series | Absolute threshold (default) | Crossing forecast | Drift (relative change) |
|---|---|---|---|
| MEASURED `readout_error` from readout probes (prepare \|b⟩, measure; contexts `p(1\|0)`, `p(0\|1)`) | 5% | yes | yes |
| OBSERVED `readout_error` (vendor values) | 5% (plug-in scale) | yes | yes |
| INFERRED `effective_flip_rate` (workload circuits) | **none** | none | yes |
| T1, T2 (any provenance) | none unless configured | if a threshold is set | yes |

v0.2 applied the 5% threshold to effective flip rates too. Their value
depends on the circuit context (gate composition, idle time), so a workload
change on unchanged hardware crossed it (v0.2 Experiment E5: every run;
E6: 44%). `DriftConfig(thresholds=dict(V02_THRESHOLDS))` reproduces v0.2.
Readout probes add a metric per qubit, so the family is declared with
`n_metrics = 2` when both are monitored (each per-series α halves). Their
counts are binomial, so their threshold channel keeps the exact guarantee of
§2.2. The probes are recognised by their structure: only X gates and
terminal measurements, at most one X per qubit, and no qubit held waiting
for another qubit's measurement (a waiting |1⟩ decays, so its error would
depend on the circuit). Experiment G of the v0.3 study tested
the change in simulation: false alerts after the E5 and E6 workload changes
fell to 2% and 5%, none from the threshold channel (`results/V03_SUMMARY.md`
§2).

## 4. Meaningful deterioration

A drift alert requires all three gates:

1. **evidence**: group e-value ≥ $1/\alpha_{\text{drift}}$;
2. **effect**: posterior $\mathbb{P}(\text{relative change} \ge \delta_{\min}) \ge 0.5$,
   computed from the counts before and after the most probable change
   point (Beta posteriors; for Gaussian series the Student-$t$ posterior of
   the shift);
3. **persistence**: at least `persistence_batches` (default 2) since the
   most probable change point, so one aberrant batch cannot alert.

Gates 2–3 only remove alerts, so they cannot raise the false-alert rate.

## 5. Forecasts

Statuses and the order in which they are decided:

| Status | Condition |
|---|---|
| `INSUFFICIENT_HISTORY` | fewer than `min_points` (6) points or span < `min_span_hours` (1 h) |
| `INSUFFICIENT_EVIDENCE` | trend e-value < $n_{\text{ctx}}/\alpha_{\text{forecast}}$ |
| `MODEL_MISSPECIFICATION` | runs test on residual signs p < 0.01, or curvature e-value ≥ 20 |
| `UNSTABLE_TREND` | first- and second-half slopes differ by > 3 standard errors |
| `UNSUPPORTED_HORIZON` | median crossing time beyond `max_extrapolation_factor` × data span |
| `VALID_FORECAST` | otherwise; also when the level is already beyond the threshold (reason `ALREADY_BEYOND_THRESHOLD`, no forecast alert: the threshold channel owns it) |

Every rejection lists `Reason(code, message, value, limit)` entries.

**Predictive crossing time.** With a near-flat prior ($g = 10^6$), draw
$\sigma^2 \sim \mathrm{InvGamma}(\nu/2, \mathrm{RSS}_g/2)$,
$b \mid \sigma^2 \sim \mathcal{N}(\hat b, \sigma^2/S_{xx})$,
$a \mid \sigma^2 \sim \mathcal{N}(\bar y_w, \sigma^2/\sum w)$, and a
future process deviation $\eta \sim \mathcal{N}(0, (\sigma^2 - 1)_+/\bar w)$:
the excess of the fitted error scale over the reported measurement
precision is read as variation of the underlying level. The crossing time
is $t^\ast = (\theta - a - \eta)/b$ for draws heading toward the threshold
(else $+\infty$). Reported: median, 10th and 90th percentiles (an 80%
predictive interval) and $\mathbb{P}(t^\ast \le H)$ with
$H = \min(\text{horizon}, \text{cap})$. A forecast alert needs
$\mathbb{P}(t^\ast \le H) \ge 0.5$; it is WARNING if the median is within
$H/4$, INFO otherwise.

## 6. Decay fits under measurement drift (v0.3)

The model checks of a T1/T2 fit (delay coverage, deviance, posterior
predictive, residual runs) look at residuals along the delay axis. When
delays are acquired in delay order, a slow drift of the measurement during
the sweep is a smooth function of delay and is absorbed into A, B and T1
(v0.2 D11: 28.5% confidently wrong). `qnp.measured.decay_sweep_plan` (the
default since v0.3) acquires the delays in random order and spreads 5 ground
references (prepare \|0⟩, measure) over the acquisition. A likelihood-ratio
(G) test of the references' homogeneity, α = 0.01, reports `READOUT_DRIFT`
and the fit is labelled `MODEL_MISSPECIFICATION`; the runs test of the
residuals in acquisition order is reported but is not a rejection rule. The
references never enter the fit, so the estimate on drift-free data is the
v0.2 estimate. Experiment H of the v0.3 study tested the design in
simulation: under the D11 drift, confidently wrong fits fell from 25.5%
(sequential) to 0.5%, at the cost of 2.5–4% of valid fits rejected
(`results/V03_SUMMARY.md` §3).

## 7. What is still not guaranteed

- The binomial change channel at a fixed rate (§2.3): empirical.
- Gaussian approximation for trend tests on rates with small counts.
- Plug-in scales for vendor values with no reported uncertainty.
- Family growth after the first check.
- Everything above assumes batches are conditionally independent given the
  rates; time-correlated noise within a batch is not modelled (Experiment D
  probes it for the decay fits; Experiment E for workload shifts).

## References

- Ville, J. (1939). *Étude critique de la notion de collectif.*
- Ramdas, A., Grünwald, P., Vovk, V., Shafer, G. (2023). Game-theoretic
  statistics and safe anytime-valid inference. *Statistical Science* 38(4).
- Lindon, M., Malek, A. (2022). Anytime-valid inference for multinomial
  count data / Anytime-valid linear models and regression adjusted causal
  inference in randomized experiments. arXiv:2210.08589.
- Liang, F., Paulo, R., Molina, G., Clyde, M., Berger, J. (2008). Mixtures
  of g priors for Bayesian variable selection. *JASA* 103(481), eq. 5.
- Shin, J., Ramdas, A., Shekhar, S. (2022). E-detectors: a nonparametric
  framework for sequential change detection. arXiv:2203.03532.
- Howard, S., Ramdas, A., McAuliffe, J., Sekhon, J. (2021). Time-uniform,
  nonparametric, nonasymptotic confidence sequences. *Ann. Statist.* 49(2).
