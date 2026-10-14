# P04 planned follow-up | fluctuating readout and robust monitoring

**Protocol status: proposed and unexecuted (2026-10-13).** Written after inspection of Experiment P, so this is **not** a preregistration of the original IBM Fez data or a confirmatory result. Freeze a final protocol commit, data exclusions, allocation, and an explicit QPU spending authorization *before* any new confirmatory acquisition. Do not re-label the 2026-10-13/14 pilot as independent testing.

## Scientific question

When readout rates fluctuate between jobs, can a fluctuation-aware monitor preserve useful detection while reducing false warnings, compared with the current v0.3 model and calibrated CUSUM, on independent real-device data?

### Hypotheses to test, not established results

- **H1 (null-model adequacy):** the constant-rate binomial null used by the v0.3 drift channel will exhibit excess rejection on held-out devices/sessions; a prespecified fluctuating-rate model will predict probe variation more accurately without concealing genuine degradation.
- **H2 (actionable monitoring):** when compared at matched **session-level** false-alert rates, a fluctuation-aware detector can avoid nuisance alerts without materially increasing detection delay relative to calibrated CUSUM.
- **H3 (operational feasibility):** for an intervention cloud users can actually make (qubit selection/remapping, not invoking recalibration), monitoring has a measurable net benefit after counting probe shots, QPU usage, and unsuccessful jobs.

## Design and safeguards

- **Data:** at least two physical backends if account access permits; repeated observation sessions spanning multiple calibration cycles and days. Include independent fresh held-out sessions after any model-fitting/calibration phase. Vendor-property snapshots are contextual, not ground-truth labels.
- **Fixed probes:** prepare |0⟩ and |1⟩ readout circuits, exact physical layout, fixed context and shots. Record execution timestamps, calibration times, queue gaps, missing jobs, and qubit selection rules. Do not silently substitute workloads or change the time grid.
- **Independent labels:** use separately authorized, blinded characterization or controlled/synthetic injections when available. Without independent labels, report **model adequacy and descriptive variation only**, not sensitivity, precision or hardware-detection accuracy.
- **Comparators:** frozen v0.3 anytime-valid, frozen v0.3 empirical-calibrated, calibrated CUSUM, a batch-overdispersed beta-binomial model, and a temporally correlated latent-rate alternative. Fix alarm-family budgeting, meaningful-effect definition, and persistence rules before test.
- **Training/validation/test separation:** the original `ibm_fez` pilot is development data only. Use different later sessions for calibration and independent evaluation. Preserve disjoint data partitions by physical session and device; do not randomly split batches from the same two-hour run.
- **Statistical guarantees:** do *not* label a new beta-binomial or correlated-rate heuristic as anytime-valid unless its proposed e-process is proven to be a supermartingale under the actual composite null and assumptions. Otherwise report empirical session-level error with binomial/Wilson uncertainty and sensitivity across devices, horizons and fluctuations.
- **Outcome measures:** session-level false alerts; time-to-detection at matched false-alert rate; missed degradation events; forecast interval coverage (where truth exists); abstention; model predictive checks; shots, calibration actions actually available, wall clock and QPU usage. Include established baselines even when they win.
- **Analysis:** preregister the exact count model, the statistical decision rules, confidence interval construction and multiplicity handling, stopping rules, primary endpoint, minimum clinically/operationally relevant effect size, sample-size rationale, and missing-data procedures. Treat exploratory parameter sweeps as development only.
- **Safety:** use only an account with explicit permission; dry-run and inspect expected charges/quota; budget jobs/shots/QPU seconds up front; avoid automatic retries/submissions, autonomous remapping, or device recalibration. Independent authorized researchers must approve any active characterization.
- **Evidence:** per-job checkpoint, immutable raw artifacts with SHA-256 hashes, full provenance/timestamps, negative outcomes and a public summary free of account credentials or restricted provider data.

## Proposed milestones (not promises)

1. **Read-only feasibility:** obtain written data permission and characterize timestamp completeness and calibration-history retention. No active jobs.
2. **Design lock:** finalize budget, backend count, power/sensitivity analysis, comparator implementations and acceptance thresholds; record protocol SHA prior to acquisition.
3. **Authorized characterization:** run only approved fixed probes and independent references, using private per-job checkpoints. A failed/incomplete session stays excluded.
4. **Held-out analysis:** verify null adequacy first, then compare the monitoring policies without using the test sessions for tuning. Publish all outcomes.
5. **Decision:** advance only if a declared improvement survives across independent sessions/devices; otherwise explicitly report limitations and retain CUSUM as a strong baseline.

## Exploratory starting point

`python tools/pilot_diagnostics.py` describes Experiment P's existing readout traces. It does **not** establish a new detector or use independent data. The unchanged pilot counts and original pass/fail outcome remain in `results/V03_SUMMARY.md`.
