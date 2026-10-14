"""H4.d private receipt, replay, expiration and rollback correctness."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from test_adb_file_pull_policy import (
    ART_OWNER,
    builder,
    pull,
)
from test_avd_provisioning import OWNER

import android_mcp_host.synthetic_file_pull as module
from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.private_artifact_support import ArtifactStoreError


def test_private_duplicate_replay_and_expiration_does_not_repeat_reader(tmp_path: Path) -> None:
    calls = [0]
    worker, live, jobs, store, handle, lid = builder(tmp_path)
    first_reader = worker._fixture
    assert first_reader is not None

    def one_shot(*args: Any) -> Any:
        calls[0] += 1
        return first_reader(*args)

    worker._fixture = one_shot
    now = [600.0]
    store._clock = lambda: now[0]
    try:
        first = pull(worker, handle, lid)
        assert first["status"] == "ok"
        again = pull(worker, handle, lid)
        assert first == again
        assert calls == [1]
        assert len(store.list_metadata(ART_OWNER)) == 2
        other = pull(worker, handle, lid, request="different-request")
        assert other["status"] == "blocked"
        assert other["errors"][0]["code"] == "IDEMPOTENCY_CONFLICT"
        now[0] += 121
        assert store.public_metadata(ART_OWNER, first["artifact_handle"])["status"] == "not_found"
        missing = pull(worker, handle, lid)
        assert missing["status"] == "uncertain"
        assert missing["errors"][0]["code"] == "ARTIFACT_EXPIRED"
        assert calls == [1]
        store.cleanup()
        assert store.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, first["job_id"])["job"]["state"] == "succeeded"
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "corrupt",
    [
        {"purpose": "arbitrary-file"},
        {"job_id": "job_" + "x" * 32},
        {"avd_handle": "mcpavd_" + "x" * 32},
        {"lifecycle_job_id": "job_" + "x" * 32},
        {"package_id": "org.example.synthetic.foreign"},
        {"source_path_sha256": "a" * 64},
        {"filename": "other.bin"},
        {"mime_type": "application/octet-stream"},
        {"sha256": "0" * 64},
        {"synthetic_fixture_only": False},
        {"artifact_handle": "art_" + "x" * 32},
    ],
)
def test_corrupted_receipt_fields_cannot_replay_private_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corrupt: dict[str, Any],
) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)
    first = pull(worker, handle, lid)
    assert first["status"] == "ok"
    original_read = store.read

    def changed(owner: str, artifact_handle: str) -> bytes:
        original = original_read(owner, artifact_handle)
        if artifact_handle != first["receipt_handle"]:
            return original
        record = json.loads(original)
        record.update(corrupt)
        return json.dumps(record).encode("utf-8")

    monkeypatch.setattr(store, "read", changed)
    try:
        denied = pull(worker, handle, lid)
        assert denied["status"] == "uncertain"
        assert denied["artifact_handle"] is None
        assert denied["errors"][0]["code"] == "ARTIFACT_EXPIRED"
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "bad",
    [
        b"x",
        b"[]",
        b"null",
        b"{}",
        b'{"purpose":null}',
        b"\xff",
    ],
)
def test_malformed_private_json_receipt_does_not_release_video(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad: bytes,
) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)
    first = pull(worker, handle, lid)
    assert first["status"] == "ok"
    real = store.read

    def tampered(owner: str, token: str) -> bytes:
        return bad if token == first["receipt_handle"] else real(owner, token)

    monkeypatch.setattr(store, "read", tampered)
    try:
        output = pull(worker, handle, lid)
        assert output["status"] == "uncertain"
        assert output["errors"][0]["code"] == "ARTIFACT_EXPIRED"
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "content",
    [
        b"changed",
        b"bad-checksum" * 1024,
        b"",
    ],
)
def test_private_file_checksum_size_corruption_replay_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    content: bytes,
) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)
    first = pull(worker, handle, lid)
    assert first["status"] == "ok"
    real = store.read

    def corrupted(owner: str, token: str) -> bytes:
        return content if token == first["artifact_handle"] else real(owner, token)

    monkeypatch.setattr(store, "read", corrupted)
    try:
        reply = pull(worker, handle, lid)
        assert reply["status"] == "uncertain"
        assert reply["errors"][0]["code"] == "ARTIFACT_EXPIRED"
    finally:
        live.shutdown()


def test_private_file_mime_spoof_detected_before_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)
    first = pull(worker, handle, lid)
    original = store.public_metadata

    def incorrect(owner: str, token: str) -> dict[str, Any]:
        meta = original(owner, token)
        if token == first["artifact_handle"]:
            meta["artifact"]["mime_type"] = "application/octet-stream"
        return meta

    monkeypatch.setattr(store, "public_metadata", incorrect)
    try:
        assert pull(worker, handle, lid)["errors"][0]["code"] == "ARTIFACT_EXPIRED"
    finally:
        live.shutdown()


@pytest.mark.parametrize("fail", ["list", "read", "metadata"])
def test_private_storage_failure_replay_is_uncertain_not_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail: str,
) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)
    first = pull(worker, handle, lid)
    assert first["status"] == "ok"

    def unavailable(*args: Any) -> Any:
        raise ArtifactStoreError("PRIVATE-SOURCE-FAILURE")

    monkeypatch.setattr(
        store,
        {"list": "list_metadata", "read": "read", "metadata": "public_metadata"}[fail],
        unavailable,
    )
    try:
        result = pull(worker, handle, lid)
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "ARTIFACT_EXPIRED"
        assert "PRIVATE-SOURCE-FAILURE" not in json.dumps(result)
    finally:
        live.shutdown()


def test_unrelated_completed_job_does_not_block_new_synthetic_file(
    tmp_path: Path,
) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)
    other = jobs.prepare(
        OWNER,
        "older-instrumentation",
        hashlib.sha256(b"old").hexdigest(),
        identity=handle,
        authorized=True,
    )
    jobs.queue(OWNER, other["job_id"], identity=handle, authorized=True)
    claimed = jobs.claim(OWNER, other["job_id"], "other-test-worker", handle, authorized=True)
    jobs.complete(
        OWNER,
        other["job_id"],
        "other-test-worker",
        claimed["generation"],
        handle,
        result_digest=hashlib.sha256(b"done").hexdigest(),
        authorized=True,
    )
    try:
        assert pull(worker, handle, lid)["status"] == "ok"
    finally:
        live.shutdown()


def test_failure_on_second_private_write_revokes_first_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)
    original = store.put
    calls = [0]

    def write(owner: str, data: bytes, **kwargs: Any) -> dict[str, Any]:
        calls[0] += 1
        if calls[0] == 2:
            raise ArtifactStoreError("RESOURCE_LIMIT")
        return original(owner, data, **kwargs)

    monkeypatch.setattr(store, "put", write)
    try:
        result = pull(worker, handle, lid)
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "RUNNER_FAILED"
        assert calls == [2]
        assert store.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_failed_durable_completion_revokes_both_handles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)

    def corrupt(*args: Any, **kwargs: Any) -> None:
        raise JobStoreError("STORAGE_FAILURE")

    monkeypatch.setattr(jobs, "complete", corrupt)
    try:
        reply = pull(worker, handle, lid)
        assert reply["status"] == "uncertain"
        assert reply["errors"][0]["code"] == "RUNNER_FAILED"
        assert store.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, reply["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_failed_rollback_revoke_never_skips_job_uncertainty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)
    original_put = store.put
    calls = [0]

    def partial(owner: str, data: bytes, **kwargs: Any) -> dict[str, Any]:
        calls[0] += 1
        if calls[0] == 2:
            raise ArtifactStoreError("NO_SPACE")
        return original_put(owner, data, **kwargs)

    monkeypatch.setattr(store, "put", partial)

    def failed_revoke(*args: Any) -> Any:
        raise ArtifactStoreError("FAILED_REVOKE")

    monkeypatch.setattr(store, "revoke", failed_revoke)
    try:
        result = pull(worker, handle, lid)
        assert result["status"] == "uncertain"
        assert "FAILED_REVOKE" not in json.dumps(result)
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_grant_revoked_after_private_writes_releases_no_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)
    verify = worker._approved
    calls = [0]

    def expires(*args: Any) -> bool:
        calls[0] += 1
        return calls[0] < 3 and verify(*args)

    monkeypatch.setattr(worker, "_approved", expires)
    try:
        reply = pull(worker, handle, lid)
        assert reply["status"] == "uncertain"
        assert reply["errors"][0]["code"] == "CONSENT_REQUIRED"
        assert calls == [3]
        assert store.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


def test_lifecycle_disconnected_after_writes_rolls_back_all_private_handles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)
    real = module.verified_fake_target
    calls = [0]

    def unavailable(*args: Any) -> bool:
        calls[0] += 1
        return calls[0] < 3 and real(*args)

    monkeypatch.setattr(module, "verified_fake_target", unavailable)
    try:
        reply = pull(worker, handle, lid)
        assert reply["status"] == "uncertain"
        assert reply["errors"][0]["code"] == "UNVERIFIED_TARGET"
        assert calls == [3]
        assert store.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()
