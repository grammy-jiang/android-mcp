"""H4.c mandatory bounded private screen recording: synthetic fixture only."""

from __future__ import annotations

import asyncio
import hashlib
import json
import struct
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator
from test_avd_provisioning import NAME, OWNER
from test_emulator_lifecycle_jobs import REQUEST as START_REQUEST
from test_emulator_lifecycle_jobs import engine

from android_mcp_host.durable_jobs import DurableJobStore
from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.server import create_server

ART_OWNER = "synthetic-video-private"
REQ = "screenrecord-req-001"
MAX_VIDEO = 262144


def mp4_fixture(payload: bytes = b"synthetic-fixed-video-bytes") -> bytes:
    def box(name: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data) + 8) + name + data

    return (
        box(b"ftyp", b"isom" + b"\0\0\2\0" + b"isom" + b"mp42")
        + box(b"moov", b"synthetic-moov-box")
        + box(b"mdat", payload)
    )


def builder(
    tmp_path: Path,
    *,
    active: bool = True,
    consent: bool = True,
    backend: Any = None,
) -> tuple[Any, Any, DurableJobStore, PrivateArtifactStore, str, str]:
    from android_mcp_host.synthetic_screenrecord import (
        RecordApproval,
        RecordedClip,
        ScreenRecordService,
    )

    live, handle, jobs, _ = engine(tmp_path, backend=active, readiness_timeout=5.0)
    lid = "job_" + "z" * 32
    if active:
        started = live.run("start", NAME, handle, request_id=START_REQUEST)
        assert started["status"] == "ok"
        lid = started["job_id"]
    artifacts = PrivateArtifactStore(tmp_path / "private-videos")
    approval = (
        RecordApproval(
            owner=OWNER,
            avd_handle=handle,
            lifecycle_job_id=lid,
            purpose="synthetic-video-recording",
            valid_until_epoch=time.time() + 150,
            ttl_s=120,
        )
        if consent
        else None
    )
    if backend is None:

        def backend(
            name: str,
            handle: str,
            lid: str,
            duration: int,
            display: int,
            codec: str,
            size: int,
            stop: threading.Event,
        ) -> RecordedClip:
            assert not stop.is_set()
            return RecordedClip(
                mp4_fixture(),
                name,
                handle,
                lid,
                duration,
                display,
                codec,
                False,
                False,
                True,
            )

    service = ScreenRecordService(
        live.provisioner,
        live,
        jobs,
        artifacts,
        owner=OWNER,
        artifact_owner=ART_OWNER,
        approval=approval,
        fixture_record=backend,
    )
    return service, live, jobs, artifacts, handle, lid


def record(
    worker: Any, handle: str, lid: str, *, action: str = "record", request: str = REQ, **kwargs: Any
) -> dict[str, Any]:
    return worker.submit(
        action,
        NAME,
        handle,
        lid,
        duration_s=5,
        display_id=0,
        codec="h264",
        max_bytes=MAX_VIDEO,
        request_id=request,
        **kwargs,
    )


def test_t_h4c_01_consent_owned_avd_gets_private_bounded_video_receipt(
    tmp_path: Path,
) -> None:
    calls: list[Any] = []
    from android_mcp_host.synthetic_screenrecord import RecordedClip

    def fake(*args: Any) -> RecordedClip:
        calls.append(args[:-1])
        name, handle, lid, duration, display, codec, size, stop = args
        assert not stop.is_set()
        return RecordedClip(
            mp4_fixture(), name, handle, lid, duration, display, codec, False, False, True
        )

    worker, live, jobs, artifacts, handle, lid = builder(tmp_path, backend=fake)
    try:
        result = record(worker, handle, lid)
        assert result["status"] == "ok"
        assert result["record_state"] == "captured_synthetic"
        assert result["job_id"].startswith("job_")
        assert result["artifact_handle"].startswith("art_")
        assert result["mime_type"] == "video/mp4"
        assert result["sha256"] == hashlib.sha256(mp4_fixture()).hexdigest()
        assert result["size_bytes"] == len(mp4_fixture())
        assert result["duration_s"] == 5
        assert result["target"] == "disposable_emulator_only"
        assert result["synthetic_fixture_only"] is True
        assert result["real_recording_enabled"] is False
        assert artifacts.read(ART_OWNER, result["artifact_handle"]) == mp4_fixture()
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "succeeded"
        assert len(calls) == 1
        assert calls[0] == (NAME, handle, lid, 5, 0, "h264", MAX_VIDEO)
        assert "synthetic-fixed-video" not in json.dumps(result)
        assert str(tmp_path) not in json.dumps(result)
    finally:
        live.shutdown()


