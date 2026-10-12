# Inspection log (Phase 1)

Date: 2026-10-12. Environment: Windows 11 on ARM64, Python 3.11.9.
Packages inspected: qiskit 2.5.2, qiskit-aer 0.17.2, qiskit-experiments 0.14.2,
cirq-core 1.7.0, pyquil 4.22.0 (qcs-sdk-python 0.21.22).

Each finding is tagged **observed** (we ran it or read it in the installed
package), **REA** (from REA's artifact evidence) or **unverified**.

## 1. What each framework hands back

### Qiskit 2.5 (observed)
- `SamplerV2.run(...).result()` → `PrimitiveResult`, iterable of
  `SamplerPubResult`. `pub.data.<creg_name>` is a `BitArray`; `measure_all()`
  names it `meas`. `BitArray.get_counts()` gives little-endian bitstrings per
  register. `shape == ()` unless the pub has a parameter sweep.
- Pub metadata: `{'shots': N, 'circuit_metadata': {...}}`. **No execution
  timestamp** in the result. IBM Runtime exposes timing via `job.metrics()`;
  the profiler takes an explicit timestamp argument instead.
- Legacy `Result.get_counts(i)`: one string per shot pattern; registers are
  separated by spaces. Stripping spaces gives the global clbit order, still
  little-endian.
- Calibration lives on `backend.target` (`Target`):
  `qubit_properties[q].t1/.t2/.frequency`; `target[op][qargs]` →
  `InstructionProperties(duration, error)`; `target['measure'][(q,)].error` is
  the readout error. `Target` has **no calibration timestamp**.
  `BackendProperties` was removed from Qiskit 2.x core. IBM Runtime backends
  still provide `backend.properties()` with `last_update_date` (unverified
  against a live account; to be checked in Phase 4).
- Circuits run on hardware must be ISA circuits (transpiled to physical
  qubits). `circuit.find_bit(q).index` on an ISA circuit gives the physical
  index. If logical circuits are passed instead, qubit labels are logical.

### Qiskit Aer 0.17 (observed)
- `AerSimulator.from_backend(GenericBackendV2)` applies thermal relaxation
  during `delay`. A T1 sweep matched e^(−τ/T1) to within 0.02 at τ = 0, T1/2,
  T1 and 2T1 (4000 shots). This makes it a usable ground-truth harness.
- `qiskit_aer.primitives.SamplerV2(seed=..., options={"backend_options": ...})`:
  the seed is a constructor argument, not a run option.

### qiskit-experiments 0.14.2 (observed)
- Works with Qiskit 2.5. `T1(physical_qubits=(0,), delays=...)` on Aer
  recovered T1 = 162 ± 5 µs against a truth of 162.5 µs. Results come back as
  `analysis_results("T1", dataframe=True)` with a `uncertainties.ufloat`
  value: a least-squares standard error, not a credible interval. We use it as
  an independent cross-check (`tests/test_cirq_and_measured.py`), not as our
  estimator.

### Cirq 1.7 (observed)
- `cirq.Result.measurements[key]` → `ndarray (repetitions, n_qubits_in_key)`;
  column order = qubit order in the `measure` op. Also `.records`, `.params`,
  `.data` (DataFrame), `.histogram()`.
- `circuit.are_all_measurements_terminal()`, `cirq.drop_terminal_measurements`
  and `cirq.final_state_vector(qubit_order=...)` (big-endian) give everything
  needed for the ideal-outcome analysis.
- Device calibration lives in `cirq_google` (`Calibration`), which is not
  installed here. Cirq OBSERVED mode is deferred.

### pyQuil 4.22 / qcs-sdk 0.21.22 (observed + REA)
- `QAMExecutionResult` exposes `get_register_map()`, `get_memory_values()`,
  `get_raw_readout_data()`, `readout_data` and `execution_duration_microseconds`.
- **REA** (`inspect_artifact` on the shipped wheel, evidence
  `ev_191c80354fa03654d200bce7e2918cc15afedc79a809594b12de0ad801a42523`):
  the `qcs_sdk` wheel is one 18.3 MB native PE extension
  (`qcs_sdk.cp311-win_amd64.pyd`) plus `.pyi` stubs and near-empty `__init__.py`
  shims. There is **no Python implementation** of `qpu/api`, `qpu/isa`,
  `qvm/api` or `compiler/quilc`; the stubs are the only readable contract on
  the Python side.
- From those stubs (`qcs_sdk/qpu/isa.pyi`): `InstructionSetArchitecture`
  has `.instructions` and `.benchmarks` (lists of `Operation`).
  `Operation.characteristics` / `.sites[*].characteristics` are lists of
  `Characteristic(name, value, error: Optional[float], node_ids, timestamp)`.
  Rigetti therefore reports a per-value uncertainty and a timestamp. Those
  are better OBSERVED inputs than Qiskit's `Target`. The pyQuil adapter is
  deferred until it can be tested against a real ISA payload.

## 2. REA usage and its limits on this host
- REA's deep native providers could not run here. Ghidra 12.1.4 is installed
  but REA rejects it on Windows ARM64 (`unsupported_host`; no native decompiler
  for win32/arm64). Hopper is macOS-only. IDA isn't configured. So
  disassembly, string search and decompilation of `qiskit/_accelerate.pyd`
  (20.3 MB), `qcs_sdk.pyd` and `quil.pyd` were **not performed**.
- What did work: archive inventory of shipped wheels (above).
- Is it needed? Qiskit (`_accelerate`, Rust), qcs-sdk-rust and quil-rs are
  open source. For this project, the source repositories answer the same
  questions with less effort. Binary RE would matter only for checking that a
  shipped wheel matches its tagged source, or for closed vendor runtimes.
  Next step if wanted: run REA on an x64 Linux/macOS host or configure IDA.

## 3. Identifiability: what workload data can and cannot tell us
- **T1 / T2 are not identifiable from ordinary workload counts.** T1 needs
  population decay over controlled delays. T2 needs a Ramsey or echo sequence.
  A workload circuit's counts mix gate, decoherence and SPAM error through an
  unknown, circuit-specific map. The profiler therefore estimates these only in
  MEASURED mode or reads them in OBSERVED mode.
- **Identifiable from workload:** for any measured qubit whose noiseless
  outcome is a deterministic bit, the observed flip rate (`effective_flip_rate`).
  It is specific to circuit context. It equals readout error only when nothing
  precedes the measurement. Mirror circuits, error-detection syndromes and
  computational-basis-state preparation all produce such qubits naturally.
- **Not identifiable per qubit:** qubits whose ideal output is in
  superposition. Comparing observed and ideal distributions gives a
  circuit-level fidelity at best, which can't be attributed to qubits without
  further assumptions. v0.1 reports INSUFFICIENT_EVIDENCE for these qubits.

## 4. Brief references checked
- `github.com/morluto/rea`: exists, MIT licence (observed via GitHub API).
- `github.com/google/benchmark_2019`: **404, does not exist** (observed). Not
  used as a data source.
- DOE Genesis Mission Phase II (2026-10-08), DARPA "PA-26-02-02" and the DOE
  2028 FTQC RFI targets: **unverified**. These postdate or fall outside what
  we checked. The README makes no funding claims until someone verifies them.
