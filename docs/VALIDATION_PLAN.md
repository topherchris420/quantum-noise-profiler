# Validation plan

## Done in this sprint (simulator, preregistered)
E1 gradual drift, E2 sudden degradation, E3 insufficient evidence. See
`experiments/PREREGISTRATION.md` for the fixed criteria and `results/runs.jsonl`
for every run (failures included). Their limitation: readout error is the
only injected noise, so the ground truth is clean but gate-noise confounding
of `effective_flip_rate` isn't exercised.

## Next: simulator realism (no hardware needed)
1. **Gate-noise confounding.** Add depolarizing and thermal-relaxation gate
   noise that drifts independently of readout. Check that contexts with
   different gate counts move as predicted, and that drift alerts in the
   `1q<=0` context track readout drift only.
2. **Workload-mix shift.** Keep the hardware constant and change the job mix.
   No drift alerts should fire, because contexts isolate the mix change.
   This is the main false-alarm risk in real deployments.
3. **Misfit detection.** Add a posterior-predictive goodness-of-fit check to
   the decay fits, then re-run E3d as a new log entry.
4. **Cirq parity.** Re-run E2 through the Cirq adapter with
   `cirq.DensityMatrixSimulator` and injected `bit_flip` drift.

## Real hardware: IBM Quantum (Open plan)
- **Backend:** whichever 127/156-qubit Eagle/Heron device the account can
  access; record the backend name and `properties().last_update_date` with
  every run.
- **Observed:** poll `backend.properties()` hourly for 30 days. This is the
  OBSERVED series for T1, T2, readout and 2q error.
- **Measured:** on 5 chosen qubits, run T1 and Hahn-echo sweeps (15 delays,
  1000 shots) twice daily, within the Open-plan time budget.
- **Inferred:** a fixed probe job every hour on the same qubits: basis-state
  prep (|0⟩, |1⟩) plus mirror circuits of depth 2, 8, 32 → contexts.
- **Comparisons:**
  - measured T1/T2 vs observed T1/T2: agreement rate of observed values
    within our credible intervals, and systematic offsets;
  - inferred `1q<=0` flip rate vs observed readout error;
  - detection lag: time from a change in the observed series to the first
    profiler alert in the measured/inferred series, and the reverse (do we
    see changes between IBM's calibration cycles?).
- **Historical data:** whether IBM still serves 30-day calibration history
  via `properties(datetime=...)` on current Runtime must be checked first.
  If it doesn't, the 30-day series has to be collected prospectively by the
  hourly poll.

## Rigetti / QCS
Blocked on access. The ISA `Characteristic` carries `error` and `timestamp`
(see the inspection log), so OBSERVED ingestion should be straightforward once
a real payload is available.

## Reporting
Every hardware run is appended to `results/runs.jsonl` with the backend name,
calibration timestamp, git commit and package versions. Nothing is deleted.