def test_t_h4c_02_default_denial_foreign_physical_or_absent_grant(
    tmp_path: Path,
) -> None:
    calls = [0]

    def prohibited(*args: Any) -> Any:
        calls[0] += 1
        pytest.fail("Unauthorized recording backend called")

    worker, live, jobs, artifacts, handle, lid = builder(
        tmp_path,
        consent=False,
        backend=prohibited,
    )
    try:
        assert record(worker, handle, lid)["errors"][0]["code"] == "CONSENT_REQUIRED"
        assert (
            worker.submit("record", "physical-USB", handle, lid, request_id=REQ)["status"]
            == "blocked"
        )
        assert record(worker, "physical-USB", lid)["status"] == "blocked"
        assert record(worker, handle, "job_" + "x" * 32)["status"] == "blocked"
        assert calls == [0]
        assert artifacts.list_metadata(ART_OWNER) == []
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "options",
    [
        {"duration_s": 0},
        {"duration_s": 31},
        {"duration_s": 2.5},
        {"duration_s": "1; rm -rf /"},
        {"display_id": 1},
        {"display_id": -1},
        {"display_id": "../bad"},
        {"codec": "hevc"},
        {"codec": "--output=/tmp/private"},
        {"max_bytes": 0},
        {"max_bytes": 8 * 1024 * 1024},
        {"max_bytes": "../private"},
        {"request_id": "\ninvalid"},
    ],
)
def test_t_h4c_03_untrusted_size_duration_flags_codec_and_request_denied(
    tmp_path: Path,
    options: dict[str, Any],
) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    try:
        params = {
            "action": "record",
            "avd_name": NAME,
            "avd_handle": handle,
            "lifecycle_job_id": lid,
            "duration_s": 5,
            "display_id": 0,
            "codec": "h264",
            "max_bytes": MAX_VIDEO,
            "request_id": REQ,
        }
        params.update(options)
        result = worker.submit(**params)
        assert result["status"] == "blocked"
        assert result["errors"][0]["code"] == "INVALID_INPUT"
        assert artifacts.list_metadata(ART_OWNER) == []
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


def test_t_h4c_04_mp4_private_ttl_and_idempotent_replay(
    tmp_path: Path,
) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    now = [600.0]
    artifacts._clock = lambda: now[0]
    try:
        first = record(worker, handle, lid)
        assert first["status"] == "ok"
        assert len(artifacts.list_metadata(ART_OWNER)) == 2
        again = record(worker, handle, lid)
        assert again == first
        assert record(worker, handle, lid, request="other-request")["status"] == "blocked"
        assert len(artifacts.list_metadata(ART_OWNER)) == 2
        now[0] += 121
        assert (
            artifacts.public_metadata(ART_OWNER, first["artifact_handle"])["status"] == "not_found"
        )
        expired = record(worker, handle, lid)
        assert expired["status"] == "uncertain"
        assert expired["errors"][0]["code"] == "ARTIFACT_EXPIRED"
    finally:
        live.shutdown()


def test_t_h4c_05_timeout_no_repeat_and_clean_partial_artifact(
    tmp_path: Path,
) -> None:
    calls = [0]

    def timeout(*args: Any) -> Any:
        calls[0] += 1
        raise subprocess.TimeoutExpired(["synthetic-only-video-fixture"], 0.1)

    worker, live, jobs, artifacts, handle, lid = builder(tmp_path, backend=timeout)
    try:
        first = record(worker, handle, lid)
        assert first["status"] == "uncertain"
        assert first["errors"][0]["code"] == "TIMEOUT"
        assert record(worker, handle, lid)["job_id"] == first["job_id"]
        assert calls == [1]
        assert artifacts.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, first["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_t_h4c_06_fastmcp_metadata_private_media_is_plan_only(tmp_path: Path) -> None:
    from android_mcp_host.synthetic_screenrecord import get_screenrecord_schema

    worker, live, jobs, artifacts, handle, lid = builder(tmp_path, active=False, consent=False)

    async def run() -> None:
        async with Client(create_server()) as baseline:
            original = {t.name: t for t in await baseline.list_tools()}
        async with Client(create_server(screenrecord_worker=worker)) as client:
            tools = {t.name: t for t in await client.list_tools()}
            assert set(tools) == {*original, "host_screenrecord"}
            assert all(tools[name] == original[name] for name in original)
            tool = tools["host_screenrecord"]
            schema = get_screenrecord_schema()
            Draft202012Validator.check_schema(schema)
            assert tool.output_schema == schema
            hints = tool.annotations.model_dump(mode="json", by_alias=True)
            assert hints["readOnlyHint"] is False
            assert hints["destructiveHint"] is True
            assert hints["idempotentHint"] is True
            assert "sensitive" in tool.description.lower()
            plan = await client.call_tool(
                "host_screenrecord",
                {"action": "plan", "avd_name": NAME, "avd_handle": handle, "lifecycle_job_id": lid},
            )
            assert plan.structured_content["status"] == "planned"
            denied = await client.call_tool(
                "host_screenrecord",
                {
                    "action": "record",
                    "avd_name": NAME,
                    "avd_handle": handle,
                    "lifecycle_job_id": lid,
                    "request_id": REQ,
                },
            )
            assert denied.structured_content["status"] == "blocked"
            assert denied.structured_content["artifact_handle"] is None
            assert denied.structured_content["real_recording_enabled"] is False
            Draft202012Validator(schema).validate(denied.structured_content)

    try:
        asyncio.run(run())
    finally:
        live.shutdown()
