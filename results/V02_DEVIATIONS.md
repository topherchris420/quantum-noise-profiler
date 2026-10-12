# Deviations from experiments/V02_PREREGISTRATION.md

Each entry states what changed, why, and when relative to data collection.

## DV1 — Experiment E padding counts (clarification; before any Experiment E data)

Found while implementing the workloads, before any Experiment E circuit
was simulated:

- **E1 "4 → 8 identity `sx` pairs-of-pairs"** is implemented as 4 → 8
  padding `sx` gates on each qubit of each mirror circuit (`sx`⁴ = I, so
  both paddings are identities). 1q counts 10/11 → 14/15, same `1q<=16`
  bucket, as intended.
- **E3 "10-`sx`-padded mirrors"** cannot be implemented as written: `sx`¹⁰ =
  X is not an identity, and with the X-terminated mirror it gives 17 1q
  gates, leaving the `1q<=16` bucket that the scenario is meant to stay
  in. Implemented as **8**-`sx` padding (identity, 14/15 gates, same
  bucket). The scenario's purpose — a mix shift between circuits of the same
  bucket with different noise — is unchanged.

## DV2 — gate naming for `sxdg` (implementation; before any Experiment E/F data)

The mirror circuits' inverse layer contains `sxdg`. `qnp.sim` now treats
`sxdg` as a noisy 1q gate (same parameters as `sx`) and the Cirq adapter
maps `X**-0.5` to `sxdg`, so exact contexts and noise agree across
frameworks. Without this, Cirq would label the gate `rx` and Qiskit `sxdg`,
which would fail F.C2 for a naming reason rather than a physical one.
