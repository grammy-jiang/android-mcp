#!/usr/bin/env python3
"""One-time owner-verified test-only V3 AVD HMAC proof provisioning.

No arbitrary serial or custom AVD. Attests only four already-created,
exclusively owned disposable test emulators, after actual QEMU+API+boot
preflight under OS file lock. Never enrolls physical Android devices.
No user data, no expensive hosted Actions, no production Host trust keys.
"""

from __future__ import annotations

import argparse
import json
import secrets
import time
from pathlib import Path

from scripts.native_v3_owned_avd import (
    _owner_and_device,
    atomic_create_owner_proof,
    create_owner_attestation,
    exclusive_avd_lock,
    read_lab_owner_secret,
    verify_owner_attestation,
)


def provision(api: int) -> dict[str, object]:
    owner, _, avd = _owner_and_device(api, require_attestation=False)
    with exclusive_avd_lock(avd / "v3-test-exclusive.lock"):
        # Recheck owner/process/boot identity after exclusive lock.
        owner, observed, _ = _owner_and_device(api, require_attestation=False)
        key_path = Path.home() / ".android/avd/v3-attestation-key.v1"
        key = read_lab_owner_secret(key_path, create=True)
        issued = int(time.time())
        nonce = secrets.token_hex(16)
        proof = create_owner_attestation(
            owner, observed, observed["process_start"], key, nonce, issued
        )
        target = avd / "v3-owner-proof.v1.json"
        atomic_create_owner_proof(target, proof)
        verify_owner_attestation(
            proof, owner, observed, observed["process_start"], key, issued
        )
        return {
            "avd": owner["avd"],
            "api": api,
            "disposable_owned_emulator": True,
            "nonce_sha256": __import__("hashlib").sha256(nonce.encode()).hexdigest(),
            "lease_proof_status": "BOUND_TEST_ONLY",
            "valid_for_at_most_seconds": 86400,
            "no_production_host_identity": True,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api", type=int, action="append", choices=(30, 33, 34, 36), required=True
    )
    args = parser.parse_args()
    if len(args.api) != len(set(args.api)):
        parser.error("Duplicate API cannot be provisioned twice")
    for api in args.api:
        print(json.dumps(provision(api), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
