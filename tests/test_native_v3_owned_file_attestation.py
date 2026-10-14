"""E01.e local-only owner attestation material must be 0600 and fail closed."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from scripts.native_v3_owned_avd import (
    IdentityError,
    atomic_create_owner_proof,
    exclusive_avd_lock,
    read_lab_owner_secret,
    read_owner_proof,
)


class OwnerAttestationFilesTests(unittest.TestCase):
    def test_secret_is_random_stable_and_only_owner_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            secret_file = Path(directory) / "avd-attestation.key"
            first = read_lab_owner_secret(secret_file, create=True)
            self.assertEqual(len(first), 32)
            self.assertTrue(any(byte != 0 for byte in first))
            self.assertEqual(secret_file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(read_lab_owner_secret(secret_file, create=False), first)

    def test_unprovisioned_key_cannot_silently_self_create_during_test(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "missing.key"
            with self.assertRaises(IdentityError):
                read_lab_owner_secret(target, create=False)
            self.assertFalse(target.exists())

    def test_owner_credential_symlink_or_insecure_mode_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            actual = parent / "real-secret"
            actual.write_bytes(b"1" * 32)
            os.chmod(actual, 0o600)
            symbolic = parent / "symbolic"
            symbolic.symlink_to(actual)
            with self.assertRaises(IdentityError):
                read_lab_owner_secret(symbolic, create=False)
            os.chmod(actual, 0o644)
            with self.assertRaises(IdentityError):
                read_lab_owner_secret(actual, create=False)

    def test_atomic_attestation_create_refuses_replay_or_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "proof.json"
            proof = {
                "schema": "native-v3-avd-owner-attestation.v1",
                "nonce": "a" * 32,
                "hmac_sha256": "f" * 64,
            }
            atomic_create_owner_proof(target, proof)
            self.assertEqual(read_owner_proof(target), proof)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(IdentityError):
                atomic_create_owner_proof(target, {**proof, "nonce": "b" * 32})
            self.assertEqual(read_owner_proof(target), proof)

    def test_no_lock_truncation_or_symlink_following(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            real = folder / "real.txt"
            real.write_text("DONT_CHANGE")
            target = folder / "v3-lock"
            target.symlink_to(real)
            with self.assertRaises(IdentityError), exclusive_avd_lock(target):
                pass
            self.assertEqual(real.read_text(), "DONT_CHANGE")
            target.unlink()
            with exclusive_avd_lock(target):
                self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(real.read_text(), "DONT_CHANGE")


if __name__ == "__main__":
    unittest.main()
