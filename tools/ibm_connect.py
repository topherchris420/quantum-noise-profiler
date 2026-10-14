"""Save IBM Quantum Platform credentials and check the connection (read-only).

Prompts for the API key without echoing it and for the instance CRN, saves
them as the default account with ``QiskitRuntimeService.save_account``
(~/.qiskit/qiskit-ibm.json, outside the repository), then lists the QPUs the
instance can reach and its remaining usage. It submits no jobs and uses no
QPU time.

    python tools/ibm_connect.py            # save (prompts), then check
    python tools/ibm_connect.py --check    # check the saved account only

Run it in your own terminal: the hidden prompt needs a console.
experiments/run_v03.py uses the saved default account when
QISKIT_IBM_TOKEN is not set.
"""

from __future__ import annotations

import argparse
import getpass

CHANNEL = "ibm_quantum_platform"


def save() -> None:
    from qiskit_ibm_runtime import QiskitRuntimeService

    token = getpass.getpass("IBM Quantum API key (input hidden): ").strip()
    if not token:
        raise SystemExit("no API key entered; nothing saved")
    instance = input("Instance CRN (Enter: auto-select an Open Plan instance): ").strip() or None
    if instance is not None and not instance.startswith("crn:"):
        raise SystemExit("an instance CRN starts with 'crn:'; copy it from the Instances page")
    # without a CRN, only Open Plan instances are considered, so a paid instance is never picked
    extra = {} if instance else {"plans_preference": ["open"], "region": "us-east"}
    QiskitRuntimeService.save_account(
        channel=CHANNEL, token=token, instance=instance, set_as_default=True, overwrite=True, **extra
    )
    print("saved as the default account (~/.qiskit/qiskit-ibm.json)")


def check() -> None:
    from qiskit_ibm_runtime import QiskitRuntimeService
    from qiskit_ibm_runtime.accounts import AccountNotFoundError

    try:
        service = QiskitRuntimeService()
    except AccountNotFoundError:
        raise SystemExit("no saved account: run python tools/ibm_connect.py (without --check) first") from None
    print(f"instance: {service.active_instance()}")
    backends = sorted(service.backends(simulator=False, operational=True), key=lambda b: b.name)
    print(f"{len(backends)} operational QPU(s):")
    for b in backends:
        print(f"  {b.name}: {b.num_qubits} qubits, {b.status().pending_jobs} pending jobs")
    try:
        u = service.usage()
    except Exception as exc:  # usage is informational; its absence is reported, not guessed
        print(f"usage: not reported ({type(exc).__name__}: {exc})")
        return
    used, left = u.get("usage_consumed_seconds"), u.get("usage_remaining_seconds")
    print(f"usage: {used} s consumed, {left if left is not None else 'unknown'} s remaining this cycle")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="only check the saved account")
    args = ap.parse_args(argv)
    if not args.check:
        save()
    check()


if __name__ == "__main__":
    main()
