"""H5.a six mandatory synthetic private sanitized bugreport acceptance cases."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import subprocess
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator
from test_avd_provisioning import NAME, OWNER
from test_emulator_lifecycle_jobs import REQUEST as START_REQUEST
from test_emulator_lifecycle_jobs import engine

from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.server import create_server

ART_OWNER = "synthetic-bugreport-artifacts"
REQ = "synthetic-bugreport-request-001"
MARKER = "OK:/bugreports/bugreport-mcp-fixture.zip"
RAW = (
    b"UPTIME_SECONDS=120\nBATTERY_PERCENT=61\nSTATE=ready\n"
    b"ACCOUNT=user@example.com\nTOKEN=private-bearer-abc\n"
    b"LOG_ID=real-person-id-12345\n"
)
MAX_ARCHIVE = 1024 * 1024


def archive(text: bytes = RAW, *, version: bytes = b"BUGREPORTV1\n") -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("version.txt", version)
        z.writestr("bugreport.txt", text)
    return output.getvalue()


def builder(
    tmp_path: Path,
    *,
    active: bool = True,
    approved: bool = True,
    runner: Any = None,
) -> tuple[Any, Any, Any, PrivateArtifactStore, str, str, list[Any]]:
    from android_mcp_host.synthetic_bugreport import (
        BugreportApproval,
        BugreportFrame,
        BugreportService,
    )

    live, handle, jobs, _ = engine(tmp_path, backend=active, readiness_timeout=5.0)
    lid = "job_" + "z" * 32
    if active:
        state = live.run("start", NAME, handle, request_id=START_REQUEST)
        assert state["status"] == "ok"
        lid = state["job_id"]
    store = PrivateArtifactStore(tmp_path / "private-sanitized-reports")
    grant = (
        BugreportApproval(
            OWNER,
            handle,
            lid,
            "synthetic-sanitized-bugreport",
            time.time() + 120,
            120,
        )
        if approved
        else None
    )
    calls: list[Any] = []
    if runner is None:

        def runner(
            name: str,
            avd_handle: str,
            lifecycle_id: str,
            timeout_s: float,
            byte_cap: int,
            stop: threading.Event,
        ) -> BugreportFrame:
            calls.append((name, avd_handle, lifecycle_id, timeout_s, byte_cap))
            assert stop.is_set() is False
            return BugreportFrame(archive(), MARKER, name, avd_handle, lifecycle_id, True, True)

    worker = BugreportService(
        live.provisioner,
        live,
        jobs,
        store,
        owner=OWNER,
        artifact_owner=ART_OWNER,
        approval=grant,
        fixture_collect=runner,
    )
    return worker, live, jobs, store, handle, lid, calls


def collect(
    worker: Any,
    handle: str,
    lid: str,
    *,
    request: str = REQ,
    action: str = "collect",
) -> dict[str, Any]:
    return worker.submit(action, NAME, handle, lid, request_id=request)


def test_t_h5a_01_owned_synthetic_bugreport_is_bounded_sanitized_private_zip(
    tmp_path: Path,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    try:
        result = collect(worker, handle, lid)
        assert result["status"] == "ok"
        assert result["report_state"] == "sanitized_synthetic"
        assert result["artifact_handle"].startswith("art_")
        assert result["receipt_handle"].startswith("art_")
        assert result["sha256"]
        assert result["size_bytes"] <= MAX_ARCHIVE
        assert result["retention_seconds"] == 120
        assert result["real_bugreport_enabled"] is False
        assert result["physical_device_reads_enabled"] is False
        assert result["synthetic_fixture_only"] is True
        assert result["sanitized_only"] is True
        saved = store.read(ART_OWNER, result["artifact_handle"])
        assert hashlib.sha256(saved).hexdigest() == result["sha256"]
        with zipfile.ZipFile(io.BytesIO(saved)) as z:
            assert z.namelist() == ["version.txt", "bugreport.txt"]
            text = z.read("bugreport.txt")
        assert b"UPTIME_SECONDS=120" in text
        assert b"BATTERY_PERCENT=61" in text
        assert b"ACCOUNT=" not in text
        assert b"private-bearer-abc" not in text
        assert b"user@example.com" not in text
        assert b"real-person-id" not in text
        assert result["redacted_lines"] >= 3
        assert calls == [(NAME, handle, lid, 3.0, MAX_ARCHIVE)]
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "succeeded"
        assert RAW.decode() not in json.dumps(result)
    finally:
        live.shutdown()


def test_t_h5a_02_physical_or_unapproved_never_invokes_bugreport_reader(
    tmp_path: Path,
) -> None:
    called = [0]

    def prohibited(*args: Any) -> Any:
        called[0] += 1
        pytest.fail("Unapproved private diagnostic collection")

    worker, live, jobs, store, handle, lid, calls = builder(
        tmp_path,
        approved=False,
        runner=prohibited,
    )
    try:
        assert collect(worker, handle, lid)["errors"][0]["code"] == "CONSENT_REQUIRED"
        assert collect(worker, "physical-USB-serial", lid)["status"] == "blocked"
        assert collect(worker, handle, "job_" + "y" * 32)["status"] == "blocked"
        assert called == [0]
        assert store.list_metadata(ART_OWNER) == []
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"NOT_A_ZIP",
        b"PK\x03\x04bad",
        archive(version=b"WRONG_VERSION\n"),
    ],
)
def test_t_h5a_03_invalid_zip_version_or_bugreportz_marker_deny(
    tmp_path: Path,
    data: bytes,
) -> None:
    from android_mcp_host.synthetic_bugreport import BugreportFrame

    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    worker._fixture = lambda *args: BugreportFrame(
        data,
        MARKER,
        NAME,
        handle,
        lid,
        True,
        True,
    )
    try:
        result = collect(worker, handle, lid)
        assert result["status"] == "failed"
        assert result["errors"][0]["code"] == "BAD_ARCHIVE"
        assert store.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


def test_t_h5a_04_redacts_accounts_tokens_log_ids_before_private_store(
    tmp_path: Path,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    raw_bytes = archive()
    try:
        result = collect(worker, handle, lid)
        assert result["status"] == "ok"
        for saved in store.list_metadata(ART_OWNER):
            content = store.read(ART_OWNER, saved["handle"])
            assert content != raw_bytes
            assert b"private-bearer" not in content
            assert b"user@example.com" not in content
            assert b"real-person-id" not in content
        assert result["redacted_lines"] == 3
        assert "user@example.com" not in json.dumps(result)
    finally:
        live.shutdown()


def test_t_h5a_05_timeout_uncertain_without_partial_artifacts(tmp_path: Path) -> None:
    def timeout(*args: Any) -> Any:
        raise subprocess.TimeoutExpired(["fake-bugreport"], 0.1)

    worker, live, jobs, store, handle, lid, calls = builder(tmp_path, runner=timeout)
    try:
        result = collect(worker, handle, lid)
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "TIMEOUT"
        assert result["artifact_handle"] is None
        assert store.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_t_h5a_06_fastmcp_schema_retention_and_production_denial(
    tmp_path: Path,
) -> None:
    from android_mcp_host.synthetic_bugreport import get_bugreport_schema

    worker, live, jobs, store, handle, lid, calls = builder(tmp_path, active=False, approved=False)

    async def verify() -> None:
        async with Client(create_server()) as base:
            originals = {t.name: t for t in await base.list_tools()}
        async with Client(create_server(bugreport_worker=worker)) as client:
            tools = {t.name: t for t in await client.list_tools()}
            assert set(tools) == {*originals, "host_bugreport"}
            assert all(tools[name] == originals[name] for name in originals)
            tool = tools["host_bugreport"]
            schema = get_bugreport_schema()
            Draft202012Validator.check_schema(schema)
            assert tool.output_schema == schema
            hints = tool.annotations.model_dump(mode="json", by_alias=True)
            assert hints["readOnlyHint"] is False
            assert hints["destructiveHint"] is True
            args = {"avd_name": NAME, "avd_handle": handle, "lifecycle_job_id": lid}
            plan = await client.call_tool("host_bugreport", {"action": "plan", **args})
            assert plan.structured_content["status"] == "planned"
            denied = await client.call_tool(
                "host_bugreport",
                {"action": "collect", "request_id": REQ, **args},
            )
            assert denied.structured_content["status"] == "blocked"
            assert denied.structured_content["errors"][0]["code"] == "CONSENT_REQUIRED"
            assert denied.structured_content["artifact_handle"] is None
            assert denied.structured_content["real_bugreport_enabled"] is False
            Draft202012Validator(schema).validate(denied.structured_content)

    try:
        asyncio.run(verify())
    finally:
        live.shutdown()
