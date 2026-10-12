"""MEASURED mode: dedicated characterization sequences with Bayesian fits.

T1: X, wait tau, measure.          P(1) = A*exp(-tau/T1) + B
T2: Hahn echo  SX, tau/2, X, tau/2, SX, measure.
                                   P(0) = A*exp(-tau/T2) + B
A and B absorb state-prep and readout error and are marginalized.
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

import numpy as np

from .models import Estimate, Metric, Provenance, Status, insufficient, utcnow
from .stats import fit_exponential_decay

T1_ASSUMPTIONS = (
    "single-exponential energy relaxation P1 = A exp(-t/T1) + B",
    "log-uniform prior on T1; uniform priors on A in [0.5,1], B in [0,0.2]",
)
T2_ASSUMPTIONS = (
    "Hahn echo; single-exponential decay P0 = A exp(-t/T2) + B",
    "log-uniform prior on T2; uniform priors on A in [0.2,0.55], B in [0.4,0.65]",
)


def t1_circuits(delays_s: Sequence[float]):
    from qiskit import QuantumCircuit

    out = []
    for tau in delays_s:
        qc = QuantumCircuit(1, 1, metadata={"qnp": "t1", "delay_s": float(tau)})
        qc.x(0)
        qc.delay(float(tau), 0, unit="s")
        qc.measure(0, 0)
        out.append(qc)
    return out


def t2_echo_circuits(delays_s: Sequence[float]):
    from qiskit import QuantumCircuit

    out = []
    for tau in delays_s:
        qc = QuantumCircuit(1, 1, metadata={"qnp": "t2_echo", "delay_s": float(tau)})
        qc.sx(0)
        qc.delay(float(tau) / 2, 0, unit="s")
        qc.x(0)
        qc.delay(float(tau) / 2, 0, unit="s")
        qc.sx(0)
        qc.measure(0, 0)
        out.append(qc)
    return out


def _estimate(metric, qubit, fit, timestamp, source, assumptions) -> Estimate:
    if not fit.ok:
        return insufficient(metric, (qubit,), Provenance.MEASURED, fit.reason, timestamp,
                            source=source, assumptions=assumptions)
    return Estimate(metric, (qubit,), Provenance.MEASURED, timestamp, Status.OK, fit.median,
                    fit.ci_low, fit.ci_high, fit.level, source=source, assumptions=assumptions)


def estimate_t1(qubit: int, delays_s, ones, shots, timestamp: datetime | None = None,
                source: str = "qnp-t1") -> Estimate:
    fit = fit_exponential_decay(np.asarray(delays_s), np.asarray(ones), shots,
                                amp_range=(0.5, 1.0), offset_range=(0.0, 0.2))
    return _estimate(Metric.T1, qubit, fit, timestamp or utcnow(), source, T1_ASSUMPTIONS)


def estimate_t2_echo(qubit: int, delays_s, zeros, shots, timestamp: datetime | None = None,
                     source: str = "qnp-t2-echo") -> Estimate:
    fit = fit_exponential_decay(np.asarray(delays_s), np.asarray(zeros), shots,
                                amp_range=(0.2, 0.55), offset_range=(0.4, 0.65))
    return _estimate(Metric.T2, qubit, fit, timestamp or utcnow(), source, T2_ASSUMPTIONS)


def run_t1(backend, qubit: int, delays_s, shots: int = 1000, seed: int | None = None,
           timestamp: datetime | None = None) -> Estimate:
    """Run T1 circuits on ``backend`` (anything with ``.run``, e.g. AerSimulator)."""
    from qiskit import transpile

    circs = transpile(t1_circuits(delays_s), backend, initial_layout=[qubit], optimization_level=0)
    res = backend.run(circs, shots=shots, seed_simulator=seed).result()
    ones = [res.get_counts(i).get("1", 0) for i in range(len(circs))]
    return estimate_t1(qubit, delays_s, ones, shots, timestamp)


def run_t2_echo(backend, qubit: int, delays_s, shots: int = 1000, seed: int | None = None,
                timestamp: datetime | None = None) -> Estimate:
    from qiskit import transpile

    circs = transpile(t2_echo_circuits(delays_s), backend, initial_layout=[qubit], optimization_level=0)
    res = backend.run(circs, shots=shots, seed_simulator=seed).result()
    zeros = [res.get_counts(i).get("0", 0) for i in range(len(circs))]
    return estimate_t2_echo(qubit, delays_s, zeros, shots, timestamp)
