"""H4.e adversarial HMAC consent, private artifact and frame integrity tests."""

from __future__ import annotations

import hashlib
import math
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_adb_file_push_policy import (
    ART_OWNER,
    DATA,
    DEST,
    KEY,
    PACKAGE,
    SHA,
    builder,
    run_push,
)
from test_avd_provisioning import NAME, OWNER

import android_mcp_host.synthetic_file_push as module
from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.synthetic_file_push import FilePushService, PushFrame


def frame_for(handle: str, lid: str, *, amount: int = len(DATA)) -> PushFrame:
    return PushFrame(NAME, handle, lid, PACKAGE, DEST, SHA, amount, True, True, False, False, True)


@pytest.mark.parametrize(
    "overrides",
    [
        {"owner": "different-owner"},
        {"avd_handle": "mcpavd_" + "x" * 32},
        {"lifecycle_job_id": "job_" + "y" * 32},
        {"package_id": "org.example.synthetic.foreign"},
        {"destination_path": "/system/evil.bin"},
        {"artifact_handle": "art_" + "x" * 32},
        {"artifact_sha256": "1" * 64},
        {"mime_type": "text/plain"},
        {"purpose": "different-purpose"},
        {"signature": "0" * 64},
        {"signature": "not-a-signature"},
        {"signature": None},
        {"valid_until_epoch": 0},
        {"valid_until_epoch": True},
        {"valid_until_epoch": time.time() + 500},
        {"valid_until_epoch": math.nan},
        {"valid_until_epoch": math.inf},
        {"valid_until_epoch": "invalid"},
    ],
)
def test_t_h4e_02_invalid_or_expired_hmac_grant_never_invokes_writer(
    tmp_path: Path,
    overrides: dict[str, Any],
) -> None:
    worker, live, jobs, store, handle, lid, token, written = builder(tmp_path)
    worker._writer = lambda *args: pytest.fail("Untrusted import reached fixture")
    assert worker._approval is not None
    worker._approval = replace(worker._approval, **overrides)
    try:
        denied = run_push(worker, handle, lid, token)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "MUTATION_DISABLED"
        assert len(jobs.list_status(OWNER)) == 1
        assert len(store.list_metadata(ART_OWNER)) == 1
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        (None, "MUTATION_DISABLED"),
        (b"incorrect-length", "MUTATION_DISABLED"),
    ],
)
def test_injected_bad_hmac_key_denied_even_if_approval_is_present(
    tmp_path: Path,
    key: Any,
    expected: str,
) -> None:
    worker, live, _, store, handle, lid, token, _ = builder(tmp_path)
    worker._key = key
    worker._writer = lambda *args: pytest.fail("Private fixture must not run")
    try:
        assert run_push(worker, handle, lid, token)["errors"][0]["code"] == expected
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "change",
    [
        {"avd_name": "foreign"},
        {"avd_handle": "mcpavd_" + "x" * 32},
        {"lifecycle_job_id": "job_" + "y" * 32},
        {"package_id": "org.example.synthetic.other"},
        {"destination_path": "/sdcard/Download/fake.bin"},
        {"artifact_sha256": "e" * 64},
        {"bytes_written": 1.0},
        {"bytes_written": True},
        {"complete": "true"},
        {"atomic": "true"},
        {"overwrote": 0},
        {"symlink": None},
        {"synthetic": False},
        {"synthetic": "true"},
    ],
)
def test_t_h4e_03_spoofed_writer_identity_and_security_types_cannot_commit(
    tmp_path: Path,
    change: dict[str, Any],
) -> None:
    worker, live, jobs, store, handle, lid, token, _ = builder(tmp_path)
    worker._writer = lambda *args: replace(frame_for(handle, lid), **change)
    try:
        outcome = run_push(worker, handle, lid, token)
        assert outcome["status"] == "uncertain"
        assert outcome["errors"][0]["code"] == "BAD_FRAME"
        assert outcome["report_handle"] is None
        assert outcome["real_push_enabled"] is False
        assert len(store.list_metadata(ART_OWNER)) == 1
        assert jobs.status(OWNER, outcome["job_id"])["job"]["state"] == "uncertain"
        again = run_push(worker, handle, lid, token)
        assert again["job_id"] == outcome["job_id"]
        assert again["status"] == "uncertain"
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"overwrote": True}, "OVERWRITE_DENIED"),
        ({"symlink": True}, "OVERWRITE_DENIED"),
        ({"overwrote": True, "symlink": True}, "OVERWRITE_DENIED"),
        ({"complete": False}, "PARTIAL_WRITE"),
        ({"atomic": False}, "PARTIAL_WRITE"),
        ({"bytes_written": len(DATA) - 1}, "CHECKSUM_MISMATCH"),
        ({"bytes_written": len(DATA) + 1}, "CHECKSUM_MISMATCH"),
    ],
)
def test_t_h4e_05_incomplete_or_overwriting_fixture_is_uncertain_not_success(
    tmp_path: Path,
    change: dict[str, Any],
    error: str,
) -> None:
    worker, live, jobs, store, handle, lid, token, _ = builder(tmp_path)
    worker._writer = lambda *args: replace(frame_for(handle, lid), **change)
    try:
        outcome = run_push(worker, handle, lid, token)
        assert outcome["status"] == "uncertain"
        assert outcome["errors"][0]["code"] == error
        assert outcome["report_handle"] is None
        assert jobs.status(OWNER, outcome["job_id"])["job"]["state"] == "uncertain"
        assert len(store.list_metadata(ART_OWNER)) == 1
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "alter",
    [
        {"sha256": "0" * 64},
        {"mime_type": "application/json"},
        {"size_bytes": len(DATA) + 1},
        {"size_bytes": 262145},
    ],
)
def test_t_h4e_04_private_artifact_metadata_spoofing_denied_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    alter: dict[str, Any],
) -> None:
    worker, live, jobs, store, handle, lid, token, _ = builder(tmp_path)
    original = store.public_metadata

    def forged(owner: str, item: str) -> dict[str, Any]:
        data = original(owner, item)
        if item == token:
            data["artifact"].update(alter)
        return data

    monkeypatch.setattr(store, "public_metadata", forged)
    worker._writer = lambda *args: pytest.fail("Invalid private artifact reached writer")
    try:
        result = run_push(worker, handle, lid, token)
        assert result["status"] == "blocked"
        assert result["errors"][0]["code"] == "BAD_ARTIFACT"
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "contents",
    [
        b"attacker-controlled data",
        b"",
        b"another longer synthetic document",
    ],
)
def test_t_h4e_04_private_bytes_tampering_denied_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    contents: bytes,
) -> None:
    worker, live, jobs, store, handle, lid, token, _ = builder(tmp_path)
    original = store.read
    monkeypatch.setattr(
        store, "read", lambda owner, item: contents if item == token else original(owner, item)
    )
    worker._writer = lambda *args: pytest.fail("Tampered bytes reached writer")
    try:
        denied = run_push(worker, handle, lid, token)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "BAD_ARTIFACT"
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


