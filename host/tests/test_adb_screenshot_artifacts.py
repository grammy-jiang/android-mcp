"""H4.a mandatory sensitive screenshot/artifact Tool contracts; synthetic-only."""

from __future__ import annotations

import asyncio
import hashlib
import json
import struct
import subprocess
import zlib
from pathlib import Path
from typing import Any

from fastmcp import Client
from jsonschema import Draft202012Validator
from test_avd_provisioning import NAME, OWNER
from test_emulator_lifecycle_jobs import REQUEST as LIFECYCLE_REQUEST
from test_emulator_lifecycle_jobs import engine

from android_mcp_host.durable_jobs import DurableJobStore
from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.server import create_server

ART_OWNER = "private-screenshot-owner"
REQ = "screenshot-fixture-001"


def png_fixture(width: int = 2, height: int = 2) -> bytes:
    def chunk(name: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + name
            + data
            + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)
        )

    image = b"".join(b"\x00" + b"\x9b\x11\x22\xff" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(image))
        + chunk(b"IEND", b"")
    )


def builder(
    tmp_path: Path,
    *,
    consent: bool = True,
    backend: Any = None,
    active: bool = True,
) -> tuple[Any, Any, DurableJobStore, PrivateArtifactStore, str, str]:
    from android_mcp_host.synthetic_screenshot import (
        CaptureApproval,
        CaptureFrame,
        ScreenshotArtifacts,
    )

    # Give the isolated synthetic child the full bounded readiness window.
    # Shared CI macOS runners can be slow to start a Python subprocess.
    lifecycle, handle, jobs, _ = engine(tmp_path, backend=active, readiness_timeout=5.0)
    lid = "job_" + "z" * 32
    if active:
        started = lifecycle.run("start", NAME, handle, request_id=LIFECYCLE_REQUEST)
        assert started["status"] == "ok"
        lid = started["job_id"]
    artifacts = PrivateArtifactStore(tmp_path / "screen-artifacts")
    approval = (
        CaptureApproval(
            owner=OWNER,
            avd_handle=handle,
            lifecycle_job_id=lid,
            purpose="synthetic-debug-screenshot",
            ttl_s=120,
        )
        if consent
        else None
    )
    if backend is None:

        def backend(*args: Any) -> CaptureFrame:
            return CaptureFrame(
                png_fixture(),
                avd_name=NAME,
                avd_handle=handle,
                lifecycle_job_id=lid,
                secure_window=False,
                locked_window=False,
                synthetic=True,
            )

    worker = ScreenshotArtifacts(
        lifecycle.provisioner,
        lifecycle,
        jobs,
        artifacts,
        owner=OWNER,
        artifact_owner=ART_OWNER,
        approval=approval,
        fixture_capture=backend,
    )
    return worker, lifecycle, jobs, artifacts, handle, lid


def capture(
    worker: Any, handle: str, lid: str, *, request: str = REQ, name: str = NAME
) -> dict[str, Any]:
    return worker.submit("capture", name, handle, lid, request_id=request)


def test_t_h4a_01_exact_fake_png_returns_private_sha_and_handle(tmp_path: Path) -> None:
    from android_mcp_host.synthetic_screenshot import CaptureFrame

    calls: list[Any] = []

    def fake(name: str, handle: str, lid: str, timeout: float) -> CaptureFrame:
        calls.append((name, handle, lid, timeout))
        return CaptureFrame(png_fixture(), name, handle, lid, False, False, True)

    worker, live, jobs, artifacts, handle, lid = builder(tmp_path, backend=fake)
    try:
        reply = capture(worker, handle, lid)
        assert reply["status"] == "ok"
        assert reply["capture_state"] == "captured_synthetic"
        assert reply["artifact_handle"].startswith("art_")
        assert reply["sha256"] == hashlib.sha256(png_fixture()).hexdigest()
        assert reply["width"] == 2 and reply["height"] == 2
        assert reply["avd_name"] == NAME and reply["avd_handle"] == handle
        assert reply["privacy_class"] == "sensitive_private"
        assert reply["real_capture_enabled"] is False
        assert artifacts.read(ART_OWNER, reply["artifact_handle"]) == png_fixture()
        assert jobs.status(OWNER, reply["job_id"])["job"]["state"] == "succeeded"
        assert calls == [(NAME, handle, lid, 3.0)]
        assert str(tmp_path) not in json.dumps(reply)
        assert "iVBOR" not in json.dumps(reply)
    finally:
        live.shutdown()


def test_t_h4a_02_other_target_and_absent_approval_denied(tmp_path: Path) -> None:
    calls = [0]

    def forbidden(*args: Any) -> Any:
        calls[0] += 1
        raise AssertionError("Missing permission must block capture")

    worker, live, jobs, artifacts, handle, lid = builder(
        tmp_path,
        consent=False,
        backend=forbidden,
    )
    try:
        for name, owner, target in (
            (NAME, handle, lid),
            ("existing_native_emulator", handle, lid),
            (NAME, "mcpavd_" + "x" * 32, lid),
            (NAME, handle, "job_" + "x" * 32),
        ):
            result = worker.submit("capture", name, owner, target, request_id=REQ)
            assert result["status"] == "blocked"
        assert calls == [0]
        assert artifacts.list_metadata(ART_OWNER) == []
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


