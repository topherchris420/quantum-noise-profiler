# Reproducing the results

Everything in `results/` can be checked without re-running a simulation, and
re-run from scratch with the commands below.

## 1. Environment

Recorded runs used Linux x86-64, Python 3.13.16, numpy 2.5.4, scipy 1.18.1,
qiskit 2.5.2, qiskit-aer 0.17.2, cirq-core 1.7.0 (v0.2 study) and Windows 11
ARM64, Python 3.11.9, numpy 2.4.6, scipy 1.17.1 (v0.1 and the 2026-10-13/14 real-device Experiment P studies). Each run entry
in `results/runs.jsonl` records its own environment, git commit and a hash
of `src/` and `experiments/` at launch and at completion.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

## 2. Check the recorded evidence (seconds; no simulation)

For a visual inspection with core dependencies only, run
`python -m qnp report` and open `qnp-evidence.html`. The exporter checks its
source hashes and recomputes probe rates/homogeneity from counts. It displays
the other summaries as recorded; the commands below perform the full check.
See the [evidence explorer guide](EVIDENCE_EXPLORER.md).

```bash
python tools/verify_results.py      # SHA-256 manifest + recompute every summary from raw data
python tools/check_provenance.py    # schema, clean source tree, seed ranges, calibration order
```

`verify_results.py` recomputes every value in every run's `summary` from its
raw file (`results/raw/`) and the run's `config`, using
`experiments/v02/analysis.py` (v0.2) and independent code in the tool itself
(v0.1). It fails on any mismatch or any changed artifact.

## 3. Re-run the studies

| Command | What | Approx. cost (4 cores) |
|---|---|---|
| `python experiments/exp1_gradual_drift.py` | v0.1 E1 (frozen v0.1 engine) | 15 min |
| `python experiments/exp2_sudden_degradation.py` | v0.1 E2 | 30 min |
| `python experiments/exp3_insufficient_evidence.py 200` | v0.1 E3 | 30 min |
| `python experiments/exp2_matched_comparison.py` | E2 correction (re-analysis only) | < 1 min |
| `python experiments/run_v02.py calibrate` | v0.2 calibration (seeds 20 000+) | 30–45 min |
| `python experiments/run_v02.py A` | sequential false-alarm control | ~60–90 min |
| `python experiments/run_v02.py B` / `C` | gradual / abrupt degradation | ~15 / ~30 min |
| `python experiments/run_v02.py D` | T1 misspecification | ~10 min |
| `python experiments/run_v02.py E` / `F` | workload shift / Qiskit-vs-Cirq | ~25 / ~10 min |
| `python tools/make_figures.py` | figures in `paper/figures/` | 1 min |
| `python experiments/run_v03.py H` | v0.3 T1 sweeps under drift (7 300 fits) | ~20 min |
| `python experiments/run_v03.py G` | v0.3 workload changes with readout probes | ~90 min |
| `python experiments/run_v03.py I` | v0.3 operational value (closed loop) | ~100 min |
| `python experiments/run_v03.py pilot` | v0.3 hardware pilot: dry run (add `--submit` only with explicit IBM Quantum authorization) | seconds / ~2 h |
| `python tools/pilot_diagnostics.py` | Read-only exploratory pilot variability/lag statistics, **not** independent confirmation | seconds |
| `python tools/make_v03_tables.py`, `python tools/make_v03_figures.py` | `results/V03_TABLES.md`, figures 8–10 | 1 min |

Runs append; they never overwrite. A re-run with the same seeds reproduces
the per-batch logs bit-for-bit on the same machine
(`tests/test_reproducibility.py`). Bit-identity across machines with
different core counts is not established (Aer parallelises with OpenMP;
see `docs/INVESTIGATION_V02.md` §4).

## 4. Local, private checkpoint journal for Experiment P

A real or fake pilot with `--submit` creates a unique directory under
`~/.qnp/pilot-checkpoints/` by default. Use `--checkpoint-dir PATH` to
choose another root. The runner fsyncs and atomically renames one JSON
event per milestone: start snapshot, **job submitted (including IBM job ID
before waiting)**, **job completed (counts and timestamps)**, final snapshot,
and recorded research run ID. A crash leaves all previously written events.
The original run is not silently resumed, and partial jobs are **never
stitched** into an official two-hour pilot. There is no automated provider
resubmission or hidden QPU spending.

These files may include device metadata and raw measurement counts. They
remain **local and untracked**, outside `results/` by default; check the
provider's disclosure conditions and remove secrets or nonpublic metadata
before sharing. Do not publish incomplete event journals as confirmatory
evidence. The original `results/runs.jsonl` and SHA-256 manifest are unchanged.

An interrupted session should be documented in `results/V03_DEVIATIONS.md`
with the submitted IBM job IDs and cost, even if a complete confirmatory
record was not produced. To obtain results for interrupted jobs, retrieve
them with the authorized account through IBM's job history; do not
automatically resubmit them.

## 5. CI smoke tests (not evidence)

```bash
export QNP_RESULTS_DIR=$(mktemp -d)
python experiments/run_v02.py calibrate --smoke && python experiments/run_v02.py C --smoke
python tools/verify_results.py --results-dir "$QNP_RESULTS_DIR" --update
```

`--smoke` refuses to write into `results/`. Smoke runs use 3 runs per
condition (v0.3: 2, and half-day runs for I) and their pass/fail flags mean
nothing. The same holds for a pilot rehearsal on a fake backend
(`run_v03.py pilot --fake FakeManilaV2 --submit --interval 0`).

## 6. Seeds

| Block | Range | Used for |
|---|---|---|
| development | < 20 000 | tests, design (`experiments/v02/DEVELOPMENT_NOTES.md`, `experiments/v03/DEVELOPMENT_NOTES.md`) |
| calibration | 20 000 – 21 999 | thresholds of the calibrated methods (reused by v0.3) |
| confirmatory | 30 000 – 39 999, 40 000 – 54 999 | v0.2 Experiments A–F |
| confirmatory | 60 000 – 69 999, 70 000 – 84 999 | v0.3 Experiments G, I and H |
| pilot | 90 000 – 90 001 | acquisition order of the v0.3 pilot's T1 sweeps |

`tools/check_provenance.py` fails if a recorded v0.2 or v0.3 run used a
seed outside its block.
