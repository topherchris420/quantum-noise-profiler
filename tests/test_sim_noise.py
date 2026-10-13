"""Baseline verification of the simulation layer against analytically
tractable models and independent numerical references.

References used:
* closed-form expressions (amplitude damping, pure dephasing, depolarizing,
  readout asymmetry);
* an independent density-matrix evolution written here from textbook Kraus
  operators (not from Aer or Cirq);
* Cirq's density-matrix simulator for the same channels;
* Stim's Pauli-frame sampler for depolarizing flip rates (optional).
"""

import numpy as np
import pytest
from qiskit import QuantumCircuit

from qnp.sim import (
    DeviceNoise,
    QubitNoise,
    aer_noise_model,
    aer_run_counts,
    cirq_noisy_circuit,
    irregular_timestamps,
    missing_mask,
    ou_log_process,
    readout_only,
    telegraph,
)

T1, T2 = 100e-6, 80e-6


# ----------------------------------------------------------------- independent reference


def thermal_kraus(t1, t2, t):
    """Amplitude damping (gamma = 1 - e^{-t/T1}) followed by pure dephasing
    chosen so the total coherence factor is e^{-t/T2}."""
    g = 1 - np.exp(-t / t1)
    ad = [np.array([[1, 0], [0, np.sqrt(1 - g)]]), np.array([[0, np.sqrt(g)], [0, 0]])]
    coh_ad = np.sqrt(1 - g)
    lam = np.exp(-t / t2) / coh_ad  # remaining coherence factor
    pd = [np.array([[1, 0], [0, lam]]), np.array([[0, 0], [0, np.sqrt(1 - lam**2)]])]
    return [b @ a for a in ad for b in pd]


def apply(rho, ks):
    return sum(k @ rho @ k.conj().T for k in ks)


X = np.array([[0, 1], [1, 0]], complex)
SX = 0.5 * np.array([[1 + 1j, 1 - 1j], [1 - 1j, 1 + 1j]])


def _aer_dm(qc, device):
    from qiskit_aer import AerSimulator

    from qnp.sim import add_delay_relaxation

    qc = add_delay_relaxation([qc], device)[0]
    qc.save_density_matrix()
    sim = AerSimulator(method="density_matrix", noise_model=aer_noise_model(device))
    return np.asarray(sim.run(qc).result().data()["density_matrix"])


def test_amplitude_damping_during_delay_matches_closed_form():
    dev = DeviceNoise({0: QubitNoise(T1, 2 * T1)}, relax_during_gates=False)
    for t in (0.0, 0.5 * T1, T1, 2 * T1):
        qc = QuantumCircuit(1)
        qc.x(0)
        qc.delay(t, 0, unit="s")
        rho = _aer_dm(qc, dev)
        assert rho[1, 1].real == pytest.approx(np.exp(-t / T1), abs=1e-9)


def test_hahn_echo_with_pure_dephasing_matches_closed_form():
    dev = DeviceNoise({0: QubitNoise(1.0, T2)}, relax_during_gates=False)  # T1 >> T2: ~pure dephasing
    for t in (0.2 * T2, T2, 2 * T2):
        qc = QuantumCircuit(1)
        qc.sx(0)
        qc.delay(t / 2, 0, unit="s")
        qc.x(0)
        qc.delay(t / 2, 0, unit="s")
        qc.sx(0)
        p0 = _aer_dm(qc, dev)[0, 0].real
        assert p0 == pytest.approx(0.5 + 0.5 * np.exp(-t / T2), abs=1e-5)


def test_thermal_relaxation_matches_independent_density_matrix():
    dev = DeviceNoise({0: QubitNoise(T1, T2)}, relax_during_gates=False)
    t = 0.7 * T1
    qc = QuantumCircuit(1)
    qc.sx(0)
    qc.delay(t / 2, 0, unit="s")
    qc.x(0)
    qc.delay(t / 2, 0, unit="s")
    qc.sx(0)
    rho_aer = _aer_dm(qc, dev)
    rho = np.array([[1, 0], [0, 0]], complex)
    rho = SX @ rho @ SX.conj().T
    rho = apply(rho, thermal_kraus(T1, T2, t / 2))
    rho = X @ rho @ X
    rho = apply(rho, thermal_kraus(T1, T2, t / 2))
    rho = SX @ rho @ SX.conj().T
    assert np.allclose(rho_aer, rho, atol=1e-9)


def test_depolarizing_on_x_gate_closed_form_and_stim():
    lam = 0.06
    dev = DeviceNoise({0: QubitNoise(depol_1q=lam)}, relax_during_gates=False)
    qc = QuantumCircuit(1)
    qc.x(0)
    assert _aer_dm(qc, dev)[0, 0].real == pytest.approx(lam / 2, abs=1e-12)
    stim = pytest.importorskip("stim")
    c = stim.Circuit(f"X 0\nDEPOLARIZE1({3 * lam / 4}) 0\nM 0")
    flips = 1 - c.compile_sampler(seed=1).sample(400_000)[:, 0].mean()
    assert flips == pytest.approx(lam / 2, abs=4 * np.sqrt(lam / 2 / 400_000))


def test_gate_dependent_scale_applies_per_gate_name():
    dev = DeviceNoise({0: QubitNoise(depol_1q=0.02)}, gate_scale={"x": 3.0}, relax_during_gates=False)
    qx = QuantumCircuit(1)
    qx.x(0)
    qs = QuantumCircuit(1)
    qs.sx(0)
    qs.sx(0)
    assert _aer_dm(qx, dev)[0, 0].real == pytest.approx(0.03, abs=1e-12)
    # two sx with lambda=0.02 each: flip-free probability (1-l)^2 + ... closed form for Pauli-twirled channel
    p_x = 1 - (1 - 0.02) ** 2  # probability at least one depolarization event
    assert _aer_dm(qs, dev)[0, 0].real == pytest.approx(p_x / 2, abs=1e-12)


