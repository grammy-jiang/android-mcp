"""H4.f private per-action receipts, replay and exact audit rejection."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_adb_emulator_ui_actions import (
    ART_OWNER,
    GENERATION,
    builder,
    execute,
)
from test_avd_provisioning import OWNER

from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.private_artifact_support import ArtifactStoreError


def test_idempotent_receipt_and_TTL_never_reissue_key_or_tap(tmp_path: Path) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    now = [500.0]
    artifacts._clock = lambda: now[0]
    try:
        first = execute(worker, handle, lid)
        assert first["status"] == "simulated"
        assert first["action_id"] == first["job_id"]
        assert execute(worker, handle, lid) == first
        assert len(calls) == 1
        assert len(artifacts.list_metadata(ART_OWNER)) == 1
        now[0] += 121
        assert artifacts.public_metadata(ART_OWNER, first["report_handle"])["status"] == "not_found"
        denied = execute(worker, handle, lid)
        assert denied["status"] == "uncertain"
        assert denied["errors"][0]["code"] == "ARTIFACT_EXPIRED"
        assert len(calls) == 1
        assert jobs.status(OWNER, first["job_id"])["job"]["state"] == "succeeded"
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "corrupt",
    [
        {"purpose": "untrusted-purpose"},
        {"job_id": "job_" + "x" * 32},
        {"avd_handle": "mcpavd_" + "y" * 32},
        {"lifecycle_job_id": "job_" + "z" * 32},
        {"window_id": "win_foreign"},
        {"window_generation": GENERATION + 1},
        {"rotation": 1},
        {"focused_node_id": "node_wrong"},
        {"kind": "swipe"},
        {"intent_sha256": "0" * 64},
        {"synthetic_fixture_only": False},
    ],
)
def test_private_receipt_tampering_never_replays_trusted_UI_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corrupt: dict[str, Any],
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    first = execute(worker, handle, lid)
    assert first["status"] == "simulated"
    real = artifacts.read

    def altered(owner: str, token: str) -> bytes:
        raw = real(owner, token)
        if token == first["report_handle"]:
            data = json.loads(raw)
            data.update(corrupt)
            return json.dumps(data).encode("utf-8")
        return raw

    monkeypatch.setattr(artifacts, "read", altered)
    try:
        denied = execute(worker, handle, lid)
        assert denied["status"] == "uncertain"
        assert denied["errors"][0]["code"] == "ARTIFACT_EXPIRED"
        assert denied["report_handle"] is None
        assert len(calls) == 1
    finally:
        live.shutdown()


@pytest.mark.parametrize("garbage", [b"x", b"[]", b"{}", b"null", b"\xff"])
def test_bad_json_private_action_receipt_cannot_prove_a_UI_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    garbage: bytes,
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    first = execute(worker, handle, lid)
    real = artifacts.read
    monkeypatch.setattr(
        artifacts,
        "read",
        lambda owner, token: garbage if token == first["report_handle"] else real(owner, token),
    )
    try:
        denied = execute(worker, handle, lid)
        assert denied["status"] == "uncertain"
        assert denied["errors"][0]["code"] == "ARTIFACT_EXPIRED"
        assert len(calls) == 1
    finally:
        live.shutdown()


@pytest.mark.parametrize("which", ["read", "list"])
def test_private_receipt_read_failure_stays_uncertain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    which: str,
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    first = execute(worker, handle, lid)
    assert first["status"] == "simulated"

    def storage_failure(*args: Any, **kwargs: Any) -> Any:
        raise ArtifactStoreError("PRIVATE-ACCESS-UNAVAILABLE")

    monkeypatch.setattr(artifacts, "read" if which == "read" else "list_metadata", storage_failure)
    try:
        denied = execute(worker, handle, lid)
        assert denied["status"] == "uncertain"
        assert denied["errors"][0]["code"] == "ARTIFACT_EXPIRED"
        assert "PRIVATE-ACCESS" not in json.dumps(denied)
        assert len(calls) == 1
    finally:
        live.shutdown()


def test_unrelated_json_receipt_not_adopted_as_UI_action(tmp_path: Path) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    artifacts.put(ART_OWNER, b'{"other":"fixture"}', mime_type="application/json")
    try:
        first = execute(worker, handle, lid)
        assert first["status"] == "simulated"
        assert execute(worker, handle, lid) == first
        assert len(artifacts.list_metadata(ART_OWNER)) == 2
        assert len(calls) == 1
    finally:
        live.shutdown()


def test_revoked_receipt_has_no_replay_success(tmp_path: Path) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    first = execute(worker, handle, lid)
    artifacts.revoke(ART_OWNER, first["report_handle"])
    try:
        denied = execute(worker, handle, lid)
        assert denied["status"] == "uncertain"
        assert denied["errors"][0]["code"] == "ARTIFACT_EXPIRED"
        assert len(calls) == 1
    finally:
        live.shutdown()


def test_private_job_failed_state_never_claimed_as_simulated_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    assert execute(worker, handle, lid)["status"] == "simulated"
    real = jobs.lookup_request

    def terminal_failure(*args: Any, **kwargs: Any) -> Any:
        job = real(*args, **kwargs)
        assert job is not None
        return {**job, "state": "failed"}

    monkeypatch.setattr(jobs, "lookup_request", terminal_failure)
    try:
        result = execute(worker, handle, lid)
        assert result["status"] == "failed"
        assert result["errors"][0]["code"] == "BAD_FRAME"
        assert len(calls) == 1
    finally:
        live.shutdown()


def test_private_artifact_failure_cannot_complete_UI_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    monkeypatch.setattr(
        artifacts,
        "put",
        lambda *args, **kwargs: (_ for _ in ()).throw(ArtifactStoreError("SECRET-WRITE")),
    )
    try:
        reply = execute(worker, handle, lid)
        assert reply["status"] == "uncertain"
        assert reply["errors"][0]["code"] == "RUNNER_FAILED"
        assert reply["report_handle"] is None
        assert artifacts.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, reply["job_id"])["job"]["state"] == "uncertain"
        assert "SECRET-WRITE" not in json.dumps(reply)
    finally:
        live.shutdown()


def test_durable_commit_failure_revokes_action_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)

    def failure(*args: Any, **kwargs: Any) -> Any:
        raise JobStoreError("SECRET-JOB-COMMIT")

    monkeypatch.setattr(jobs, "complete", failure)
    try:
        result = execute(worker, handle, lid)
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "RUNNER_FAILED"
        assert artifacts.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_failed_private_revoke_and_cancel_do_not_echo_secret_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)

    def failed_cancel(*args: Any, **kwargs: Any) -> Any:
        raise JobStoreError("SECRET-DB-CANCEL")

    def failed_revoke(*args: Any, **kwargs: Any) -> Any:
        raise ArtifactStoreError("SECRET-REVOKE")

    monkeypatch.setattr(jobs, "complete", failed_cancel)
    monkeypatch.setattr(jobs, "cancel", failed_cancel)
    monkeypatch.setattr(artifacts, "revoke", failed_revoke)
    try:
        reply = execute(worker, handle, lid)
        assert reply["status"] == "uncertain"
        assert reply["errors"][0]["code"] == "RUNNER_FAILED"
        assert "SECRET" not in json.dumps(reply)
    finally:
        live.shutdown()


def test_grant_expiry_after_action_but_before_receipt_commit_discards_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    original = worker._approved
    n = [0]

    def expires(*args: Any) -> bool:
        n[0] += 1
        return original(*args) if n[0] < 4 else False

    monkeypatch.setattr(worker, "_approved", expires)
    try:
        result = execute(worker, handle, lid)
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "CONSENT_REQUIRED"
        assert artifacts.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"
        assert n == [4]
    finally:
        live.shutdown()


def test_focus_changes_after_receipt_write_discards_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    source = worker._witness
    assert source is not None
    checks = [0]

    def changed(*args: Any) -> Any:
        checks[0] += 1
        frame = source(*args)
        if checks[0] == 3:
            return replace(frame, focused_node_id="node_other")
        return frame

    monkeypatch.setattr(worker, "_witness", changed)
    try:
        result = execute(worker, handle, lid)
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "STALE_WINDOW"
        assert artifacts.list_metadata(ART_OWNER) == []
        assert checks == [3]
    finally:
        live.shutdown()