def test_revoked_private_artifact_cannot_be_imported(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, token, _ = builder(tmp_path)
    store.revoke(ART_OWNER, token)
    worker._writer = lambda *args: pytest.fail("Revoked private source executed")
    try:
        denied = run_push(worker, handle, lid, token)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "BAD_ARTIFACT"
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "exception",
    [
        OSError("SECRET-PATH"),
        RuntimeError("SECRET-STORE"),
        ValueError("SECRET-INPUT"),
        TypeError("SECRET-PROTOCOL"),
        subprocess.CalledProcessError(1, ["fixture-only"], output=b"SECRET-PAYLOAD"),
        subprocess.TimeoutExpired(["fixture-only"], 0.001),
    ],
)
def test_t_h4e_05_fixture_runner_error_no_secret_and_no_trusted_receipt(
    tmp_path: Path,
    exception: Exception,
) -> None:
    worker, live, jobs, store, handle, lid, token, _ = builder(tmp_path)

    def fail(*args: Any) -> PushFrame:
        raise exception

    worker._writer = fail
    try:
        denied = run_push(worker, handle, lid, token)
        assert denied["status"] == "uncertain"
        code = "TIMEOUT" if isinstance(exception, subprocess.TimeoutExpired) else "RUNNER_FAILED"
        assert denied["errors"][0]["code"] == code
        assert "SECRET-" not in str(denied)
        assert denied["report_handle"] is None
        assert len(store.list_metadata(ART_OWNER)) == 1
        assert jobs.status(OWNER, denied["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_constructor_rejects_owner_package_and_bad_fixture_key(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, token, _ = builder(tmp_path)
    try:
        for owner, art_owner, package, key in (
            ("foreign", ART_OWNER, PACKAGE, KEY),
            (OWNER, "bad/owner", PACKAGE, KEY),
            (OWNER, ART_OWNER, "org.example.real", KEY),
            (OWNER, ART_OWNER, PACKAGE, b"short"),
            (OWNER, ART_OWNER, PACKAGE, True),
        ):
            with pytest.raises(ValueError):
                FilePushService(
                    live.provisioner,
                    live,
                    jobs,
                    store,
                    owner=owner,
                    artifact_owner=art_owner,
                    package_id=package,
                    fixture_hmac_key=key,
                )
    finally:
        live.shutdown()


def test_clock_failure_never_enables_grant(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, token, _ = builder(tmp_path)
    worker._clock = lambda: (_ for _ in ()).throw(ValueError("SECRET-TIME"))
    worker._writer = lambda *args: pytest.fail("Clock failure must be denied")
    try:
        denied = run_push(worker, handle, lid, token)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "MUTATION_DISABLED"
    finally:
        live.shutdown()


def test_verified_synthetic_lifecycle_stops_before_write(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, token, _ = builder(tmp_path)
    live.shutdown()
    worker._writer = lambda *args: pytest.fail("Disconnected fixture cannot write")
    denied = run_push(worker, handle, lid, token)
    assert denied["status"] == "blocked"
    assert denied["errors"][0]["code"] == "UNVERIFIED_TARGET"


def test_verified_synthetic_lifecycle_lost_during_write(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, token, _ = builder(tmp_path)

    def lost(*args: Any) -> PushFrame:
        live.shutdown()
        return frame_for(handle, lid)

    worker._writer = lost
    result = run_push(worker, handle, lid, token)
    assert result["status"] == "uncertain"
    assert result["errors"][0]["code"] == "UNVERIFIED_TARGET"
    assert result["report_handle"] is None
    assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"


def test_grant_expires_during_writer_and_receipt_denied(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, token, _ = builder(tmp_path)
    now = [1000.0]
    worker._clock = lambda: now[0]
    worker._approval = replace(worker._approval, valid_until_epoch=1010.0)

    def expires(*args: Any) -> PushFrame:
        now[0] = 1011.0
        return frame_for(handle, lid)

    worker._writer = expires
    try:
        failed = run_push(worker, handle, lid, token)
        assert failed["status"] == "uncertain"
        assert failed["errors"][0]["code"] == "CONSENT_REQUIRED"
        assert failed["report_handle"] is None
        assert jobs.status(OWNER, failed["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_other_active_job_blocks_mutation_before_writer(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, token, _ = builder(tmp_path)
    other = jobs.prepare(
        OWNER,
        "other-active-job",
        hashlib.sha256(b"unrelated").hexdigest(),
        identity=handle,
        authorized=True,
    )
    worker._writer = lambda *args: pytest.fail("Concurrent fixture write forbidden")
    try:
        blocked = run_push(worker, handle, lid, token)
        assert blocked["status"] == "blocked"
        assert blocked["errors"][0]["code"] == "RECOVERY_REQUIRED"
        assert other["job_id"] not in worker._active
        assert len(jobs.list_status(OWNER)) == 2
    finally:
        live.shutdown()


def test_invalid_lock_and_job_store_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker, live, jobs, store, handle, lid, token, _ = builder(tmp_path)
    worker._writer = lambda *args: pytest.fail("Not allowed to enter writer")
    try:
        with monkeypatch.context() as patch:
            patch.setattr(module, "claim_fixture_lock", lambda *args: None)
            assert run_push(worker, handle, lid, token)["errors"][0]["code"] == "RECOVERY_REQUIRED"
        with monkeypatch.context() as patch:

            def error(*args: Any) -> Any:
                raise OSError("PRIVATE-LOCK")

            patch.setattr(module, "claim_fixture_lock", error)
            assert run_push(worker, handle, lid, token)["errors"][0]["code"] == "JOB_UNAVAILABLE"
        with monkeypatch.context() as patch:

            def error(*args: Any, **kwargs: Any) -> Any:
                raise JobStoreError("STORAGE_FAILURE")

            patch.setattr(jobs, "lookup_request", error)
            assert run_push(worker, handle, lid, token)["errors"][0]["code"] == "JOB_UNAVAILABLE"
    finally:
        live.shutdown()
