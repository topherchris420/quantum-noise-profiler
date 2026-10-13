# Reproducing the results

Everything in `results/` can be checked without re-running a simulation, and
re-run from scratch with the commands below.

## 1. Environment

Recorded runs used Linux x86-64, Python 3.13.16, numpy 2.5.4, scipy 1.18.1,
qiskit 2.5.2, qiskit-aer 0.17.2, cirq-core 1.7.0 (v0.2 study) and Windows 11
ARM64, Python 3.11.9, numpy 2.4.6, scipy 1.17.1 (v0.1 study). Each run entry
in `results/runs.jsonl` records its own environment, git commit and a hash
of `src/` and `experiments/` at launch and at completion.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

## 2. Check the recorded evidence (seconds; no simulation)

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

Runs append; they never overwrite. A re-run with the same seeds reproduces
the per-batch logs bit-for-bit on the same machine
(`tests/test_reproducibility.py`). Bit-identity across machines with
different core counts is not established (Aer parallelises with OpenMP;
see `docs/INVESTIGATION_V02.md` §4).

## 4. CI smoke tests (not evidence)

```bash
export QNP_RESULTS_DIR=$(mktemp -d)
python experiments/run_v02.py calibrate --smoke && python experiments/run_v02.py C --smoke
python tools/verify_results.py --results-dir "$QNP_RESULTS_DIR" --update
```

`--smoke` refuses to write into `results/`. Smoke runs use 3 runs per
condition and their pass/fail flags mean nothing.

## 5. Seeds

| Block | Range | Used for |
|---|---|---|
| development | < 20 000 | tests, design (`experiments/v02/DEVELOPMENT_NOTES.md`) |
| calibration | 20 000 – 21 999 | thresholds of the calibrated methods |
| confirmatory | 30 000 – 39 999, 40 000 – 54 999 | Experiments A–F |

`tools/check_provenance.py` fails if a recorded v0.2 run used a seed outside
its block.
