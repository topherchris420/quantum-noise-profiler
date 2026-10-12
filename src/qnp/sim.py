"""Configurable simulated noise for validation experiments (Qiskit Aer and Cirq).

What is modelled (per qubit unless stated):

* thermal relaxation with T1, T2 (T2 <= 2 T1) during gates and during
  explicit ``delay`` instructions (Aer ``RelaxationNoisePass``);
* amplitude damping and pure dephasing as separate channels (via T1 and the
  pure-dephasing time T_phi, 1/T2 = 1/(2 T1) + 1/T_phi);
* depolarizing noise per gate, configurable by gate name (gate-dependent);
* two-qubit depolarizing noise per coupler;
* asymmetric readout error P(read 1 | 0) != P(read 0 | 1);
* time variation of any parameter across batches (``qnp.sim`` schedules:
  ramps, steps, Ornstein-Uhlenbeck correlated disturbances, telegraph
  two-level-system switching), missing observations and irregular
  observation intervals.

What is *not* modelled, and therefore not validated by any experiment that
uses this module: leakage outside the qubit subspace, coherent (unitary)
over-rotation and crosstalk, non-Markovian 1/f dephasing within a circuit
(the echo cancels nothing here: Aer's T2 is Markovian), measurement-induced
state transitions, thermal excited-state population, correlated errors
*within* a circuit across qubits, and calibration-dependent changes of gate
durations. The simulator does not reproduce the behaviour of any specific
superconducting, trapped-ion or neutral-atom device; parameter values are
chosen to be in a plausible range, not fitted to hardware.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import numpy as np

ONE_Q_NOISY = ("x", "sx", "sxdg", "h", "ry", "rx", "u", "u3", "y")
TWO_Q_NOISY = ("cx", "cz", "ecr")
DEFAULT_GATE_TIMES = {
    "sxdg": 35.5e-9,
    "x": 35.5e-9,
    "sx": 35.5e-9,
    "h": 35.5e-9,
    "ry": 35.5e-9,
    "rx": 35.5e-9,
    "u": 35.5e-9,
    "u3": 35.5e-9,
    "y": 35.5e-9,
    "rz": 0.0,
    "cx": 300e-9,
    "cz": 300e-9,
    "ecr": 300e-9,
}


@dataclass(frozen=True)
class QubitNoise:
    t1_s: float | None = None
    t2_s: float | None = None
    p_read1_given0: float = 0.0
    p_read0_given1: float = 0.0
    depol_1q: float = 0.0  # Qiskit depolarizing parameter lambda: rho -> (1-l) rho + l I/2

    def __post_init__(self) -> None:
        for name in ("p_read1_given0", "p_read0_given1", "depol_1q"):
            v = getattr(self, name)
            if not 0 <= v <= 1:
                raise ValueError(f"{name} must be in [0, 1], got {v}")
        if (self.t1_s is None) != (self.t2_s is None):
            raise ValueError("give both t1_s and t2_s, or neither")
        if self.t1_s is not None:
            t2_s = cast(float, self.t2_s)  # given together with t1_s (checked above)
            if self.t1_s <= 0 or t2_s <= 0:
                raise ValueError("T1 and T2 must be positive")
            if t2_s > 2 * self.t1_s * (1 + 1e-12):
                raise ValueError(f"T2={self.t2_s} > 2*T1={2 * self.t1_s} is unphysical")

    @property
    def t_phi_s(self) -> float | None:
        """Pure-dephasing time: 1/T_phi = 1/T2 - 1/(2 T1); inf if T2 == 2 T1."""
        if self.t1_s is None:
            return None
        rate = 1 / cast(float, self.t2_s) - 1 / (2 * self.t1_s)  # t2_s is set whenever t1_s is
        return float("inf") if rate <= 0 else 1 / rate


@dataclass(frozen=True)
class DeviceNoise:
    qubits: Mapping[int, QubitNoise]
    depol_2q: float = 0.0
    depol_2q_per_pair: Mapping[tuple[int, int], float] = field(default_factory=dict)
    gate_scale: Mapping[str, float] = field(default_factory=dict)  # gate-dependent multiplier on depol_1q
    gate_times: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_GATE_TIMES))
    relax_during_gates: bool = True

    def with_qubit(self, q: int, **changes: Any) -> DeviceNoise:
        qs = dict(self.qubits)
        qs[q] = replace(qs.get(q, QubitNoise()), **changes)
        return replace(self, qubits=qs)


def readout_only(p_by_qubit: Mapping[int, float], asymmetry: float = 0.0) -> DeviceNoise:
    """Symmetric (asymmetry=0) or asymmetric readout error only. With
    asymmetry a, P(0|1) = p (1 + a) and P(1|0) = p (1 - a)."""
    return DeviceNoise(
        {
            q: QubitNoise(p_read1_given0=p * (1 - asymmetry), p_read0_given1=p * (1 + asymmetry))
            for q, p in p_by_qubit.items()
        }
    )


# --------------------------------------------------------------------------- Qiskit Aer


def aer_noise_model(device: DeviceNoise):
    from qiskit_aer.noise import NoiseModel, ReadoutError, depolarizing_error, thermal_relaxation_error

    nm = NoiseModel(basis_gates=sorted(set(ONE_Q_NOISY) | set(TWO_Q_NOISY) | {"rz", "id", "delay", "measure"}))
    for q, qn in device.qubits.items():
        for g in ONE_Q_NOISY:
            err = None
            lam = qn.depol_1q * device.gate_scale.get(g, 1.0)
            if lam > 0:
                err = depolarizing_error(min(lam, 1.0), 1)
            t = device.gate_times.get(g, 0.0)
            if device.relax_during_gates and qn.t1_s is not None and t > 0:
                th = thermal_relaxation_error(qn.t1_s, qn.t2_s, t)
                err = th if err is None else err.compose(th)
            if err is not None:
                nm.add_quantum_error(err, g, [q])
        if qn.p_read1_given0 > 0 or qn.p_read0_given1 > 0:
            nm.add_readout_error(
                ReadoutError([[1 - qn.p_read1_given0, qn.p_read1_given0], [qn.p_read0_given1, 1 - qn.p_read0_given1]]),
                [q],
            )
    pairs = set(device.depol_2q_per_pair)
    qs = sorted(device.qubits)
    if device.depol_2q > 0:
        pairs |= {(a, b) for a in qs for b in qs if a != b}
    for a, b in sorted(pairs):
        lam = device.depol_2q_per_pair.get((a, b), device.depol_2q)
        for g in TWO_Q_NOISY:
            err = depolarizing_error(lam, 2) if lam > 0 else None
            t = device.gate_times.get(g, 0.0)
            qa, qb = device.qubits.get(a), device.qubits.get(b)
            if device.relax_during_gates and t > 0 and qa and qb and qa.t1_s and qb.t1_s:
                th = thermal_relaxation_error(qb.t1_s, qb.t2_s, t).expand(thermal_relaxation_error(qa.t1_s, qa.t2_s, t))
                err = th if err is None else err.compose(th)
            if err is not None:
                nm.add_quantum_error(err, g, [a, b])
    return nm


def add_delay_relaxation(circuits, device: DeviceNoise):
    """Insert thermal relaxation on ``delay`` instructions (durations in seconds)."""
    from qiskit.circuit import Delay
    from qiskit_aer.noise import RelaxationNoisePass

    n = max(max(device.qubits) + 1, max(c.num_qubits for c in circuits))
    t1s = [device.qubits[q].t1_s if q in device.qubits and device.qubits[q].t1_s else float("inf") for q in range(n)]
    t2s = [device.qubits[q].t2_s if q in device.qubits and device.qubits[q].t2_s else float("inf") for q in range(n)]
    p = RelaxationNoisePass(t1s, t2s, dt=None, op_types=[Delay])
    return [p(c) for c in circuits]


def aer_run_counts(circuits, device: DeviceNoise, shots: int, seed: int) -> list[dict[str, int]]:
    """Run circuits on Aer under ``device`` noise; returns counts dicts."""
    from qiskit_aer import AerSimulator

    sim = AerSimulator(noise_model=aer_noise_model(device))
    circs = circuits
    if any(inst.operation.name == "delay" for c in circuits for inst in c.data):
        circs = add_delay_relaxation(circuits, device)
    res = sim.run(circs, shots=shots, seed_simulator=seed).result()
    return [res.get_counts(i) for i in range(len(circs))]


# --------------------------------------------------------------------------- Cirq


def _readout_kraus(p10: float, p01: float):
    """Classical asymmetric readout as a channel before a Z measurement.
    p01 = P(read 1 | 0), p10 = P(read 0 | 1)."""
    k0 = np.array([[np.sqrt(1 - p01), 0], [0, np.sqrt(1 - p10)]])
    k1 = np.array([[0, np.sqrt(p10)], [0, 0]])
    k2 = np.array([[0, 0], [np.sqrt(p01), 0]])
    return (k0, k1, k2)


def _cirq_relaxation_ops(q, qn: QubitNoise, t: float):
    import cirq

    if qn.t1_s is None or t <= 0:
        return []
    ops = [cirq.amplitude_damp(1 - np.exp(-t / qn.t1_s)).on(q)]
    tphi = qn.t_phi_s
    if tphi is not None and np.isfinite(tphi):
        ops.append(cirq.phase_damp(1 - np.exp(-2 * t / tphi)).on(q))
    return ops


def cirq_noisy_circuit(circuit, device: DeviceNoise, index_of=lambda q: q.x):
    """Return a copy of ``circuit`` with the device's noise channels inserted.

    Gate names follow Qiskit's convention through a small map (X -> x,
    X**0.5 -> sx, H -> h, Ry -> ry, CNOT -> cx, CZ -> cz); ``cirq.WaitGate``
    plays the role of ``delay``. Depolarizing parameters are converted from
    Qiskit's lambda to Cirq's p (p = 3 lambda / 4 for one qubit,
    15 lambda / 16 for two)."""
    import cirq

    from .adapters.cirq_adapter import canonical_gate_name as gname

    out = []
    for moment in circuit:
        noise_after = []
        for op in moment.operations:
            if cirq.is_measurement(op):
                pre = []
                for q in op.qubits:
                    qn = device.qubits.get(index_of(q))
                    if qn and (qn.p_read1_given0 or qn.p_read0_given1):
                        pre.append(cirq.KrausChannel(_readout_kraus(qn.p_read0_given1, qn.p_read1_given0)).on(q))
                if pre:
                    out.append(cirq.Moment(pre))
                continue
            if isinstance(op.gate, cirq.WaitGate):
                t = op.gate.duration.total_nanos() * 1e-9
                for q in op.qubits:
                    qn = device.qubits.get(index_of(q))
                    if qn:
                        noise_after += _cirq_relaxation_ops(q, qn, t)
                continue
            name = gname(op)
            t = device.gate_times.get(name, 0.0)
            if len(op.qubits) == 1:
                q = op.qubits[0]
                qn = device.qubits.get(index_of(q))
                if qn and name in ONE_Q_NOISY:
                    lam = qn.depol_1q * device.gate_scale.get(name, 1.0)
                    if lam > 0:
                        noise_after.append(cirq.depolarize(3 * lam / 4).on(q))
                    if device.relax_during_gates:
                        noise_after += _cirq_relaxation_ops(q, qn, t)
            elif len(op.qubits) == 2 and name in TWO_Q_NOISY:
                a, b = (index_of(q) for q in op.qubits)
                lam = device.depol_2q_per_pair.get((a, b), device.depol_2q)
                if lam > 0:
                    noise_after.append(cirq.depolarize(15 * lam / 16, n_qubits=2).on(*op.qubits))
                if device.relax_during_gates:
                    for q in op.qubits:
                        qn = device.qubits.get(index_of(q))
                        if qn:
                            noise_after += _cirq_relaxation_ops(q, qn, t)
        out.append(
            cirq.Moment(
                [
                    op
                    for op in moment.operations
                    if not isinstance(op.gate, cirq.WaitGate) and not cirq.is_measurement(op)
                ]
            )
        )
        if noise_after:
            # split into moments without qubit overlap
            while noise_after:
                used: set[Any] = set()
                this, rest = [], []
                for op in noise_after:
                    if used & set(op.qubits):
                        rest.append(op)
                    else:
                        this.append(op)
                        used |= set(op.qubits)
                out.append(cirq.Moment(this))
                noise_after = rest
        # measurement moment re-added after readout noise
        meas = [op for op in moment.operations if cirq.is_measurement(op)]
        if meas:
            out.append(cirq.Moment(meas))
    return cirq.Circuit(m for m in out if len(m.operations))


# --------------------------------------------------------------------------- schedules


def linear_ramp(start: float, end: float, n: int) -> np.ndarray:
    return np.linspace(start, end, n)


def step(base: float, ratio: float, at: int, n: int) -> np.ndarray:
    return np.where(np.arange(n) < at, base, base * ratio)


def ou_log_process(
    base: float, sigma: float, tau_batches: float, n: int, rng: np.random.Generator, n_series: int = 1, rho: float = 0.0
) -> np.ndarray:
    """Correlated disturbances: base * exp(x_t) with x an Ornstein-Uhlenbeck
    process (stationary sd ``sigma``, correlation time ``tau_batches``),
    started in its stationary law. With ``n_series`` > 1, series share a
    common-mode component with correlation ``rho``. Returns (n_series, n)."""
    if tau_batches <= 0 or sigma < 0 or not 0 <= rho <= 1:
        raise ValueError("need tau_batches > 0, sigma >= 0, rho in [0, 1]")
    a = np.exp(-1 / tau_batches)
    innov = np.sqrt(1 - a * a)
    common = np.empty(n)
    own = np.empty((n_series, n))
    common[0] = rng.normal()
    own[:, 0] = rng.normal(size=n_series)
    for t in range(1, n):
        common[t] = a * common[t - 1] + innov * rng.normal()
        own[:, t] = a * own[:, t - 1] + innov * rng.normal(size=n_series)
    x = sigma * (np.sqrt(rho) * common[None, :] + np.sqrt(1 - rho) * own)
    return base * np.exp(x)


def telegraph(low: float, high: float, switch_prob: float, n: int, rng: np.random.Generator) -> np.ndarray:
    """Two-level-system switching: the value flips between ``low`` and ``high``
    with probability ``switch_prob`` per batch (TLS-like T1 fluctuations)."""
    state = rng.random() < 0.5
    out = np.empty(n)
    for t in range(n):
        out[t] = high if state else low
        if rng.random() < switch_prob:
            state = not state
    return out


def missing_mask(n: int, p_missing: float, rng: np.random.Generator, keep_first: int = 0) -> np.ndarray:
    """True where the batch is missing (job failed / not run)."""
    m = rng.random(n) < p_missing
    m[:keep_first] = False
    return m


def irregular_timestamps(
    n: int,
    mean_interval: timedelta,
    jitter: float,
    rng: np.random.Generator,
    t0: datetime = datetime(2026, 1, 1, tzinfo=timezone.utc),
) -> list[datetime]:
    """Strictly increasing timestamps with gamma-distributed gaps
    (coefficient of variation ``jitter``; 0 gives a regular grid)."""
    if jitter < 0:
        raise ValueError("jitter must be >= 0")
    if jitter == 0:
        gaps = np.full(n, mean_interval.total_seconds())
    else:
        k = 1 / jitter**2
        gaps = rng.gamma(k, mean_interval.total_seconds() / k, n)
    gaps = np.maximum(gaps, 1.0)
    t = np.cumsum(np.r_[0.0, gaps[:-1]])
    return [t0 + timedelta(seconds=float(s)) for s in t]


def recalibration_batches(n: int, mean_interval_batches: float, rng: np.random.Generator) -> list[int]:
    """Irregular recalibration events (geometric gaps)."""
    out: list[int] = []
    t = 0
    while True:
        t += int(rng.geometric(1 / mean_interval_batches))
        if t >= n:
            return out
        out.append(t)


def schedule_devices(base: DeviceNoise, changes: Iterable[tuple[int, str, np.ndarray]]) -> list[DeviceNoise]:
    """Per-batch devices: ``changes`` = (qubit, QubitNoise field, values per batch)."""
    changes = list(changes)
    n = len(changes[0][2]) if changes else 0
    out = []
    for i in range(n):
        d = base
        for q, name, values in changes:
            d = d.with_qubit(q, **{name: float(values[i])})
        out.append(d)
    return out


__all__ = [
    "DeviceNoise",
    "QubitNoise",
    "add_delay_relaxation",
    "aer_noise_model",
    "aer_run_counts",
    "cirq_noisy_circuit",
    "irregular_timestamps",
    "linear_ramp",
    "missing_mask",
    "ou_log_process",
    "readout_only",
    "recalibration_batches",
    "schedule_devices",
    "step",
    "telegraph",
]
