"""H4.d hostile source metadata, transport failure and narrow approval tests."""

from __future__ import annotations

import hashlib
import math
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_adb_file_pull_policy import (
    ART_OWNER,
    DIGEST,
    FILE,
    MIME,
    PACKAGE,
    REMOTE,
    builder,
    pull,
)
from test_avd_provisioning import NAME, OWNER

import android_mcp_host.synthetic_file_pull as module
from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.synthetic_file_pull import (
    FilePullApproval,
    FilePullFrame,
    FilePullService,
)


def default_frame(name: str, handle: str, lid: str) -> FilePullFrame:
    return FilePullFrame(FILE, name, handle, lid, PACKAGE, REMOTE, MIME, DIGEST, True, False, True)


@pytest.mark.parametrize(
    "change",
    [
        {"avd_name": "untrusted"},
        {"avd_handle": "mcpavd_" + "x" * 32},
        {"lifecycle_job_id": "job_" + "z" * 32},
        {"package_id": "org.example.synthetic.foreign"},
        {"remote_path": "/data/local/tmp/secret.bin"},
        {"mime_type": "application/octet-stream"},
        {"synthetic": False},
        {"synthetic": "true"},
        {"regular": "true"},
        {"partial": 0},
        {"symlink": "false"},
    ],
)
def test_wrong_frame_identity_type_and_mime_cannot_commit(
    tmp_path: Path,
    change: dict[str, Any],
) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)
    worker._fixture = lambda *args: replace(default_frame(NAME, handle, lid), **change)
    try:
        reply = pull(worker, handle, lid)
        assert reply["status"] == "failed"
        assert reply["errors"][0]["code"] == "BAD_FRAME"
        assert reply["artifact_handle"] is None
        assert store.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, reply["job_id"])["job"]["state"] == "failed"
        assert pull(worker, handle, lid)["status"] == "failed"
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "change",
    [
        {"regular": False},
        {"symlink": True},
        {"regular": False, "symlink": True},
    ],
)
def test_source_is_symlink_or_nonregular_even_when_bytes_match_denied(
    tmp_path: Path,
    change: dict[str, Any],
) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)
    worker._fixture = lambda *args: replace(default_frame(NAME, handle, lid), **change)
    try:
        result = pull(worker, handle, lid)
        assert result["status"] == "failed"
        assert result["errors"][0]["code"] == "SYMLINK_DENIED"
        assert store.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"partial": True}, "PARTIAL_TRANSFER"),
        ({"declared_sha256": "f" * 64}, "CHECKSUM_MISMATCH"),
        ({"payload": b"other-payload"}, "CHECKSUM_MISMATCH"),
        ({"payload": b""}, "TRANSFER_TOO_LARGE"),
        ({"payload": b"x" * 262145}, "TRANSFER_TOO_LARGE"),
        ({"payload": "text instead of bytes"}, "TRANSFER_TOO_LARGE"),
    ],
)
def test_partial_checksum_mismatch_and_oversized_file_denied(
    tmp_path: Path,
    change: dict[str, Any],
    expected: str,
) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)
    worker._fixture = lambda *args: replace(default_frame(NAME, handle, lid), **change)
    try:
        outcome = pull(worker, handle, lid)
        assert outcome["status"] == "failed"
        assert outcome["errors"][0]["code"] == expected
        assert store.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "grant_change",
    [
        {"owner": "foreign-owner"},
        {"avd_handle": "mcpavd_" + "x" * 32},
        {"lifecycle_job_id": "job_" + "z" * 32},
        {"package_id": "org.example.synthetic.other"},
        {"remote_path": "/sdcard/Android/data/other/files/mcp-export/secret.txt"},
        {"expected_sha256": "0" * 64},
        {"purpose": "different-purpose"},
        {"valid_until_epoch": 0},
        {"valid_until_epoch": 10**20},
        {"valid_until_epoch": math.nan},
        {"valid_until_epoch": math.inf},
        {"valid_until_epoch": "invalid"},
        {"valid_until_epoch": True},
        {"ttl_s": 0},
        {"ttl_s": 301},
        {"ttl_s": math.nan},
        {"ttl_s": math.inf},
        {"ttl_s": "invalid"},
        {"ttl_s": True},
    ],
)
def test_unapproved_private_export_never_invokes_backend(
    tmp_path: Path,
    grant_change: dict[str, Any],
) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)
    fields: dict[str, Any] = {
        "owner": OWNER,
        "avd_handle": handle,
        "lifecycle_job_id": lid,
        "package_id": PACKAGE,
        "remote_path": REMOTE,
        "expected_sha256": DIGEST,
        "purpose": "synthetic-app-export",
        "valid_until_epoch": time.time() + 120,
        "ttl_s": 120,
    }
    fields.update(grant_change)
    worker._approval = FilePullApproval(**fields)
    worker._fixture = lambda *args: pytest.fail("Unapproved export backend executed")
    try:
        denied = pull(worker, handle, lid)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "CONSENT_REQUIRED"
        assert store.list_metadata(ART_OWNER) == []
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


