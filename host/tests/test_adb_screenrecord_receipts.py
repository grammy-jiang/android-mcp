"""H4.c private synthetic video receipt integrity and no-blind-replay regressions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_adb_screenrecord_job import ART_OWNER, builder, mp4_fixture, record

from android_mcp_host.private_artifact_support import ArtifactStoreError
from android_mcp_host.screenrecord_support import InvalidSyntheticVideo, validate_video


@pytest.mark.parametrize(
    "rewrite",
    [
        {"purpose": "foreign-media"},
        {"job_id": "job_" + "x" * 32},
        {"avd_handle": "mcpavd_" + "z" * 32},
        {"lifecycle_job_id": "job_" + "z" * 32},
        {"duration_s": 30},
        {"display_id": 1},
        {"codec": "unsupported"},
        {"artifact_handle": "art_" + "x" * 32},
        {"sha256": "0" * 64},
        {"purpose": ["not-a-string"]},
    ],
)
def test_corrupted_private_metadata_never_replays_as_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rewrite: dict[str, Any]
) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    try:
        original = record(worker, handle, lid)
        assert original["status"] == "ok"
        receipt_handle = original["receipt_handle"]
        original_read = artifacts.read

        def corrupted(owner: str, key: str) -> bytes:
            data = original_read(owner, key)
            if key != receipt_handle:
                return data
            fields = json.loads(data)
            fields.update(rewrite)
            return json.dumps(fields).encode("utf-8")

        monkeypatch.setattr(artifacts, "read", corrupted)
        denied = record(worker, handle, lid)
        assert denied["status"] == "uncertain"
        assert denied["artifact_handle"] is None
        assert denied["errors"][0]["code"] == "ARTIFACT_EXPIRED"
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "bad_result",
    [
        b"invalid-json",
        b"[]",
        b"{}",
        b'{"purpose":null}',
        b"\xff",
    ],
)
def test_malformed_json_receipt_does_not_publish_stale_video(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad_result: bytes,
) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    try:
        initial = record(worker, handle, lid)
        assert initial["status"] == "ok"
        read = artifacts.read

        def changed(owner: str, key: str) -> bytes:
            if key == initial["receipt_handle"]:
                return bad_result
            return read(owner, key)

        monkeypatch.setattr(artifacts, "read", changed)
        result = record(worker, handle, lid)
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "ARTIFACT_EXPIRED"
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "bad_payload",
    [
        mp4_fixture(b"changed-but-container-looks-valid"),
        b"not-an-mp4",
    ],
)
def test_private_media_integrity_or_format_changed_replay_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad_payload: bytes,
) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    try:
        first = record(worker, handle, lid)
        original_read = artifacts.read

        def altered(owner: str, key: str) -> bytes:
            if key == first["artifact_handle"]:
                return bad_payload
            return original_read(owner, key)

        monkeypatch.setattr(artifacts, "read", altered)
        denied = record(worker, handle, lid)
        assert denied["status"] == "uncertain"
        assert denied["errors"][0]["code"] == "ARTIFACT_EXPIRED"
    finally:
        live.shutdown()


def test_unrelated_json_metadata_not_misinterpreted_as_recording_receipt(tmp_path: Path) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    artifacts.put(ART_OWNER, b'{"old":"unrelated"}', mime_type="application/json")
    try:
        first = record(worker, handle, lid)
        assert first["status"] == "ok"
        assert record(worker, handle, lid) == first
        assert len(artifacts.list_metadata(ART_OWNER)) == 3
    finally:
        live.shutdown()


@pytest.mark.parametrize("fault", ["list", "read"])
def test_private_storage_io_failure_returns_unavailable_receipt_without_leak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    try:
        first = record(worker, handle, lid)
        assert first["status"] == "ok"

        def fail(*args: Any, **kwargs: Any) -> Any:
            raise ArtifactStoreError("PRIVATE_FILE_SYSTEM_UNAVAILABLE")

        if fault == "list":
            monkeypatch.setattr(artifacts, "list_metadata", fail)
        else:
            monkeypatch.setattr(artifacts, "read", fail)
        response = record(worker, handle, lid)
        assert response["status"] == "uncertain"
        assert "PRIVATE_FILE_SYSTEM" not in json.dumps(response)
        assert response["errors"][0]["code"] == "ARTIFACT_EXPIRED"
    finally:
        live.shutdown()


def test_truncated_fake_box_header_and_empty_box_are_rejected() -> None:
    from test_adb_screenrecord_faults import box

    brand = b"isom" + b"\0\0\2\0" + b"isom" + b"mp42"
    truncated = box(b"ftyp", brand) + box(b"moov", b"normal-record-metadata") + b"\0\0\0\0"
    assert len(truncated) >= 44
    with pytest.raises(InvalidSyntheticVideo):
        validate_video(truncated)

    no_brand = (
        box(b"ftyp", b"") + box(b"moov", b"complete-moov-box") + box(b"mdat", b"synthetic-payload")
    )
    assert len(no_brand) >= 44
    with pytest.raises(InvalidSyntheticVideo):
        validate_video(no_brand)


def test_fixed_owner_job_slot_does_not_repeat_on_changed_size_or_codec(tmp_path: Path) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    try:
        initial = record(worker, handle, lid)
        assert initial["status"] == "ok"
        changed = worker.submit(
            "record",
            "mcp_owned_avd_api36",
            handle,
            lid,
            request_id="screenrecord-req-001",
            duration_s=5,
            display_id=0,
            codec="h264",
            max_bytes=32768,
        )
        assert changed["status"] == "blocked"
        assert len(artifacts.list_metadata(ART_OWNER)) == 2
    finally:
        live.shutdown()