def test_t_h4a_03_bad_png_crc_size_and_spoofed_identity_rejected(tmp_path: Path) -> None:
    from android_mcp_host.synthetic_screenshot import CaptureFrame

    malformed = [
        b"",
        b"not a PNG",
        png_fixture()[:-4],
        png_fixture().replace(b"IDAT", b"EDAT", 1),
        png_fixture(2049, 1),
    ]
    for i, data in enumerate(malformed):
        case = tmp_path / f"case{i}"

        def fake(
            name: str, handle: str, lid: str, timeout: float, raw: bytes = data
        ) -> CaptureFrame:
            return CaptureFrame(raw, name, handle, lid, False, False, True)

        worker, live, jobs, artifacts, handle, lid = builder(case, backend=fake)
        try:
            denied = capture(worker, handle, lid)
            assert denied["status"] in {"failed", "uncertain"}
            assert denied["artifact_handle"] is None
            assert artifacts.list_metadata(ART_OWNER) == []
        finally:
            live.shutdown()
    worker, live, jobs, artifacts, handle, lid = builder(
        tmp_path / "spoof",
        backend=lambda name, handle, lid, timeout: CaptureFrame(
            png_fixture(),
            "physical_serial",
            handle,
            lid,
            False,
            False,
            True,
        ),
    )
    try:
        denied = capture(worker, handle, lid)
        assert denied["status"] == "failed"
        assert denied["artifact_handle"] is None
    finally:
        live.shutdown()


def test_t_h4a_04_secure_screen_is_never_bypassed(tmp_path: Path) -> None:
    from android_mcp_host.synthetic_screenshot import CaptureFrame

    for flag in ("secure_window", "locked_window"):
        case = tmp_path / flag
        worker, live, jobs, artifacts, handle, lid = builder(
            case,
            backend=lambda name, handle, lid, timeout, protected=flag: CaptureFrame(
                png_fixture(),
                name,
                handle,
                lid,
                protected == "secure_window",
                protected == "locked_window",
                True,
            ),
        )
        try:
            result = capture(worker, handle, lid)
            assert result["status"] == "blocked"
            assert result["artifact_handle"] is None
            assert artifacts.list_metadata(ART_OWNER) == []
            assert png_fixture().hex() not in json.dumps(result)
        finally:
            live.shutdown()


def test_t_h4a_05_timeout_and_duplicate_do_not_re_capture(tmp_path: Path) -> None:
    calls = [0]

    def timeout(*args: Any) -> Any:
        calls[0] += 1
        raise subprocess.TimeoutExpired(["fixture-screenshot"], 0.01)

    worker, live, jobs, artifacts, handle, lid = builder(tmp_path, backend=timeout)
    try:
        first = capture(worker, handle, lid)
        assert first["status"] == "uncertain"
        assert first["artifact_handle"] is None
        second = capture(worker, handle, lid)
        assert second["status"] == "uncertain"
        assert first["job_id"] == second["job_id"]
        assert calls == [1]
        assert capture(worker, handle, lid, request="another-capture")["status"] == "blocked"
        assert artifacts.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


def test_t_h4a_06_fastmcp_sensitive_artifact_contract_default_disabled(
    tmp_path: Path,
) -> None:
    from android_mcp_host.synthetic_screenshot import get_screenshot_schema

    worker, live, jobs, artifacts, handle, lid = builder(
        tmp_path,
        active=False,
        consent=False,
    )

    async def verify() -> None:
        async with Client(create_server()) as base:
            original = {tool.name: tool for tool in await base.list_tools()}
        async with Client(create_server(screenshot_worker=worker)) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert set(tools) == {*original, "host_screenshot"}
            assert all(tools[name] == original[name] for name in original)
            schema = get_screenshot_schema()
            Draft202012Validator.check_schema(schema)
            assert tools["host_screenshot"].output_schema == schema
            hints = tools["host_screenshot"].annotations.model_dump(mode="json", by_alias=True)
            assert hints["destructiveHint"] is True
            assert hints["readOnlyHint"] is False
            planned = await client.call_tool(
                "host_screenshot",
                {
                    "action": "plan",
                    "avd_name": NAME,
                    "avd_handle": handle,
                    "lifecycle_job_id": lid,
                },
            )
            assert planned.structured_content["status"] == "planned"
            denied = await client.call_tool(
                "host_screenshot",
                {
                    "action": "capture",
                    "avd_name": NAME,
                    "avd_handle": handle,
                    "lifecycle_job_id": lid,
                    "request_id": REQ,
                },
            )
            assert denied.structured_content["status"] == "blocked"
            assert denied.structured_content["artifact_handle"] is None
            Draft202012Validator(schema).validate(denied.structured_content)

    try:
        asyncio.run(verify())
    finally:
        live.shutdown()
    assert jobs.list_status(OWNER) == []
