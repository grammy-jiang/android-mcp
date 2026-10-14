"""H4.c adversarial synthetic media, consent, replay and failure contracts."""

from __future__ import annotations

import math
import struct
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_adb_screenrecord_job import (
    ART_OWNER,
    MAX_VIDEO,
    REQ,
    builder,
    mp4_fixture,
    record,
)
from test_avd_provisioning import NAME, OWNER

from android_mcp_host.screenrecord_support import (
    MAX_VIDEO_BYTES,
    InvalidSyntheticVideo,
    valid_record_request,
    validate_video,
)
from android_mcp_host.synthetic_screenrecord import (
    RecordApproval,
    RecordedClip,
    ScreenRecordService,
)


def box(name: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload) + 8) + name + payload


@pytest.mark.parametrize(
    "sample",
    [
        b"",
        "text-not-bytes",
        mp4_fixture()[:10],
        b"x" * (MAX_VIDEO_BYTES + 1),
        b"not-a-movie" + mp4_fixture()[11:],
        mp4_fixture().replace(b"ftyp", b"bad!", 1),
        mp4_fixture().replace(b"moov", b"mdat", 1),
        mp4_fixture().replace(b"mdat", b"evil", 1),
        mp4_fixture() + b"trailer",
        mp4_fixture().replace(b"isom", b"fake", 1),
        mp4_fixture().replace(b"synthetic-moov-box", b"", 1),
        box(b"ftyp", b"isom") + box(b"moov", b"some") + box(b"mdat", b"bytes"),
        box(b"ftyp", b"isom" + b"\0\0\2\0" + b"isom")
        + box(b"moov", b"valid-moov")
        + box(b"mdat", b"x"),
        b"\0\0\0\0ftyp" + mp4_fixture()[8:],
    ],
)
def test_fake_mp4_invalid_container_rejected(sample: Any) -> None:
    with pytest.raises(InvalidSyntheticVideo):
        validate_video(sample)


def test_mp4_exact_fixed_container_valid_and_no_embedded_shell_options() -> None:
    validate_video(mp4_fixture())
    with pytest.raises(InvalidSyntheticVideo):
        validate_video(mp4_fixture(), maximum=24)
    with pytest.raises(InvalidSyntheticVideo):
        validate_video(mp4_fixture(), maximum=True)
    with pytest.raises(InvalidSyntheticVideo):
        validate_video(mp4_fixture(), maximum=MAX_VIDEO_BYTES + 1)
    with pytest.raises(InvalidSyntheticVideo):
        validate_video(mp4_fixture(), maximum=len(mp4_fixture()) - 1)


@pytest.mark.parametrize(
    "params",
    [
        (0, 0, "h264", MAX_VIDEO),
        (31, 0, "h264", MAX_VIDEO),
        (True, 0, "h264", MAX_VIDEO),
        (1.0, 0, "h264", MAX_VIDEO),
        (5, True, "h264", MAX_VIDEO),
        (5, -1, "h264", MAX_VIDEO),
        (5, 1, "h264", MAX_VIDEO),
        (5, 0, "av1", MAX_VIDEO),
        (5, 0, "h264 -b 999", MAX_VIDEO),
        (5, 0, "h264", 63),
        (5, 0, "h264", MAX_VIDEO_BYTES + 1),
        (5, 0, "h264", False),
    ],
)
def test_record_limits_allow_only_one_display_and_codec(params: Any) -> None:
    assert valid_record_request(*params) is False
    assert valid_record_request(1, 0, "h264", 64) is True
    assert valid_record_request(30, 0, "h264", MAX_VIDEO_BYTES) is True


@pytest.mark.parametrize(
    "change",
    [
        {"avd_name": "different-avd"},
        {"avd_handle": "mcpavd_" + "x" * 32},
        {"lifecycle_job_id": "job_" + "z" * 32},
        {"duration_s": 7},
        {"display_id": 1},
        {"codec": "vp9"},
        {"synthetic": False},
        {"secure_window": "false"},
        {"locked_window": None},
        {"payload": mp4_fixture()[:-4]},
        {"payload": b"PRIVATE-RAW-SECRET"},
    ],
)
def test_spoofed_recording_metadata_or_corrupted_mp4_fails_closed(
    tmp_path: Path,
    change: dict[str, Any],
) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)

    def fake(*args: Any) -> RecordedClip:
        clip = RecordedClip(mp4_fixture(), NAME, handle, lid, 5, 0, "h264", False, False, True)
        return replace(clip, **change)

    worker._fixture = fake
    try:
        failed = record(worker, handle, lid)
        assert failed["status"] == "failed"
        assert failed["artifact_handle"] is None
        assert jobs.status(OWNER, failed["job_id"])["job"]["state"] == "failed"
        assert record(worker, handle, lid)["status"] == "failed"
        assert artifacts.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