def test_constructor_fail_closed_for_cross_owner_and_non_synthetic_app(
    tmp_path: Path,
) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)
    try:
        for owner, artifact_owner, package in (
            ("wrong-owner", ART_OWNER, PACKAGE),
            (OWNER, "invalid/path", PACKAGE),
            (OWNER, ART_OWNER, "com.example.normal"),
            (OWNER, ART_OWNER, "org.example.synthetic.bad/escape"),
        ):
            with pytest.raises(ValueError):
                FilePullService(
                    live.provisioner,
                    live,
                    jobs,
                    store,
                    owner=owner,
                    artifact_owner=artifact_owner,
                    package_id=package,
                )
    finally:
        live.shutdown()


def test_inert_operator_production_mode_has_no_real_reader(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)
    worker._fixture = None
    try:
        denied = pull(worker, handle, lid)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "EXECUTION_DISABLED"
        assert store.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


def test_lifecycle_disconnected_before_backend_is_denied(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)
    live.shutdown()
    denied = pull(worker, handle, lid)
    assert denied["status"] == "blocked"
    assert denied["errors"][0]["code"] == "UNVERIFIED_TARGET"
    assert store.list_metadata(ART_OWNER) == []


def test_lifecycle_disconnected_during_backend_is_uncertain(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)

    def disappear(*args: Any) -> FilePullFrame:
        live.shutdown()
        return default_frame(NAME, handle, lid)

    worker._fixture = disappear
    reply = pull(worker, handle, lid)
    assert reply["status"] == "uncertain"
    assert reply["errors"][0]["code"] == "UNVERIFIED_TARGET"
    assert store.list_metadata(ART_OWNER) == []
    assert jobs.status(OWNER, reply["job_id"])["job"]["state"] == "uncertain"


def test_expiring_grant_during_export_denies_result(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)
    now = [500.0]
    worker._clock = lambda: now[0]
    worker._approval = FilePullApproval(
        OWNER,
        handle,
        lid,
        PACKAGE,
        REMOTE,
        DIGEST,
        "synthetic-app-export",
        510.0,
        120,
    )

    def expire(*args: Any) -> FilePullFrame:
        now[0] = 511
        return default_frame(NAME, handle, lid)

    worker._fixture = expire
    try:
        result = pull(worker, handle, lid)
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "CONSENT_REQUIRED"
        assert store.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "error",
    [
        OSError("PRIVATE-AUTH"),
        RuntimeError("PRIVATE-STATE"),
        ValueError("PRIVATE-INPUT"),
        TypeError("PRIVATE-TYPE"),
        subprocess.CalledProcessError(1, "fake-command"),
        subprocess.TimeoutExpired(["synthetic-reader"], 0.1),
    ],
)
def test_reader_errors_never_leak_private_content(
    tmp_path: Path,
    error: BaseException,
) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)

    def failed(*args: Any) -> FilePullFrame:
        raise error

    worker._fixture = failed
    try:
        output = pull(worker, handle, lid)
        assert output["status"] == "uncertain"
        assert output["errors"][0]["code"] == (
            "TIMEOUT" if isinstance(error, subprocess.TimeoutExpired) else "RUNNER_FAILED"
        )
        assert "PRIVATE-" not in str(output)
        assert store.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, output["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_inert_source_lock_and_job_store_fail_before_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)
    worker._fixture = lambda *args: pytest.fail("Invalid fixture operation executed")
    try:
        with monkeypatch.context() as patch:
            patch.setattr(module, "claim_fixture_lock", lambda *args: None)
            assert pull(worker, handle, lid)["errors"][0]["code"] == "RECOVERY_REQUIRED"
        with monkeypatch.context() as patch:

            def bad_lock(*args: Any) -> Any:
                raise OSError("PRIVATE-HOST-LOCK")

            patch.setattr(module, "claim_fixture_lock", bad_lock)
            assert pull(worker, handle, lid)["errors"][0]["code"] == "JOB_UNAVAILABLE"
        with monkeypatch.context() as patch:

            def bad_store(*args: Any) -> Any:
                raise JobStoreError("STORAGE_FAILURE")

            patch.setattr(jobs, "lookup_request", bad_store)
            assert pull(worker, handle, lid)["errors"][0]["code"] == "JOB_UNAVAILABLE"
        assert store.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


def test_other_running_operation_blocks_concurrent_private_export(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)
    existing = jobs.prepare(
        OWNER,
        "unrelated-work",
        hashlib.sha256(b"other").hexdigest(),
        identity=handle,
        authorized=True,
    )
    try:
        denied = pull(worker, handle, lid)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "RECOVERY_REQUIRED"
        assert len(jobs.list_status(OWNER)) == 2
        assert store.list_metadata(ART_OWNER) == []
        assert existing["job_id"] != lid
    finally:
        live.shutdown()
