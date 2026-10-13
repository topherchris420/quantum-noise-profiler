# Framework investigation for v0.2 (Qiskit, Aer, Qiskit Experiments, Qiskit Runtime, Cirq, Stim, REA)

Date 2026-10-12. Host: Linux x86-64, Python 3.13.16. Package versions:
qiskit 2.5.2, qiskit-aer 0.17.2, qiskit-experiments 0.14.2,
qiskit-ibm-runtime 0.50.0, cirq-core 1.7.0, stim 1.16.0, rea-agents 6.4.0.
The v0.1 log (`docs/INSPECTION_LOG.md`) is kept unchanged.

Every finding is tagged:

- **[source]** read in the installed package source (file and line given);
- **[runtime]** verified by running code here (test named);
- **[REA]** from REA evidence (evidence ID in `docs/evidence/rea/`);
- **[inference]** reasoned from the above, not directly observed;
- **[unverified]** an assumption nobody has checked yet.

All upstream packages are open source (Apache-2.0: Qiskit, Aer, Qiskit
Experiments, Qiskit Runtime, Cirq, Stim; MIT: REA). Nothing here
redistributes their code; file paths and line numbers point into the
installed packages.

## 1. Noise semantics the simulations rely on

| Finding | Tag | Evidence |
|---|---|---|
| `ReadoutError([[1-a, a], [b, 1-b]])`: row = prepared state, column = recorded bit, so P(1\|0)=a and P(0\|1)=b | [runtime] | `tests/test_sim_noise.py::test_asymmetric_readout_error` (200 000 shots each, within 4σ) |
| `thermal_relaxation_error(t1, t2, time)` rejects T2 > 2T1 and assumes zero excited-state population unless given | [source] | `qiskit_aer/noise/errors/standard_errors.py:257, 284-298` |
| Aer's relaxation on `delay` equals the closed-form amplitude damping e^(−t/T1) to 1e-9 and matches an independent Kraus-operator density-matrix evolution | [runtime] | `test_amplitude_damping_during_delay_matches_closed_form`, `test_thermal_relaxation_matches_independent_density_matrix` |
| Aer's T2 is Markovian: a Hahn echo does not refocus it (P0 = ½ + ½e^(−t/T2) exactly) | [runtime] | `test_hahn_echo_with_pure_dephasing_matches_closed_form` |
| Qiskit `depolarizing_error(λ, 1)` maps ρ → (1−λ)ρ + λ I/2, so a bit flips with probability λ/2 | [runtime] | `test_depolarizing_on_x_gate_closed_form_and_stim` |
| Cirq `depolarize(p)` applies each non-identity Pauli with probability p/(4ⁿ−1); equivalence with Qiskit needs p = 3λ/4 (n=1), 15λ/16 (n=2) | [source] + [runtime] | `cirq/ops/common_channels.py:251-271`; `test_cirq_channels_match_aer_density_matrix` (agreement to 2e-6) |
| Stim `DEPOLARIZE1(p)` flips a Z measurement with probability 2p/3; with p = 3λ/4 it reproduces Qiskit's λ/2 | [runtime] | same test, 400 000 Stim shots |
| Cirq `X**0.5` and Qiskit `sx` differ only by a global phase | [runtime] | density matrices agree in `test_cirq_channels_match_aer_density_matrix` |

**Consequence for v0.2:** the simulation layer (`qnp.sim`) and its Cirq
translation implement the same channels, which Experiment F relies on.

## 2. Execution results, metadata and indexing

| Finding | Tag | Evidence |
|---|---|---|
| Identical counts give identical estimates through the Qiskit and Cirq adapters on physical qubits 3 and 7 (little- vs big-endian handled) | [runtime] | `tests/test_adapter_validation.py::test_identical_counts_give_identical_estimates_across_frameworks` |
| Exact contexts are identical across frameworks once `X**-0.5` is named `sxdg` | [runtime] | `test_exact_contexts_agree_across_frameworks`; deviation DV2 |
| `BackendProperties.qubit_property(q)` returns `(value, datetime)` for T1, T2, readout error, `prob_meas1_prep0`, `prob_meas0_prep1`; dates differ per property | [runtime] on fake backends | `tests/test_hardware.py`; FakeTorino qubit 0: T1 dated 2025-01-29, readout 2025-02-25 |
| `IBMBackend.properties(datetime=...)` returns the snapshot closest to, but older than, `datetime`; raises `NotImplementedError` on IBM Quantum Compute | [source] | `qiskit_ibm_runtime/ibm_backend.py:326-351` |
| Whether that history is available to an Open-plan account today | [unverified] | no account used |
| `RuntimeJobV2.metrics()` returns `timestamps` (created, running, finished) and `usage` from the service | [source] | `qiskit_ibm_runtime/base_runtime_job.py:152-166` |
| The exact key set of `metrics()["timestamps"]` on the live service | [unverified] | `qnp.hardware.execution_timestamps` reports missing keys instead of guessing |
| Simulator backends return `properties() is None` | [source] | `ibm_backend.py:353-355`; `backend_snapshot` records it under `missing` |

