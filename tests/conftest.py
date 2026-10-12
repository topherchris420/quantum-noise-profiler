import warnings

import pytest

warnings.filterwarnings("ignore", category=DeprecationWarning)


def readout_noise_model(p_by_qubit: dict[int, float], p1q: float = 0.0):
    """Symmetric readout error per qubit (+ optional 1q depolarizing)."""
    from qiskit_aer.noise import NoiseModel, ReadoutError, depolarizing_error

    nm = NoiseModel(basis_gates=["x", "sx", "rz", "cx", "h"])
    for q, p in p_by_qubit.items():
        nm.add_readout_error(ReadoutError([[1 - p, p], [p, 1 - p]]), [q])
    if p1q:
        nm.add_all_qubit_quantum_error(depolarizing_error(p1q, 1), ["x", "sx", "h"])
    return nm


@pytest.fixture
def aer():
    from qiskit_aer import AerSimulator

    return lambda **kw: AerSimulator(noise_model=readout_noise_model(**kw))