@pytest.mark.parametrize("security_flag", ["secure_window", "locked_window"])
def test_protected_window_recording_refused_without_private_data(
    tmp_path: Path,
    security_flag: str,
) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)

    def fake(*args: Any) -> RecordedClip:
        original = RecordedClip(mp4_fixture(), NAME, handle, lid, 5, 0, "h264", False, False, True)
        return replace(original, **{security_flag: True})

    worker._fixture = fake
    try:
        reply = record(worker, handle, lid)
        assert reply["status"] == "blocked"
        assert reply["errors"][0]["code"] == "SECURE_CONTENT"
        assert reply["raw_media_returned"] is False
        assert artifacts.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, reply["job_id"])["job"]["state"] == "failed"
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "invalid",
    [
        {"owner": "foreign"},
        {"avd_handle": "mcpavd_" + "x" * 32},
        {"lifecycle_job_id": "job_" + "z" * 32},
        {"purpose": "other-purpose"},
        {"valid_until_epoch": 0},
        {"valid_until_epoch": 10**20},
        {"valid_until_epoch": math.inf},
        {"valid_until_epoch": math.nan},
        {"valid_until_epoch": "not-a-time"},
        {"valid_until_epoch": True},
        {"ttl_s": 0},
        {"ttl_s": 301},
        {"ttl_s": float("nan")},
        {"ttl_s": float("inf")},
        {"ttl_s": "long"},
    ],
)
def test_consent_expiry_wrong_identity_or_invalid_ttl_block_before_backend(
    tmp_path: Path,
    invalid: dict[str, Any],
) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    fields: dict[str, Any] = {
        "owner": OWNER,
        "avd_handle": handle,
        "lifecycle_job_id": lid,
        "purpose": "synthetic-video-recording",
        "valid_until_epoch": time.time() + 120,
        "ttl_s": 120,
    }
    fields.update(invalid)
    worker._approval = RecordApproval(**fields)
    worker._fixture = lambda *args: pytest.fail("unapproved recording fixture")
    try:
        denied = record(worker, handle, lid)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "CONSENT_REQUIRED"
        assert artifacts.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


def test_invalid_owner_at_constructor_and_no_raw_recording_without_executor(tmp_path: Path) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    try:
        for owner, art_owner in (
            ("foreign", ART_OWNER),
            (OWNER, "bad/path"),
            ("..", ART_OWNER),
        ):
            with pytest.raises(ValueError):
                ScreenRecordService(
                    live.provisioner, live, jobs, artifacts, owner=owner, artifact_owner=art_owner
                )
        worker._fixture = None
        blocked = record(worker, handle, lid)
        assert blocked["status"] == "blocked"
        assert blocked["errors"][0]["code"] == "EXECUTION_DISABLED"
    finally:
        live.shutdown()


def test_request_validation_for_plan_capture_cancel_and_physical_denial(tmp_path: Path) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    try:
        tests = (
            worker.submit("raw-shell", NAME, handle, lid),
            worker.submit(True, NAME, handle, lid),
            worker.submit("plan", NAME, handle, "bad"),
            worker.submit("record", NAME, handle, lid, request_id=None),
            worker.submit("record", NAME, handle, lid, request_id="../evil"),
            worker.submit("cancel", NAME, handle, lid, request_id=REQ),
            worker.submit("plan", NAME, "usb-real", lid),
        )
        assert all(value["status"] == "blocked" for value in tests)
        assert tests[0]["errors"][0]["code"] == "INVALID_ACTION"
        assert tests[2]["errors"][0]["code"] == "INVALID_INPUT"
        assert tests[-1]["errors"][0]["code"] == "NOT_OWNED"
        assert worker.submit("plan", NAME, handle, lid)["status"] == "planned"
        assert artifacts.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


def test_disconnected_emulator_during_recording_is_uncertain_and_no_private_artifact(
    tmp_path: Path,
) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)

    def disconnected(*args: Any) -> RecordedClip:
        live.shutdown()
        return RecordedClip(mp4_fixture(), NAME, handle, lid, 5, 0, "h264", False, False, True)

    worker._fixture = disconnected
    result = record(worker, handle, lid)
    assert result["status"] == "uncertain"
    assert result["errors"][0]["code"] == "UNVERIFIED_TARGET"
    assert artifacts.list_metadata(ART_OWNER) == []
    assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"


def test_approval_expires_during_recording_and_media_discarded(tmp_path: Path) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    clock = [1000.0]
    worker._clock = lambda: clock[0]
    worker._approval = RecordApproval(OWNER, handle, lid, "synthetic-video-recording", 1006.0, 120)

    def expire(*args: Any) -> RecordedClip:
        clock[0] = 1010
        return RecordedClip(mp4_fixture(), NAME, handle, lid, 5, 0, "h264", False, False, True)

    worker._fixture = expire
    try:
        result = record(worker, handle, lid)
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "CONSENT_REQUIRED"
        assert artifacts.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


def test_timeout_idempotency_conflict_does_not_repeat_operation(
    tmp_path: Path,
) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    worker._fixture = lambda *args: (_ for _ in ()).throw(
        subprocess.TimeoutExpired(["synthetic-fixture"], 0.001)
    )
    try:
        first = record(worker, handle, lid)
        assert first["status"] == "uncertain"
        assert record(worker, handle, lid)["job_id"] == first["job_id"]
        conflict = record(worker, handle, lid, request="another-id")
        assert conflict["status"] == "blocked"
        assert conflict["errors"][0]["code"] == "IDEMPOTENCY_CONFLICT"
    finally:
        live.shutdown()