## 3. Benchmarking reference: Qiskit Experiments T1

| Finding | Tag | Evidence |
|---|---|---|
| `T1Analysis` is a `DecayAnalysis` (least-squares fit of amp·e^(−x/τ)+base via lmfit) and reports a standard error, not a credible interval | [source] | `qiskit_experiments/library/characterization/analysis/t1_analysis.py:22`; `curve_analysis/curve_analysis.py:403-520` |
| Its fit-quality flag is "good" when 0 < χ²_red < 3, \|amp−1\| < 0.1, base < 0.1 and errors are not significant | [source] | `t1_analysis.py:40-61` |
| [inference] That quality flag is a heuristic gate, not a calibrated misfit test: for a bi-exponential curve, χ²_red < 3 can still hold at moderate shot counts. v0.2's checks are calibrated instead (Experiment D). | [inference] | — |

## 4. Native artifacts (REA)

REA 6.4.0 ran as a CLI from an isolated npm prefix. `rea-agents setup` was
**not** run, because it edits agent configuration. Its binary-layout
provider ran with a separately supplied pwntools 4.15.0 / pyelftools 0.33 /
Unicorn 2.1.2 interpreter, as REA requires; REA installs nothing itself.

| Finding | Tag | Evidence |
|---|---|---|
| Aer's `controller_wrappers…so` (SHA-256 `5209ab2b…8178`) dynamically links a vendored OpenMP runtime (`libgomp-a34b3233.so.1.0.0`) and OpenBLAS (`libopenblas-r0-f650aae0.3.3.so`) | [REA] | `ev_9db05c55…39e2` (`inspect-binary-layout`), `ev_be71f853…1185` (`inspect-artifact`) |
| Qiskit's `_accelerate.abi3.so` (SHA-256 `0c1170ac…c214`, Rust) links only libc/libm/libpthread/libdl/libgcc_s | [REA] | `ev_dd92c7d1…e09`, `ev_e703af9b…bce` |
| [inference] Aer can parallelise shots and circuits with OpenMP, so a fixed `seed_simulator` reproduces counts only if the parallel decomposition is also fixed. Determinism is verified on this 4-core host (`tests/test_reproducibility.py`); bit-identity across machines with different thread counts is **[unverified]**. The CI matrix reruns the determinism test on three operating systems, which checks within-machine determinism, not cross-machine identity. | [inference] | `qiskit_aer/backends/aer_simulator.py:220-230` (`max_parallel_threads`, `max_parallel_shots`) |

**What REA did not do, and why.** No disassembly or decompilation was
performed. REA's Ghidra provider reports `not_configured` (no
`GHIDRA_INSTALL_DIR`). Java 21 is present, so a Ghidra 12.1 install would
work on this host, unlike the Windows ARM64 host of v0.1. It was not
installed because the questions this project has about Aer, Qiskit, Cirq
and Stim are answered by their published source and by runtime tests
above. Decompiling open-source extensions would add little beyond
checking that a shipped binary matches its tagged source, which is a
supply-chain question outside this study. REA's artifact identity and
linkage evidence (above) was the part that added information not visible
in the Python source: the OpenMP dependency behind the determinism caveat.

## 5. Cross-framework discrepancy investigation (Experiment F)

| Finding | Tag | Evidence |
|---|---|---|
| Sampled mean flip rates differ by 0.1–0.6% relative (largest 2.5 SE), with Cirq higher in all four contexts | [runtime] | `V02_F_cross_framework-20261013T003304-0c31fc` |
| Exact density-matrix flip probabilities of the same circuits under the F device agree to ≤ 1e-7 between Aer and Cirq | [runtime] | `tests/test_v02_harness.py::test_experiment_f_circuits_have_identical_exact_flip_probabilities_in_aer_and_cirq` |
| [inference] The sampled difference is sampling noise: four same-sign differences have probability 1/8 under the null, and the exact probabilities are equal | [inference] | — |
| With two-qubit depolarizing set to zero, `qnp.sim.aer_noise_model` added **no** noise to `cx`, dropping thermal relaxation during two-qubit gates, while the Cirq builder kept it (state-flip 0.0022 vs 0.0078) | [runtime] | found by the same exact comparison; fixed, regression test `test_two_qubit_gate_relaxation_without_depolarizing_matches_cirq` |
| No recorded experiment used that configuration (A–C: readout-only; D13: no 2q gates; E, F: depol_2q = 0.01) | [source] | `experiments/v02/workloads.py`, `experiments/common.py` |

## 6. Open questions carried forward

1. Live IBM Runtime: calibration history, `metrics()` fields, quotas [unverified].
2. Cross-machine bit-identity of Aer runs [unverified]; within-machine determinism verified.
3. Whether real-device readout drift has the batch-independence structure the e-processes assume [unverified]; see `docs/HARDWARE_VALIDATION.md`.