def test_asymmetric_readout_error():
    dev = readout_only({0: 0.04}, asymmetry=0.5)  # P(1|0)=0.02, P(0|1)=0.06
    zero = QuantumCircuit(1, 1)
    zero.measure(0, 0)
    one = QuantumCircuit(1, 1)
    one.x(0)
    one.measure(0, 0)
    c0, c1 = aer_run_counts([zero, one], dev, 200_000, seed=3)
    p10 = c0.get("1", 0) / 200_000
    p01 = c1.get("0", 0) / 200_000
    assert p10 == pytest.approx(0.02, abs=4 * np.sqrt(0.02 / 200_000))
    assert p01 == pytest.approx(0.06, abs=4 * np.sqrt(0.06 / 200_000))


def test_cirq_channels_match_aer_density_matrix():
    import cirq

    dev = DeviceNoise({0: QubitNoise(T1, T2, depol_1q=0.01)})
    t = 0.5 * T1
    q = cirq.LineQubit(0)
    wait = cirq.WaitGate(cirq.Duration(nanos=t * 1e9))
    circ = cirq.Circuit(cirq.X(q) ** 0.5, wait.on(q), cirq.X(q), wait.on(q), cirq.X(q) ** 0.5)
    rho_c = cirq.DensityMatrixSimulator().simulate(cirq_noisy_circuit(circ, dev)).final_density_matrix
    qc = QuantumCircuit(1)
    qc.sx(0)
    qc.delay(t, 0, unit="s")
    qc.x(0)
    qc.delay(t, 0, unit="s")
    qc.sx(0)
    rho_a = _aer_dm(qc, dev)
    # Cirq's X**0.5 differs from Qiskit's SX by a global phase only: compare density matrices
    assert np.allclose(np.asarray(rho_c), rho_a, atol=2e-6)


def test_cirq_readout_channel_is_asymmetric():
    import cirq

    dev = readout_only({0: 0.04}, asymmetry=0.5)
    q = cirq.LineQubit(0)
    one = cirq_noisy_circuit(cirq.Circuit(cirq.X(q), cirq.measure(q, key="m")), dev)
    r = cirq.DensityMatrixSimulator(seed=4).run(one, repetitions=100_000)
    assert 1 - r.measurements["m"].mean() == pytest.approx(0.06, abs=0.004)


def test_validation_rejects_unphysical_parameters():
    with pytest.raises(ValueError):
        QubitNoise(t1_s=50e-6, t2_s=120e-6)
    with pytest.raises(ValueError):
        QubitNoise(p_read1_given0=1.2)
    with pytest.raises(ValueError):
        QubitNoise(t1_s=50e-6)


def test_schedules():
    rng = np.random.default_rng(0)
    x = ou_log_process(0.02, 0.2, 5.0, 20_000, rng)[0]
    assert np.std(np.log(x / 0.02)) == pytest.approx(0.2, rel=0.1)
    lag1 = np.corrcoef(np.log(x[:-1]), np.log(x[1:]))[0, 1]
    assert lag1 == pytest.approx(np.exp(-1 / 5), abs=0.03)
    two = ou_log_process(0.02, 0.2, 5.0, 20_000, rng, n_series=2, rho=0.6)
    assert np.corrcoef(np.log(two[0]), np.log(two[1]))[0, 1] == pytest.approx(0.6, abs=0.06)
    tg = telegraph(50e-6, 100e-6, 0.1, 10_000, rng)
    assert set(np.unique(tg)) == {50e-6, 100e-6}
    assert np.mean(tg[1:] != tg[:-1]) == pytest.approx(0.1, abs=0.015)
    m = missing_mask(10_000, 0.1, rng, keep_first=5)
    assert not m[:5].any() and m.mean() == pytest.approx(0.1, abs=0.01)
    from datetime import timedelta

    ts = irregular_timestamps(500, timedelta(minutes=10), 0.5, rng)
    gaps = np.diff([t.timestamp() for t in ts])
    assert np.all(gaps > 0) and np.mean(gaps) == pytest.approx(600, rel=0.1)


def test_two_qubit_gate_relaxation_without_depolarizing_matches_cirq():
    """Regression: with depol_2q = 0, Aer must still apply relaxation during cx
    (found by the exact cross-framework check of Experiment F's circuits)."""
    import cirq
    from qiskit_aer import AerSimulator

    dev = DeviceNoise({0: QubitNoise(20e-6, 15e-6), 1: QubitNoise(20e-6, 15e-6)}, depol_2q=0.0)
    qc = QuantumCircuit(2)
    qc.x(0)
    for _ in range(10):
        qc.cx(0, 1)
    qc.save_density_matrix()
    rho_a = np.asarray(
        AerSimulator(method="density_matrix", noise_model=aer_noise_model(dev))
        .run(qc)
        .result()
        .data()["density_matrix"]
    )
    q0, q1 = cirq.LineQubit.range(2)
    cc = cirq.Circuit([cirq.X(q0)] + [cirq.CNOT(q0, q1)] * 10)
    rho_c = (
        cirq.DensityMatrixSimulator().simulate(cirq_noisy_circuit(cc, dev), qubit_order=[q0, q1]).final_density_matrix
    )
    # Aer little-endian (q1 q0) vs Cirq big-endian (q0 q1): compare populations of q0 = 1
    pa = np.real(np.diag(rho_a))
    pc = np.real(np.diag(np.asarray(rho_c)))
    assert pa[1] + pa[3] == pytest.approx(pc[2] + pc[3], abs=1e-6)
    assert pa[1] + pa[3] < 0.95  # relaxation during the 10 cx gates is visible
