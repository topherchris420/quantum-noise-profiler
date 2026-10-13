# Deviations from experiments/V03_PREREGISTRATION.md

Each entry states what changed, why, and when relative to data collection.

Experiments G, H and I were run unchanged from the protocol and the code
committed with it (commit `8ea5b49`). The hardware pilot (Experiment P) has
not been run.

## Code changes after the confirmatory runs (2026-10-13)

Code review of the pull request found two defects; a CI type check found a
third issue. None of these changes affects a recorded result.

1. **Pilot analysis, before any pilot data.**
   - *Defect:* `experiments/v03/pilot.py` counted a sweep's reference
     p-value of exactly 0.0 as 1.0 (`p or 1.0` treats 0.0 as missing). A
     p-value of 0.0 is a chi-square underflow: the strongest disagreement
     between references, exactly the case P.C2 exists to catch.
   - *Fix:* only a missing p-value (no references) is now skipped.
   - *Protocol:* the rule (reject at α = 0.01) is unchanged; the code now
     implements it. No pilot data existed. Test:
     `tests/test_pilot.py::test_reference_p_value_that_underflows_to_zero_counts_as_a_rejection`.
2. **Readout-probe recognition (`qnp.adapters`).**
   - *Defect:* the Qiskit recognizer accepted a barrier that holds a qubit
     still to be measured until another qubit's measurement ends. The Cirq
     recognizer accepted empty moments, or another qubit's measurement,
     between a qubit's X and its measurement. Either way a prepared |1⟩
     waits and decays, so its error depends on the circuit.
   - *Fix:* both recognizers now treat such circuits as workload.
   - *Recorded results:* all 120 circuits of Experiment G (36 of them
     probes) are classified identically before and after the change.
     Experiments H and I do not use the recognizers.
3. **Type annotation only (`qnp.stats.reference_homogeneity`).** The pooled
   rate is now computed as a division of Python floats rather than of NumPy
   scalars, for mypy 2.4. It is the same IEEE operation, so the result is
   bit-identical.
