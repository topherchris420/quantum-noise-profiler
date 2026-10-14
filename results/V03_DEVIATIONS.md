# Deviations from experiments/V03_PREREGISTRATION.md

Each entry states what changed, why, and when relative to data collection.

Experiments G, H and I were run unchanged from the protocol and the code
committed with it (commit `8ea5b49`). The hardware pilot (Experiment P) ran
unchanged on 2026-10-13/14 (`V03_P_pilot-20261013T234830-220ff3`), after two
launches that were interrupted before completing (below).

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

## Experiment P interrupted twice (operational; no data recorded from either attempt)

Two launches of Experiment P on 2026-10-13 (`ibm_kingston`; both selected
qubits 93, 45, 44, 8, 127 by the preregistered rule) were killed by the host
before completing, because the machine ran low on memory (the run was a
background task of an agent session that stops such tasks under memory
pressure). No run entry or raw file was written for either: results are only
recorded when an experiment completes. Their jobs are listed so the attempts
can be audited; their results are not used in any analysis. Together they
used 170 s of the instance's QPU time.

| Attempt | Jobs completed | QPU time | Killed |
|---|---|---|---|
| 1 | 5 of 14 (sweep0, probe0–3) | 71 s | after probe3, before probe4 |
| 2 | 12 of 14 (sweep0, probe0–10) | 99 s | after probe10, before probe11 |

| Attempt | Job | IBM job id | Created (UTC) |
|---|---|---|---|
| 1 | sweep0 | `db79ocgr1c5c738k2nfg` | 21:01 |
| 1 | probe0 | `db79osgr1c5c738k2opg` | 21:02 |
| 1 | probe1 | `db79tj0r1c5c738k336g` | 21:12 |
| 1 | probe2 | `db7a290r1c5c738k3dd0` | 21:22 |
| 1 | probe3 | `db7a6v6r6oqs73874bjg` | 21:32 |
| 2 | sweep0 | `db7aaier6oqs73874jgg` | 21:40 |
| 2 | probe0 | `db7ab2mil99s73fnmcj0` | 21:41 |
| 2 | probe1 | `db7afp6il99s73fnmnlg` | 21:51 |
| 2 | probe2 | `db7akeur6oqs738759t0` | 22:01 |
| 2 | probe3 | `db7ap4or1c5c738k504g` | 22:11 |
| 2 | probe4 | `db7atr6il99s73fnnls0` | 22:21 |
| 2 | probe5 | `db7b2heil99s73fno4d0` | 22:31 |
| 2 | probe6 | `db7b76uil99s73fnodog` | 22:41 |
| 2 | probe7 | `db7bbsur6oqs73876vog` | 22:51 |
| 2 | probe8 | `db7bgj6r6oqs73877a70` | 23:01 |
| 2 | probe9 | `db7bl8qraffc73fa73kg` | 23:11 |
| 2 | probe10 | `db7bpv6r6oqs73877t10` | 23:21 |

The third launch (2026-10-13 23:48 UTC) ran to completion in its own
process, outside the agent session, with the same command and the same
committed source (`src/` and `experiments/` unchanged since commit `5e4d270`).
Nothing about the protocol changed. No backend was named on the command line,
so §5's rule chose the least busy device at launch, which was `ibm_fez`; the
qubit rule then chose 54, 108, 127, 59, 87 from that run's own snapshot.
Partial data are not stitched into a run: an interrupted session is not the
preregistered two-hour session.

## Experiment P provenance on a Windows checkout (no effect on the result)

The pilot ran on Windows with Git's `core.autocrlf=true`, which converts text
files to CRLF line endings on checkout. Two consequences, neither affecting
any recorded value:

1. **Source-tree hash.** `source_tree_sha256` (`experiments/common.py`) hashes
   the working-copy bytes of `src/` and `experiments/` with platform path
   separators, so the recorded value `880c5eea…` (CRLF, backslash paths) is
   reproducible on that checkout (recomputed after the run: identical) but
   not on Linux. The code is identified by `git_commit` `1ea9556` with
   `git_dirty` false; `src/` and `experiments/` are identical at `5e4d270`
   and `1ea9556`. SHA-256 over the git blobs of the same `.py` files at `1ea9556`
   (POSIX paths sorted as strings, LF content) is `9f467d6a…`.
2. **Result artifacts.** The CRLF checkout made the four uncompressed v0.1
   raw files fail their manifest hashes locally, although the committed
   blobs match the manifest. `.gitattributes` now marks `results/**` as
   `-text`, so recorded results are checked out byte for byte on every
   platform. The manifest gained only the two pilot entries; no recorded
   hash changed.
