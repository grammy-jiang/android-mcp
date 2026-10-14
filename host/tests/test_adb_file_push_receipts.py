"""H4.e private import receipt replay, TTL and torn-state safety."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_adb_file_push_policy import (
    ART_OWNER,
    DATA,
    DEST,
    SHA,
    builder,
    run_push,
)
from test_avd_provisioning import NAME, OWNER

from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.private_artifact_support import ArtifactStoreError


def test_identical_request_replays_signed_receipt_without_repeating_writer(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path)
    real = worker._writer
    count = [0]

    def once(*args: Any) -> Any:
        count[0] += 1
        assert real is not None
        return real(*args)

    worker._writer = once
    try:
        first = run_push(worker, handle, lid, token)
        assert first["status"] == "simulated"
        again = run_push(worker, handle, lid, token)
        assert again == first
        assert count == [1]
        assert fs == {DEST: DATA}
        assert len(store.list_metadata(ART_OWNER)) == 2
        conflict = run_push(worker, handle, lid, token, request="other-id")
        assert conflict["status"] == "blocked"
        assert conflict["errors"][0]["code"] == "IDEMPOTENCY_CONFLICT"
        assert count == [1]
    finally:
        live.shutdown()


def test_receipt_ttl_cannot_silently_reissue_mutation(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path)
    now = [100.0]
    store._clock = lambda: now[0]
    try:
        first = run_push(worker, handle, lid, token)
        assert first["status"] == "simulated"
        now[0] += 121
        assert store.public_metadata(ART_OWNER, first["report_handle"])["status"] == "not_found"
        again = run_push(worker, handle, lid, token)
        assert again["status"] == "uncertain"
        assert again["errors"][0]["code"] == "ARTIFACT_EXPIRED"
        assert again["report_handle"] is None
        assert fs == {DEST: DATA}
        assert jobs.status(OWNER, first["job_id"])["job"]["state"] == "succeeded"
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "tamper",
    [
        {"purpose": "other-purpose"},
        {"job_id": "job_" + "x" * 32},
        {"avd_handle": "mcpavd_" + "x" * 32},
        {"lifecycle_job_id": "job_" + "z" * 32},
        {"package_id": "org.example.synthetic.other"},
        {"destination_sha256": "f" * 64},
        {"artifact_handle": "art_" + "x" * 32},
        {"artifact_sha256": "0" * 64},
        {"mime_type": "text/plain"},
        {"bytes_written": 0},
        {"bytes_written": len(DATA) + 1},
        {"bytes_written": True},
        {"synthetic_fixture_only": False},
    ],
)
def test_corrupt_receipt_cannot_be_accepted_as_verified_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: dict[str, Any],
) -> None:
    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path)
    first = run_push(worker, handle, lid, token)
    assert first["status"] == "simulated"
    real = store.read

    def forged(owner: str, item: str) -> bytes:
        raw = real(owner, item)
        if item == first["report_handle"]:
            obj = json.loads(raw)
            obj.update(tamper)
            return json.dumps(obj).encode("utf-8")
        return raw

    monkeypatch.setattr(store, "read", forged)
    try:
        denied = run_push(worker, handle, lid, token)
        assert denied["status"] == "uncertain"
        assert denied["errors"][0]["code"] == "ARTIFACT_EXPIRED"
        assert denied["report_handle"] is None
        assert fs == {DEST: DATA}
    finally:
        live.shutdown()


@pytest.mark.parametrize("raw", [b"x", b"[]", b"null", b"{}", b"\xff"])
def test_invalid_receipt_json_not_a_trusted_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw: bytes,
) -> None:
    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path)
    first = run_push(worker, handle, lid, token)
    assert first["status"] == "simulated"
    original = store.read
    monkeypatch.setattr(
        store,
        "read",
        lambda owner, item: raw if item == first["report_handle"] else original(owner, item),
    )
    try:
        result = run_push(worker, handle, lid, token)
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "ARTIFACT_EXPIRED"
    finally:
        live.shutdown()


@pytest.mark.parametrize("bytes_content", [b"tampered", b"", b"x" * len(DATA)])
def test_source_bytes_integrity_is_required_even_for_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bytes_content: bytes,
) -> None:
    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path)
    assert run_push(worker, handle, lid, token)["status"] == "simulated"
    real = store.read
    monkeypatch.setattr(
        store,
        "read",
        lambda owner, item: bytes_content if item == token else real(owner, item),
    )
    try:
        result = run_push(worker, handle, lid, token)
        assert result["status"] == "blocked"
        assert result["errors"][0]["code"] == "BAD_ARTIFACT"
    finally:
        live.shutdown()


@pytest.mark.parametrize("error_on", ["read", "list", "metadata"])
def test_error_retrieving_private_success_report_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_on: str,
) -> None:
    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path)
    first = run_push(worker, handle, lid, token)
    assert first["status"] == "simulated"

    def unavailable(*args: Any, **kwargs: Any) -> Any:
        raise ArtifactStoreError("PRIVATE-KEY-ERROR")

    actual = {"read": "read", "list": "list_metadata", "metadata": "public_metadata"}[error_on]
    monkeypatch.setattr(store, actual, unavailable)
    try:
        result = run_push(worker, handle, lid, token)
        # Missing source is conservatively blocked; no fixture re-execution.
        assert result["status"] in ("blocked", "uncertain")
        assert result["errors"][0]["code"] in ("ARTIFACT_EXPIRED", "BAD_ARTIFACT")
        assert "PRIVATE-KEY-ERROR" not in str(result)
        assert fs == {DEST: DATA}
    finally:
        live.shutdown()


def test_unrelated_json_receipt_skipped_and_not_spoofed(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path)
    store.put(ART_OWNER, b'{"other":"unrelated"}', mime_type="application/json")
    try:
        first = run_push(worker, handle, lid, token)
        assert first["status"] == "simulated"
        assert run_push(worker, handle, lid, token) == first
        assert len(store.list_metadata(ART_OWNER)) == 3
    finally:
        live.shutdown()


def test_revoked_private_source_cannot_replay_earlier_success(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path)
    assert run_push(worker, handle, lid, token)["status"] == "simulated"
    store.revoke(ART_OWNER, token)
    try:
        reply = run_push(worker, handle, lid, token)
        assert reply["status"] == "blocked"
        assert reply["errors"][0]["code"] == "BAD_ARTIFACT"
        assert fs == {DEST: DATA}
    finally:
        live.shutdown()


def test_failed_receipt_write_never_claims_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path)

    def reject(*args: Any, **kwargs: Any) -> Any:
        raise ArtifactStoreError("STORAGE_FAILURE")

    monkeypatch.setattr(store, "put", reject)
    try:
        result = run_push(worker, handle, lid, token)
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "RUNNER_FAILED"
        assert result["report_handle"] is None
        assert len(store.list_metadata(ART_OWNER)) == 1
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_failed_durable_success_transaction_revokes_new_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path)

    def reject(*args: Any, **kwargs: Any) -> Any:
        raise JobStoreError("STORAGE_FAILURE")

    monkeypatch.setattr(jobs, "complete", reject)
    try:
        output = run_push(worker, handle, lid, token)
        assert output["status"] == "uncertain"
        assert output["errors"][0]["code"] == "RUNNER_FAILED"
        assert output["report_handle"] is None
        assert len(store.list_metadata(ART_OWNER)) == 1
        assert jobs.status(OWNER, output["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_private_revoke_and_job_cancel_errors_never_expose_private_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path)

    def bad(*args: Any, **kwargs: Any) -> Any:
        raise ArtifactStoreError("SECRET-REVOKE-FAIL")

    def broken_job(*args: Any, **kwargs: Any) -> Any:
        raise JobStoreError("SECRET-CANCEL-FAIL")

    monkeypatch.setattr(jobs, "complete", broken_job)
    monkeypatch.setattr(jobs, "cancel", broken_job)
    monkeypatch.setattr(store, "revoke", bad)
    try:
        reply = run_push(worker, handle, lid, token)
        assert reply["status"] == "uncertain"
        assert "SECRET" not in json.dumps(reply)
    finally:
        live.shutdown()


def test_expiring_grant_after_private_receipt_write_discards_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path)
    original = worker._approved
    calls = [0]

    def expire(*args: Any) -> bool:
        calls[0] += 1
        return calls[0] < 4 and original(*args)

    monkeypatch.setattr(worker, "_approved", expire)
    try:
        reply = run_push(worker, handle, lid, token)
        assert reply["status"] == "uncertain"
        assert reply["errors"][0]["code"] == "CONSENT_REQUIRED"
        assert reply["report_handle"] is None
        assert len(store.list_metadata(ART_OWNER)) == 1
        assert jobs.status(OWNER, reply["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_corrupt_durable_failed_state_is_not_successfully_replayed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path)
    assert run_push(worker, handle, lid, token)["status"] == "simulated"
    lookup = jobs.lookup_request

    def failed_state(*args: Any, **kwargs: Any) -> Any:
        row = lookup(*args, **kwargs)
        assert row is not None
        return {**row, "state": "failed"}

    monkeypatch.setattr(jobs, "lookup_request", failed_state)
    try:
        denied = run_push(worker, handle, lid, token)
        assert denied["status"] == "failed"
        assert denied["errors"][0]["code"] == "BAD_FRAME"
        assert denied["report_handle"] is None
        assert fs == {DEST: DATA}
    finally:
        live.shutdown()


def test_source_changes_between_initial_validation_and_replay_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path)
    assert run_push(worker, handle, lid, token)["status"] == "simulated"
    real = store.read
    called = [0]

    def changed(owner: str, item: str) -> bytes:
        if item == token:
            called[0] += 1
            if called[0] == 2:
                return b"fixture changed at replay"
        return real(owner, item)

    monkeypatch.setattr(store, "read", changed)
    try:
        denied = run_push(worker, handle, lid, token)
        assert denied["status"] == "uncertain"
        assert denied["errors"][0]["code"] == "ARTIFACT_EXPIRED"
        assert called == [2]
        assert fs == {DEST: DATA}
    finally:
        live.shutdown()


def test_source_is_revoked_during_durable_transaction_without_invoking_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path)
    original = worker._source
    checked = [0]

    def lost(*args: Any) -> bytes | None:
        checked[0] += 1
        return original(*args) if checked[0] == 1 else None

    monkeypatch.setattr(worker, "_source", lost)
    worker._writer = lambda *args: pytest.fail("Revoked source reached synthetic writer")
    try:
        denied = run_push(worker, handle, lid, token)
        assert denied["status"] == "uncertain"
        assert denied["errors"][0]["code"] == "BAD_ARTIFACT"
        assert denied["report_handle"] is None
        assert checked == [2]
        assert len(store.list_metadata(ART_OWNER)) == 1
        assert jobs.status(OWNER, denied["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_grant_revoked_between_preflight_and_durable_claim_cannot_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path)
    approved = worker._approved
    count = [0]

    def expiry(*args: Any) -> bool:
        count[0] += 1
        return approved(*args) if count[0] == 1 else False

    monkeypatch.setattr(worker, "_approved", expiry)
    worker._writer = lambda *args: pytest.fail("Expired grant reached synthetic writer")
    try:
        denied = run_push(worker, handle, lid, token)
        assert denied["status"] == "uncertain"
        assert denied["errors"][0]["code"] == "CONSENT_REQUIRED"
        assert count == [2]
        assert len(store.list_metadata(ART_OWNER)) == 1
        assert jobs.status(OWNER, denied["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_invalid_packaged_file_push_schema_cannot_be_adopted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from android_mcp_host import synthetic_file_push as service

    class InvalidResource:
        def joinpath(self, name: str) -> InvalidResource:
            assert name == "host-synthetic-file-push.v1.schema.json"
            return self

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return "[]"

    monkeypatch.setattr(service, "files", lambda package: InvalidResource())
    with pytest.raises(ValueError):
        service.get_file_push_schema()


def test_invalid_public_action_does_not_issue_any_mutation(
    tmp_path: Path,
) -> None:
    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path)
    worker._writer = lambda *args: pytest.fail("Unknown action reached writer")
    try:
        denied = worker.submit("raw-shell", NAME, handle, lid, token, SHA, DEST)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "INVALID_ACTION"
        assert len(jobs.list_status(OWNER)) == 1
        assert fs == {}
    finally:
        live.shutdown()
