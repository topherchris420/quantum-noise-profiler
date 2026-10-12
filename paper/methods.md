<!-- Methods part of paper/paper.md; assembled by hand. Math uses GitHub's $...$ / $$...$$ rendering. -->

## 2. Data model and identifiability

Every number the profiler emits is an *estimate* with a provenance:
**observed** (vendor calibration data), **inferred** (from ordinary workload
results) or **measured** (dedicated characterization sequences). Series are
keyed by (metric, qubits, context, provenance) and never pooled across
provenances.

From workload counts, the identifiable per-qubit quantity is the
*effective flip rate* of a qubit whose noiseless outcome is a definite bit
$b$:

$$
p_{q,c} \;=\; \Pr\big(\text{observed bit} \neq b \;\big|\; \text{qubit } q,\ \text{context } c\big),
$$

where the context $c$ summarises the qubit's noiseless path (ideal bit,
gate counts and, in *exact* mode, per-gate-name counts and idle time). It
lumps preparation, gate, decoherence and readout error and is comparable
only within one context. A batch contributes $(k, n)$ flips and shots; the
posterior under a Jeffreys prior is $\mathrm{Beta}(k + \tfrac12,\ n - k + \tfrac12)$.

T1 and T2 are not identifiable from workload counts. They are estimated from
relaxation and Hahn-echo sweeps with the model

$$
P_1(t) = A\,e^{-t/T_1} + B, \qquad k_j \sim \mathrm{Bin}\big(n_j, P_1(t_j)\big),
$$

on a grid posterior with log-uniform prior on $T_1$ and uniform priors on
the SPAM parameters $A, B$, which are marginalised.

## 3. Sequential monitoring with e-processes

A non-negative process $(E_t)$ is an **e-process** for a null $H_0$ if
$\mathbb{E}_{H_0}[E_\tau] \le 1$ for every stopping time $\tau$. By Ville's
inequality,

$$
\Pr_{H_0}\!\left(\sup_{t \ge 1} E_t \ge \tfrac{1}{\alpha}\right) \le \alpha ,
$$

for any monitoring length. This is the property a monitor re-tested after
every batch needs, and which a fixed posterior bar $\Pr(\theta \in \text{bad} \mid \text{data}) \ge 0.95$
does not have: under repeated testing, such a bar is crossed eventually with
probability approaching one.

**Change-time mixture.** For a change starting at batch $s$ the
likelihood-ratio process is $L_t(s)$ ($=1$ for $t < s$). With a geometric
prior $\pi(s) = \rho(1-\rho)^{s-1}$,

$$
E_t \;=\; \sum_{s \le t} \pi(s)\, L_t(s) \;+\; \sum_{s>t} \pi(s)
$$

is a convex combination of e-processes and hence an e-process.

**Threshold channel (exact).** For $H_0: p_u \le \theta$ for all $u$ and
alternatives $q_j = \theta(1+\varepsilon_j)$,
$L_t(s) = J^{-1}\sum_j \prod_{u=s}^{t} \mathrm{Bin}(k_u; n_u, q_j)/\mathrm{Bin}(k_u; n_u, \theta)$.
Each factor has expectation $\big[p\,q_j/\theta + (1-p)(1-q_j)/(1-\theta)\big]^{n_u} \le 1$
for $p \le \theta$, so the guarantee is frequentist and exact.

**Drift channel (Bayesian-marginal).** For $H_0$: one common unknown rate,
the null predictive is the Beta-binomial under the running Jeffreys
posterior; the alternative for a change at $s$ multiplies a rate drawn from
the null posterior *frozen at* $s-1$ by $(1+\delta)$, $\delta$ on a grid in
$[0.1, 3]$. Each term is a likelihood-ratio martingale under the Bayesian
null (rate drawn from the prior). For a fixed rate this is not a theorem;
Experiment A measures it.

**Gaussian channels.** For $y_u = a + b\,x_u + \epsilon_u$,
$\epsilon_u \sim \mathcal N(0, \sigma^2/w_u)$ with unknown $\sigma$, flat
priors on $a$ and $\log\sigma$ and a $g$-prior on $b$, the Bayes factor

$$
\mathrm{BF}_{10}(g) = (1+g)^{(\nu-1)/2}\big(1+g(1-R^2)\big)^{-\nu/2}, \qquad \nu = n-1,
$$

