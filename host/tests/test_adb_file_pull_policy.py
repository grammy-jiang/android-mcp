"""H4.d six mandatory synthetic-only scoped app file export acceptance cases."""

from __future__ import annotations

import asyncio
import hashlib
import json
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

from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.server import create_server

ART_OWNER = "synthetic-pull-private"
PACKAGE = "org.example.synthetic.export"
REMOTE = f"/sdcard/Android/data/{PACKAGE}/files/mcp-export/report.json"
MIME = "application/json"
FILE = b'{"source":"synthetic-fixture","count":2}'
DIGEST = hashlib.sha256(FILE).hexdigest()
REQUEST = "private-export-request-001"


def builder(
    tmp_path: Path,
    *,
    active: bool = True,
    consent: bool = True,
    backend: Any = None,
) -> tuple[Any, Any, Any, PrivateArtifactStore, str, str]:
    from android_mcp_host.synthetic_file_pull import (
        FilePullApproval,
        FilePullFrame,
        FilePullService,
    )

    live, handle, jobs, _ = engine(tmp_path, backend=active, readiness_timeout=5.0)
    lid = "job_" + "z" * 32
    if active:
        started = live.run("start", NAME, handle, request_id=START_REQUEST)
        assert started["status"] == "ok"
        lid = started["job_id"]
    store = PrivateArtifactStore(tmp_path / "private-file-pull")
    grant = (
        FilePullApproval(
            OWNER,
            handle,
            lid,
            PACKAGE,
            REMOTE,
            DIGEST,
            "synthetic-app-export",
            time.time() + 120,
            120,
        )
        if consent
        else None
    )
    if backend is None:

        def backend(
            name: str,
            avd_handle: str,
            job_id: str,
            package: str,
            remote: str,
            timeout: float,
            cap: int,
            stop: threading.Event,
        ) -> FilePullFrame:
            assert timeout <= 3.0 and cap <= 262144 and not stop.is_set()
            return FilePullFrame(
                FILE, name, avd_handle, job_id, package, remote, MIME, DIGEST, True, False, True
            )

    worker = FilePullService(
        live.provisioner,
        live,
        jobs,
        store,
        owner=OWNER,
        artifact_owner=ART_OWNER,
        package_id=PACKAGE,
        approval=grant,
        fixture_reader=backend,
    )
    return worker, live, jobs, store, handle, lid


def pull(
    worker: Any,
    handle: str,
    lid: str,
    *,
    path: str = REMOTE,
    request: str = REQUEST,
    expected_sha256: str = DIGEST,
    mime_type: str = MIME,
    max_bytes: int = 262144,
    action: str = "pull",
) -> dict[str, Any]:
    return worker.submit(
        action,
        NAME,
        handle,
        lid,
        path,
        expected_sha256=expected_sha256,
        mime_type=mime_type,
        max_bytes=max_bytes,
        request_id=request,
    )


def test_t_h4d_01_approved_private_app_export_receipt_sha_size(tmp_path: Path) -> None:
    from android_mcp_host.synthetic_file_pull import FilePullFrame

    calls: list[Any] = []

    def fake(*args: Any) -> FilePullFrame:
        calls.append(args[:7])
        name, handle, lid, package, remote, timeout, cap, stop = args
        assert isinstance(stop, threading.Event) and not stop.is_set()
        return FilePullFrame(
            FILE,
            name,
            handle,
            lid,
            package,
            remote,
            MIME,
            DIGEST,
            True,
            False,
            True,
        )

    worker, live, jobs, store, handle, lid = builder(tmp_path, backend=fake)
    try:
        result = pull(worker, handle, lid)
        assert result["status"] == "ok"
        assert result["file_state"] == "pulled_synthetic"
        assert result["artifact_handle"].startswith("art_")
        assert result["receipt_handle"].startswith("art_")
        assert result["sha256"] == DIGEST
        assert result["size_bytes"] == len(FILE)
        assert result["mime_type"] == MIME
        assert result["filename"] == "report.json"
        assert result["package_id"] == PACKAGE
        assert result["job_id"].startswith("job_")
        assert result["real_pull_enabled"] is False
        assert result["physical_device_reads_enabled"] is False
        assert result["physical_device_writes_enabled"] is False
        assert store.read(ART_OWNER, result["artifact_handle"]) == FILE
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "succeeded"
        assert calls == [(NAME, handle, lid, PACKAGE, REMOTE, 3.0, 262144)]
        assert str(tmp_path) not in json.dumps(result)
        assert REMOTE not in json.dumps(result)
        assert FILE.decode() not in json.dumps(result)
    finally:
        live.shutdown()


