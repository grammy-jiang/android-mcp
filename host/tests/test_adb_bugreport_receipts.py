"""H5.a durable private sanitized bugreport receipts and rollback tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_adb_bugreport_artifacts import ART_OWNER, RAW, builder, collect
from test_avd_provisioning import OWNER

import android_mcp_host.synthetic_bugreport as module
from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.private_artifact_support import ArtifactStoreError


def test_private_success_is_idempotent_and_expiry_never_collects_again(
    tmp_path: Path,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    now = [500.0]
    store._clock = lambda: now[0]
    try:
        first = collect(worker, handle, lid)
        assert first["status"] == "ok"
        again = collect(worker, handle, lid)
        assert again == first
        assert len(calls) == 1
        conflict = collect(worker, handle, lid, request="other-request")
        assert conflict["status"] == "blocked"
        assert conflict["errors"][0]["code"] == "IDEMPOTENCY_CONFLICT"
        assert len(calls) == 1
        now[0] += 121
        assert store.public_metadata(ART_OWNER, first["artifact_handle"])["status"] == "not_found"
        expired = collect(worker, handle, lid)
        assert expired["status"] == "uncertain"
        assert expired["errors"][0]["code"] == "ARTIFACT_EXPIRED"
        assert len(calls) == 1
        store.cleanup()
        assert store.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, first["job_id"])["job"]["state"] == "succeeded"
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "changed",
    [
        {"purpose": "other-report"},
        {"job_id": "job_" + "x" * 32},
        {"avd_handle": "mcpavd_" + "y" * 32},
        {"lifecycle_job_id": "job_" + "z" * 32},
        {"synthetic_fixture_only": False},
        {"sanitized_only": False},
        {"redacted_lines": -1},
        {"redacted_lines": 129},
        {"redacted_lines": True},
        {"retention_seconds": 0},
        {"retention_seconds": 301},
        {"retention_seconds": 3.4},
        {"artifact_handle": "art_" + "x" * 32},
        {"sha256": "0" * 64},
        {"size_bytes": 1},
    ],
)
def test_tampered_private_receipt_never_replays_as_trusted_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed: dict[str, Any],
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    first = collect(worker, handle, lid)
    assert first["status"] == "ok"
    original = store.read

    def forged(owner: str, item: str) -> bytes:
        raw = original(owner, item)
        if item == first["receipt_handle"]:
            record = json.loads(raw)
            record.update(changed)
            return json.dumps(record).encode("utf-8")
        return raw

    monkeypatch.setattr(store, "read", forged)
    try:
        rejected = collect(worker, handle, lid)
        assert rejected["status"] == "uncertain"
        assert rejected["errors"][0]["code"] == "ARTIFACT_EXPIRED"
        assert rejected["artifact_handle"] is None
        assert len(calls) == 1
    finally:
        live.shutdown()


@pytest.mark.parametrize("bad", [b"x", b"[]", b"null", b"{}", b"\xff"])
def test_corrupted_private_JSON_receipt_cannot_authorize_bugreport_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad: bytes,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    first = collect(worker, handle, lid)
    real = store.read
    monkeypatch.setattr(
        store,
        "read",
        lambda owner, item: bad if item == first["receipt_handle"] else real(owner, item),
    )
    try:
        response = collect(worker, handle, lid)
        assert response["status"] == "uncertain"
        assert response["errors"][0]["code"] == "ARTIFACT_EXPIRED"
        assert len(calls) == 1
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "content",
    [b"ACCOUNT=user@example.com\n", RAW, b"untrusted ZIP", b""],
)
def test_private_archive_changed_after_success_never_replays_as_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    content: bytes,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    first = collect(worker, handle, lid)
    real = store.read
    monkeypatch.setattr(
        store,
        "read",
        lambda owner, item: content if item == first["artifact_handle"] else real(owner, item),
    )
    try:
        denied = collect(worker, handle, lid)
        assert denied["status"] == "uncertain"
        assert denied["errors"][0]["code"] == "ARTIFACT_EXPIRED"
        assert len(calls) == 1
    finally:
        live.shutdown()


@pytest.mark.parametrize("broken", ["list", "read", "metadata"])
def test_private_store_outage_replay_reports_uncertain_not_private_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    broken: str,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    assert collect(worker, handle, lid)["status"] == "ok"

    def offline(*args: Any, **kwargs: Any) -> Any:
        raise ArtifactStoreError("PRIVATE-CREDENTIAL-ROOT")

    name = {"list": "list_metadata", "read": "read", "metadata": "public_metadata"}[broken]
    monkeypatch.setattr(store, name, offline)
    try:
        reply = collect(worker, handle, lid)
        assert reply["status"] == "uncertain"
        assert reply["errors"][0]["code"] == "ARTIFACT_EXPIRED"
        assert "PRIVATE-CREDENTIAL" not in json.dumps(reply)
        assert len(calls) == 1
    finally:
        live.shutdown()


def test_unrelated_private_JSON_objects_skipped_before_real_receipt(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    store.put(ART_OWNER, b'{"irrelevant":"other"}', mime_type="application/json")
    try:
        first = collect(worker, handle, lid)
        assert first["status"] == "ok"
        assert collect(worker, handle, lid) == first
        assert len(store.list_metadata(ART_OWNER)) == 3
        assert len(calls) == 1
    finally:
        live.shutdown()


def test_failed_durable_job_state_never_produces_private_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    assert collect(worker, handle, lid)["status"] == "ok"
    real = jobs.lookup_request

    def failed(*args: Any, **kwargs: Any) -> Any:
        result = real(*args, **kwargs)
        assert result is not None
        return {**result, "state": "failed"}

    monkeypatch.setattr(jobs, "lookup_request", failed)
    try:
        result = collect(worker, handle, lid)
        assert result["status"] == "failed"
        assert result["errors"][0]["code"] == "BAD_ARCHIVE"
        assert len(calls) == 1
    finally:
        live.shutdown()


def test_owner_scope_rejects_missing_sanitized_artifact_after_revocation(
    tmp_path: Path,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    first = collect(worker, handle, lid)
    store.revoke(ART_OWNER, first["artifact_handle"])
    try:
        denied = collect(worker, handle, lid)
        assert denied["status"] == "uncertain"
        assert denied["errors"][0]["code"] == "ARTIFACT_EXPIRED"
        assert (
            store.public_metadata("foreign-owner", first["receipt_handle"])["status"] == "not_found"
        )
        assert len(calls) == 1
    finally:
        live.shutdown()


def test_failed_second_private_write_revokes_first_sanitized_ZIP(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    actual = store.put
    count = [0]

    def partial(owner: str, data: bytes, **kwargs: Any) -> dict[str, Any]:
        count[0] += 1
        if count[0] == 2:
            raise ArtifactStoreError("QUOTA_EXCEEDED")
        return actual(owner, data, **kwargs)

    monkeypatch.setattr(store, "put", partial)
    try:
        failed = collect(worker, handle, lid)
        assert failed["status"] == "uncertain"
        assert failed["errors"][0]["code"] == "RUNNER_FAILED"
        assert count == [2]
        assert store.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, failed["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_failed_durable_success_commit_revokes_ZIP_and_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)

    def unavailable(*args: Any, **kwargs: Any) -> Any:
        raise JobStoreError("STORAGE_FAILURE")

    monkeypatch.setattr(jobs, "complete", unavailable)
    try:
        failed = collect(worker, handle, lid)
        assert failed["status"] == "uncertain"
        assert failed["errors"][0]["code"] == "RUNNER_FAILED"
        assert store.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, failed["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_failed_revoke_does_not_skip_durable_uncertain_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    real = store.put
    tries = [0]

    def partial(owner: str, payload: bytes, **kwargs: Any) -> dict[str, Any]:
        tries[0] += 1
        if tries[0] == 2:
            raise ArtifactStoreError("PRIVATE-FILE-FULL")
        return real(owner, payload, **kwargs)

    def unrecoverable(*args: Any) -> None:
        raise ArtifactStoreError("PRIVATE-REVOKE-FAILED")

    monkeypatch.setattr(store, "put", partial)
    monkeypatch.setattr(store, "revoke", unrecoverable)
    try:
        result = collect(worker, handle, lid)
        assert result["status"] == "uncertain"
        assert "PRIVATE-" not in json.dumps(result)
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_approval_expiration_after_private_writes_discards_all_receipts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    approve = worker._approved
    invokes = [0]

    def expired(*args: Any) -> bool:
        invokes[0] += 1
        return invokes[0] < 3 and approve(*args)

    monkeypatch.setattr(worker, "_approved", expired)
    try:
        outcome = collect(worker, handle, lid)
        assert outcome["status"] == "uncertain"
        assert outcome["errors"][0]["code"] == "CONSENT_REQUIRED"
        assert invokes == [3]
        assert store.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


def test_verified_lifecycle_lost_after_private_writes_discards_receipts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    original = module.verified_fake_target
    invokes = [0]

    def disconnect(*args: Any) -> bool:
        invokes[0] += 1
        return invokes[0] < 3 and original(*args)

    monkeypatch.setattr(module, "verified_fake_target", disconnect)
    try:
        response = collect(worker, handle, lid)
        assert response["status"] == "uncertain"
        assert response["errors"][0]["code"] == "UNVERIFIED_TARGET"
        assert invokes == [3]
        assert store.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()