is a test martingale under $b = 0$ for every $(a, \sigma)$; one-sided
versions multiply by $2\Pr(\pm b>0 \mid y)$. The detectors mix
$g \in \{1, 10, 100\}$. They serve trend (forecast evidence), level-shift
(interval and point series) and curvature (lack of fit) tests.

**Family-wise budget.** The session budget $\alpha_{\text{session}} = 0.10$
is split across channels (drift 0.5, threshold 0.25, forecast 0.25) and by a
union bound across the declared qubits and metrics:
$\alpha_{\text{series}} = \alpha_{\text{session}}\cdot\text{share}/(n_q n_m)$.
Contexts of one qubit and metric are combined by averaging e-values (an
e-value), plus a shared-change product term; time costs nothing extra.

**Meaningful deterioration.** A drift alert additionally requires
$\Pr(\text{relative change} \ge 10\% \mid \text{data}) \ge 0.5$ at the most
probable change point and at least two batches since it. These gates only
remove alerts.

**Empirical calibration.** The anytime-valid thresholds are conservative.
The *calibrated* configuration divides every threshold by $e^{c}$, with $c$
chosen on separate calibration seeds so that the maximal run-level
false-alert rate over four stable conditions is at most 0.08. It trades the
theorem for an empirical guarantee, and every alert it raises is labelled
`+calibrated`.

## 4. Forecasts and abstention

A forecast is offered only if the history has at least 6 points over at
least 1 h (else `INSUFFICIENT_HISTORY`), the one-sided trend e-value exceeds
$n_{\text{ctx}}/\alpha_{\text{forecast}}$ (else `INSUFFICIENT_EVIDENCE`), the
residuals show no structure (runs test $p \ge 0.01$) and no curvature
(quadratic-term e-value $< 20$) (else `MODEL_MISSPECIFICATION`), the slopes of
the two halves of the history agree within 3 standard errors (else
`UNSTABLE_TREND`), and the median crossing time lies within the observed span
(else `UNSUPPORTED_HORIZON`). Each rejection carries machine-readable reason
codes.

The crossing-time distribution is predictive. Draw
$\sigma^2 \sim \mathrm{InvGamma}(\nu/2, \mathrm{RSS}/2)$,
$b \mid \sigma^2 \sim \mathcal N(\hat b, \sigma^2/S_{xx})$,
$a \mid \sigma^2 \sim \mathcal N(\bar y_w, \sigma^2/\textstyle\sum w)$ and a
future process deviation $\eta \sim \mathcal N\big(0, (\sigma^2-1)_+/\bar w\big)$,
the excess of the fitted scale over the reported measurement precision.
Then $t^\ast = (\theta - a - \eta)/b$ for draws heading toward the threshold.
The report gives the 10th, 50th and 90th percentiles and
$\Pr(t^\ast \le H)$.

## 5. Model checking of relaxation fits

A fit returns a value only if every check passes:

- **Coverage of the delay range.** The delays must span at least 30% of the
  decay ($e^{-t_{\min}/\hat T_1} - e^{-t_{\max}/\hat T_1} \ge 0.3$) with at
  least three delays in $[0.1, 3]\,\hat T_1$, and the posterior must not pile
  up at the prior edge. Otherwise the status is `INSUFFICIENT_EVIDENCE`.
- **Goodness of fit.** The binomial deviance
  $D = 2\sum_j \big[k_j\log\frac{k_j}{n_j\hat p_j} + (n_j-k_j)\log\frac{n_j-k_j}{n_j(1-\hat p_j)}\big]$
  is tested against $\chi^2_{J-3}$; a posterior-predictive check compares the
  observed deviance with replicated data; a runs test examines the signs of the
  Pearson residuals along the sweep. Each test uses $\alpha = 0.01$. Failure
  gives `MODEL_MISSPECIFICATION`.
- **Diagnosis.** The marginal likelihood of a bi-exponential model is
  reported as a Bayes factor against the single exponential. It is never
  substituted for the single-exponential estimate.

## 6. Experimental design

The v0.2 study was preregistered (`experiments/V02_PREREGISTRATION.md`)
before any calibration or confirmatory run. It used disjoint seed blocks for
development, calibration and confirmation, compared every method on
identical simulated data, and recorded every run, including failures, in an
append-only log with hashes, raw data and provenance. Two clarifications
were recorded before the affected data were generated
(`results/V02_DEVIATIONS.md`).
