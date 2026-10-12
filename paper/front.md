# Trustworthy warnings from continuous qubit-noise monitoring: anytime-valid alerts, abstaining forecasts and model-checked relaxation fits

*Quantum Noise Profiler v0.2 — research report. Simulation study; no hardware results.*

## Abstract

ABSTRACT_PLACEHOLDER

## 1. Introduction

Quantum processors are calibrated on a schedule, but their error rates and
coherence times change in between. Two-level-system defects move T1 on
minute-to-hour scales, readout fidelity drifts with amplifier and
temperature changes, and gate errors follow calibration staleness. A monitor
that watches these quantities and warns before they cross a recalibration
threshold could save failed jobs and calibration time, but only if its
warnings are reliable. A monitor that re-tests after every batch with a
fixed posterior or p-value bar alarms falsely in almost every long enough
session. A forecast extrapolated from a short or misfitted history can be
precise and wrong.

The first version of this project (v0.1) made these failure modes concrete.
In three preregistered simulation experiments it detected gradual and
abrupt degradation early, but 62% of stable sessions near threshold raised
an alert, and its T1 estimator reported confident, wrong values in 72% of
fluctuating-T1 cases and never abstained on a two-component decay. An audit
also found that its comparison against a Shewhart chart had used different
evaluation rules for the two methods.

This report describes v0.2 and tests, in a new preregistered study, whether
it fixes these problems. The contributions are:

1. a monitoring engine whose alerts come from anytime-valid e-processes
   under an explicit session error budget, with each alert labelled by the
   kind of guarantee behind it (exact, Bayesian-marginal, approximate or
   empirically calibrated);
2. forecasts that abstain with machine-readable reasons and report
   predictive intervals for the threshold-crossing time;
3. relaxation fits that refuse to report a value when the data contradict a
   single exponential or do not resolve the decay, and that say which;
4. a matched-rules re-analysis of the v0.1 benchmark; and
5. an evidence trail in which every reported number can be recomputed from
   raw data and every run is tied to the exact source it ran.

The standard applied throughout is not that the method produces more
confident answers, but that its confidence is more often deserved.

## 1.1 Related work

Sequential tests with error control at arbitrary stopping times go back to
Wald's SPRT and Ville's inequality; their modern form is the theory of
e-values, test martingales and confidence sequences (Ramdas et al. 2023;
Howard et al. 2021). Change detection with e-processes ("e-detectors") is
developed by Shin, Ramdas and Shekhar (2022). Anytime-valid inference for
linear models with unknown variance follows from Bayes factors under
right-Haar priors (Lindon and Malek 2022; Liang et al. 2008 for the
g-prior closed form). Classical statistical process control (Shewhart charts,
Page's CUSUM) controls the average run length rather than the probability
of any false alarm in a session, and its limits are usually calibrated by
simulation, which is how they are used as comparators here. For qubit
characterization, Qiskit Experiments fits T1/T2 by least squares with
heuristic quality flags; drift of superconducting-qubit parameters and TLS
fluctuations are documented in the experimental literature (e.g. Klimov et
al. 2018; Burnett et al. 2019).
