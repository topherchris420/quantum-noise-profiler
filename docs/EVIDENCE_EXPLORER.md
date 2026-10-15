# Inspect the evidence locally

The evidence explorer is a self-contained HTML report of the completed physical
Experiment P and the latest eligible G/H/I simulation entries in a results log.
It uses the existing research record. It is not a live monitor or a hardware
control panel.

## Start

From the repository root:

```bash
python -m pip install -e .
python -m qnp report
```

Open `qnp-evidence.html` directly in a browser. The installed `qnp report`
command is equivalent. The checked-in [HTML snapshot](evidence-explorer.html)
can be downloaded and opened without installing Python. GitHub displays its
source rather than running it.

The core install uses NumPy and SciPy. Qiskit, Cirq, IBM credentials, a web
server, and internet access are unnecessary for report generation or viewing.
Documentation links open GitHub only when followed. The report makes no
background requests and has no external fonts, libraries or analytics.

```bash
qnp report --results-dir /path/to/results --output report.html
qnp report --run-id V03_P_pilot-20261013T234830-220ff3 --output pilot.html
qnp demo
```

`demo` prints a deterministic synthetic session as strict JSON. Its counts are
invented solely to illustrate the API and are labeled as a demonstration;
they are not research evidence. It does not write a run record.

## Read the interface

1. Select a physical qubit. The initial selection has the largest recorded
   G/df, a descriptive choice made after the experiment.
2. Inspect both readout directions or select one. Rates are errors divided by
   shots, connected by straight segments. No smoothing or inferred physical
   trajectory is added.
3. Keep **Same scale across qubits** selected for direct comparisons. Turning
   it off rescales the selected traces and can visually exaggerate variation.
4. Move the batch slider with the mouse, touch, or keyboard arrow keys to read
   exact counts and the recorded UTC time. The full trace remains visible;
   this is retrospective inspection, not a prospective detector replay.
5. Optionally show vendor snapshots. They are historical references, not
   independent ground truth. Alerts are recorded per qubit, not assigned to
   one readout direction by this report.
6. Inspect all probe-series assumption checks and all T1 fit decisions.
   “Not rejected” does not establish stability. Withheld estimates are blank,
   never substituted with zero. T1 credible intervals are conditional on the
   assumed fit model and checks.
7. Expand the simulation cards to inspect individual registered criteria.
   Those pass counts do not validate hardware performance.

Every plotted value is also available in an expandable, accessible table.
The report supports narrow screens, reduced-motion preferences, keyboard
navigation and printing.

## Exports and verification scope

**CSV:** selected qubit and visible readout direction(s), across all recorded
batches. Columns are `qubit`, `context`, `batch`, `timestamp_utc`,
`elapsed_minutes`, `errors`, `shots`, and `rate` (a fraction, not percent).

**JSON:** all explorer data, original decisions, timestamps and timestamp
sources, source commit, SHA-256 receipts, and an explicit verification-scope
object. It excludes job IDs, account credentials and full backend snapshots.

| Exporter check | Scope |
|---|---|
| Existing manifest | Every displayed run-entry line and its raw file must match its recorded SHA-256 |
| Hardware selection | A completed physical pilot only; smoke, fake and rehearsal records are excluded |
| Probe acquisition | Expected batch order, physical-qubit mapping, counts and shot totals |
| Probe statistics | Rates and original homogeneity G-statistic/p-value recomputed from bit counts |
| Other outcomes | Recorded T1 fits, alerts and simulation criteria; not recomputed by this exporter |

The full research verifier remains:

```bash
python tools/verify_results.py
python tools/check_provenance.py
```

Checksums detect changes relative to the supplied manifest. They do not
independently authenticate an author, establish scientific validity, or turn
re-analysis of the same pilot into independent confirmation. The report is a
snapshot checked when generated; it does not continuously revalidate source
files or authenticate an HTML file after it is shared.

The exporter preserves the append-only record: it never writes inside
`results/`. Existing reports require `--force` to replace. Writes are atomic,
and verification failure leaves the previous output untouched. Generated
reports and CSV/JSON exports may be shared after checking the disclosure terms
of the underlying data.

## Session API

For a monitor you construct yourself, `Profiler.session_report()` includes the
monitoring family, notices, budget status, reports and latest estimates in a
strict-JSON object. It replaces non-finite diagnostics with `null`; a zero
channel alpha identifies disabled channels. Existing `report()` and
`reports()` preserve their original numerical diagnostics, including infinity.

`within_declared_family` only means that the observed family has not exceeded
its allocated dimensions. It does not verify statistical assumptions. If the
family grows past its declaration, all channel/alert guarantees are marked
`unavailable:family_exceeded`, the original label is kept in
`nominal_guarantee`, and text alerts explain that they are descriptive only.

Inspecting an empty store, or one containing only withheld estimates, does not
freeze an implicitly declared family. Declare the full family before monitoring
when it is known in advance.

## Troubleshooting

| Message | Action |
|---|---|
| Missing `runs.jsonl` or manifest | Run from the cloned repository root, or supply `--results-dir` |
| No completed physical-QPU pilot | Supply a complete authorized pilot record; a simulator rehearsal is deliberately ineligible |
| SHA-256 mismatch / missing hash | Inspect the original evidence and run the existing verifier; do not reseal changed evidence merely to make the report pass |
| Probe counts disagree with summary | Resolve the inconsistency in a documented research correction before generating a report |
| Output already exists | Choose another filename or use `--force` for an intentional replacement |

The checked-in preview is regenerated with:

```bash
python -m qnp report --output docs/evidence-explorer.html --force
```

The explorer's original findings are unchanged: P.C1 failed, P.C2 passed, and
the true/false status of the five recorded warnings remains unknown. The next
study is documented in [P04_FOLLOWUP_PLAN.md](../experiments/P04_FOLLOWUP_PLAN.md).