def test_t_h4d_02_unapproved_target_and_hostile_root_never_invoke_reader(
    tmp_path: Path,
) -> None:
    calls: list[bool] = []

    def forbidden(*args: Any) -> Any:
        calls.append(True)
        pytest.fail("Private export reader must not run")

    worker, live, jobs, store, handle, lid = builder(
        tmp_path,
        consent=False,
        backend=forbidden,
    )
    try:
        assert pull(worker, handle, lid)["errors"][0]["code"] == "CONSENT_REQUIRED"
        assert pull(worker, "usb-real-device", lid)["status"] == "blocked"
        for path in (
            "/data/data/org.example.synthetic.export/shared_prefs/secret.xml",
            "/system/build.prop",
            "/sdcard/DCIM/private.jpg",
            "/storage/emulated/0/Download/secret.txt",
        ):
            rejected = pull(worker, handle, lid, path=path)
            assert rejected["status"] == "blocked"
            assert rejected["errors"][0]["code"] == "SOURCE_DENIED"
        assert calls == []
        assert store.list_metadata(ART_OWNER) == []
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "path",
    [
        "/sdcard/Android/data/org.example.synthetic.export/files/mcp-export/../private.bin",
        "/sdcard/Android/data/org.example.synthetic.export/files/mcp-export/..",
        "/sdcard/Android/data/org.example.synthetic.export/files/mcp-export/.hidden",
        "/sdcard/Android/data/org.example.synthetic.export/files/mcp-export//report.json",
        "/sdcard/Android/data/org.example.synthetic.export/files/mcp-export/a/b.json",
        "/sdcard/Android/data/org.example.synthetic.export/files/mcp-export/a\\b.json",
        "/sdcard/Android/data/org.example.synthetic.export/files/mcp-export/é.json",
        "/sdcard/Android/data/org.example.synthetic.export/files/mcp-export/\\u202e.json",
        "/sdcard/Android/data/org.example.synthetic.export/files/mcp-export/x.json\0",
        "/sdcard/Android/data/org.example.synthetic.export/files/mcp-export/x.json\n",
        "/sdcard/Android/data/org.example.synthetic.export/files/mcp-export/x.json;--",
        "/sdcard/Android/data/org.example.synthetic.export/files/mcp-export/a.zip",
        "/sdcard/Android/data/org.example.synthetic.export/files/mcp-export/report.json/",
        "/sdcard/Android/data/other.app/files/mcp-export/report.json",
    ],
)
def test_t_h4d_03_traversal_unicode_controls_and_root_spoofing_rejected(
    tmp_path: Path,
    path: str,
) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)
    try:
        result = pull(worker, handle, lid, path=path)
        assert result["status"] == "blocked"
        assert result["errors"][0]["code"] == "SOURCE_DENIED"
        assert store.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


def test_t_h4d_04_remote_frame_cannot_choose_output_or_symlink(tmp_path: Path) -> None:
    from android_mcp_host.synthetic_file_pull import FilePullFrame

    worker, live, jobs, store, handle, lid = builder(tmp_path)
    worker._fixture = lambda name, ah, job, package, path, timeout, cap, stop: FilePullFrame(
        FILE,
        name,
        ah,
        job,
        package,
        "/data/local/tmp/unapproved-output",
        MIME,
        DIGEST,
        True,
        False,
        True,
    )
    try:
        denied = pull(worker, handle, lid)
        assert denied["status"] == "failed"
        assert denied["artifact_handle"] is None
        assert store.list_metadata(ART_OWNER) == []
        with pytest.raises(TypeError):
            worker.submit(
                "pull",
                NAME,
                handle,
                lid,
                REMOTE,
                expected_sha256=DIGEST,
                output_path=str(tmp_path / "user-home"),
            )
        assert not (tmp_path / "user-home").exists()
    finally:
        live.shutdown()


def test_t_h4d_05_partial_bad_checksum_timeout_or_disconnect_no_artifact(
    tmp_path: Path,
) -> None:
    from android_mcp_host.synthetic_file_pull import FilePullFrame

    def partial(
        name: str,
        ah: str,
        lid: str,
        package: str,
        path: str,
        timeout: float,
        cap: int,
        stop: threading.Event,
    ) -> FilePullFrame:
        return FilePullFrame(
            FILE[:10], name, ah, lid, package, path, MIME, DIGEST, True, True, True
        )

    worker, live, jobs, store, handle, lid = builder(tmp_path, backend=partial)
    try:
        result = pull(worker, handle, lid)
        assert result["status"] == "failed"
        assert result["artifact_handle"] is None
        assert store.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "failed"
    finally:
        live.shutdown()

    def timeout(*args: Any) -> Any:
        raise subprocess.TimeoutExpired(["fixture-pull"], 0.1)

    worker, live, jobs, store, handle, lid = builder(tmp_path / "second", backend=timeout)
    try:
        uncertain = pull(worker, handle, lid)
        assert uncertain["status"] == "uncertain"
        assert uncertain["errors"][0]["code"] == "TIMEOUT"
        assert store.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, uncertain["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_t_h4d_06_fastmcp_private_contract_default_only_plans(tmp_path: Path) -> None:
    from android_mcp_host.synthetic_file_pull import get_file_pull_schema

    worker, live, jobs, store, handle, lid = builder(tmp_path, active=False, consent=False)

    async def verify() -> None:
        async with Client(create_server()) as base:
            original = {tool.name: tool for tool in await base.list_tools()}
        async with Client(create_server(file_pull_worker=worker)) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert set(tools) == {*original, "host_file_pull"}
            assert all(tools[key] == original[key] for key in original)
            tool = tools["host_file_pull"]
            schema = get_file_pull_schema()
            Draft202012Validator.check_schema(schema)
            assert tool.output_schema == schema
            hints = tool.annotations.model_dump(mode="json", by_alias=True)
            assert hints["readOnlyHint"] is False
            assert hints["destructiveHint"] is True
            assert hints["openWorldHint"] is False
            planned = await client.call_tool(
                "host_file_pull",
                {
                    "action": "plan",
                    "avd_name": NAME,
                    "avd_handle": handle,
                    "lifecycle_job_id": lid,
                    "remote_path": REMOTE,
                },
            )
            assert planned.structured_content["status"] == "planned"
            denied = await client.call_tool(
                "host_file_pull",
                {
                    "action": "pull",
                    "avd_name": NAME,
                    "avd_handle": handle,
                    "lifecycle_job_id": lid,
                    "remote_path": REMOTE,
                    "expected_sha256": DIGEST,
                    "mime_type": MIME,
                    "request_id": REQUEST,
                },
            )
            assert denied.structured_content["status"] == "blocked"
            assert denied.structured_content["errors"][0]["code"] == "CONSENT_REQUIRED"
            assert denied.structured_content["artifact_handle"] is None
            assert denied.structured_content["real_pull_enabled"] is False
            Draft202012Validator(schema).validate(denied.structured_content)

    try:
        asyncio.run(verify())
    finally:
        live.shutdown()
