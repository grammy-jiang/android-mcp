"""H4.e mandatory test-only approved signed-file import into private synthetic AVD."""

from __future__ import annotations

import asyncio
import hashlib
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

PACKAGE = "org.example.synthetic.export"
DEST = f"/sdcard/Android/data/{PACKAGE}/files/mcp-import/fixture.bin"
ART_OWNER = "synthetic-push-private"
DATA = b"owned private synthetic app import fixture bytes"
SHA = hashlib.sha256(DATA).hexdigest()
MIME = "application/octet-stream"
KEY = b"k" * 32
REQ = "synthetic-app-file-push-001"


def builder(
    tmp_path: Path, *, active: bool = True, approved: bool = True, writer: Any = None
) -> tuple[Any, Any, Any, PrivateArtifactStore, str, str, str, dict[str, bytes]]:
    from android_mcp_host.file_push_support import fixture_signature
    from android_mcp_host.synthetic_file_push import FilePushService, PushApproval, PushFrame

    live, handle, jobs, _ = engine(tmp_path, backend=active, readiness_timeout=5.0)
    lid = "job_" + "z" * 32
    if active:
        started = live.run("start", NAME, handle, request_id=START_REQUEST)
        assert started["status"] == "ok"
        lid = started["job_id"]
    store = PrivateArtifactStore(tmp_path / "private-push-artifacts")
    artifact = store.put(ART_OWNER, DATA, mime_type=MIME, ttl_s=120)
    token = artifact["handle"]
    signature = fixture_signature(
        KEY,
        OWNER,
        handle,
        lid,
        PACKAGE,
        DEST,
        token,
        SHA,
        MIME,
    )
    grant = (
        PushApproval(
            OWNER,
            handle,
            lid,
            PACKAGE,
            DEST,
            token,
            SHA,
            MIME,
            "synthetic-atomic-app-import",
            signature,
            time.time() + 120,
        )
        if approved
        else None
    )
    simulated_fs: dict[str, bytes] = {}
    if writer is None:

        def writer(
            name: str,
            target: str,
            lid: str,
            package: str,
            destination: str,
            payload: bytes,
            limit: int,
            stop: threading.Event,
        ) -> PushFrame:
            assert not stop.is_set()
            assert limit == 262144
            assert destination not in simulated_fs
            simulated_fs[destination] = payload
            return PushFrame(
                name,
                target,
                lid,
                package,
                destination,
                hashlib.sha256(payload).hexdigest(),
                len(payload),
                True,
                True,
                False,
                False,
                True,
            )

    worker = FilePushService(
        live.provisioner,
        live,
        jobs,
        store,
        owner=OWNER,
        artifact_owner=ART_OWNER,
        package_id=PACKAGE,
        approval=grant,
        fixture_hmac_key=KEY,
        fixture_writer=writer,
    )
    return worker, live, jobs, store, handle, lid, token, simulated_fs


def run_push(
    worker: Any,
    target: str,
    lid: str,
    artifact_handle: str,
    *,
    dest: str = DEST,
    request: str = REQ,
    expected: str = SHA,
    action: str = "push",
    max_bytes: int = 262144,
    mime: str = MIME,
) -> dict[str, Any]:
    return worker.submit(
        action,
        NAME,
        target,
        lid,
        artifact_handle,
        expected,
        dest,
        mime_type=mime,
        max_bytes=max_bytes,
        request_id=request,
    )


def test_t_h4e_01_attested_source_imports_once_with_private_receipt(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path)
    try:
        result = run_push(worker, handle, lid, token)
        assert result["status"] == "simulated"
        assert result["push_state"] == "imported_synthetic"
        assert result["job_id"].startswith("job_")
        assert result["report_handle"].startswith("art_")
        assert result["artifact_sha256"] == SHA
        assert result["bytes_written"] == len(DATA)
        assert result["destination_filename"] == "fixture.bin"
        assert result["synthetic_signature_provenance"] == "synthetic_hmac_fixture_only"
        assert result["real_push_enabled"] is False
        assert result["physical_device_writes_enabled"] is False
        assert fs == {DEST: DATA}
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "succeeded"
        assert store.public_metadata(ART_OWNER, result["report_handle"])["status"] == "ok"
        assert run_push(worker, handle, lid, token) == result
        assert fs == {DEST: DATA}
    finally:
        live.shutdown()


def test_t_h4e_02_physical_target_and_missing_grant_are_mutation_disabled(tmp_path: Path) -> None:
    calls = [0]

    def never(*args: Any) -> Any:
        calls[0] += 1
        pytest.fail("Mutation must be denied")

    worker, live, jobs, store, handle, lid, token, fs = builder(
        tmp_path,
        approved=False,
        writer=never,
    )
    try:
        denied = run_push(worker, handle, lid, token)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "MUTATION_DISABLED"
        assert run_push(worker, "physical-serial", lid, token)["status"] == "blocked"
        assert calls == [0]
        assert fs == {}
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "path",
    [
        "/system/bin/fake",
        "/data/data/org.example.synthetic.export/databases/secrets.db",
        "/sdcard/Download/not-approved.bin",
        "/sdcard/Android/data/org.example.synthetic.export/files/mcp-import/../other.bin",
        "/sdcard/Android/data/org.example.synthetic.export/files/mcp-import/a/b.bin",
        "/sdcard/Android/data/org.example.synthetic.export/files/mcp-import//double.bin",
        "/sdcard/Android/data/org.example.synthetic.export/files/mcp-import/é.bin",
        "/sdcard/Android/data/org.example.synthetic.export/files/mcp-import/.hidden",
        "/sdcard/Android/data/org.example.synthetic.export/files/mcp-import/file.bin\n",
        "/sdcard/Android/data/org.example.synthetic.export/files/mcp-import/file.bin\0",
        "/sdcard/Android/data/org.example.synthetic.export/files/mcp-import/file.bin;",
        "/sdcard/Android/data/org.example.synthetic.export/files/mcp-import/file.zip",
        "/sdcard/Android/data/foreign/files/mcp-import/fixture.bin",
    ],
)
def test_t_h4e_03_remote_path_traversal_symlinks_and_shell_flags_denied(
    tmp_path: Path,
    path: str,
) -> None:
    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path)
    try:
        denied = run_push(worker, handle, lid, token, dest=path)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "DESTINATION_DENIED"
        assert fs == {}
    finally:
        live.shutdown()


def test_t_h4e_04_wrong_owner_digest_mime_and_size_denied_before_writer(
    tmp_path: Path,
) -> None:
    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path)
    worker._writer = lambda *args: pytest.fail("Invalid private artifact sent to writer")
    try:
        for bad in (
            run_push(worker, handle, lid, "art_" + "x" * 32),
            run_push(worker, handle, lid, token, expected="0" * 64),
            run_push(worker, handle, lid, token, mime="application/json"),
            run_push(worker, handle, lid, token, max_bytes=8),
        ):
            assert bad["status"] == "blocked"
            assert bad["report_handle"] is None
        assert fs == {}
    finally:
        live.shutdown()


def test_t_h4e_05_partial_timeout_and_duplicate_safe_no_overwrite(
    tmp_path: Path,
) -> None:
    from android_mcp_host.synthetic_file_push import PushFrame

    def partial(
        name: str,
        target: str,
        lid: str,
        package: str,
        dest: str,
        payload: bytes,
        cap: int,
        stop: threading.Event,
    ) -> PushFrame:
        return PushFrame(
            name,
            target,
            lid,
            package,
            dest,
            SHA,
            len(payload) // 2,
            False,
            False,
            False,
            False,
            True,
        )

    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path, writer=partial)
    try:
        first = run_push(worker, handle, lid, token)
        assert first["status"] == "uncertain"
        assert first["report_handle"] is None
        assert run_push(worker, handle, lid, token)["job_id"] == first["job_id"]
        assert jobs.status(OWNER, first["job_id"])["job"]["state"] == "uncertain"
        assert fs == {}
    finally:
        live.shutdown()

    def hung(*args: Any) -> Any:
        raise subprocess.TimeoutExpired(["synthetic-push-only"], 0.1)

    worker, live, jobs, store, handle, lid, token, fs = builder(
        tmp_path / "second",
        writer=hung,
    )
    try:
        failed = run_push(worker, handle, lid, token)
        assert failed["status"] == "uncertain"
        assert failed["errors"][0]["code"] == "TIMEOUT"
        assert fs == {}
    finally:
        live.shutdown()


def test_t_h4e_06_fastmcp_plan_only_and_mutation_annotations(tmp_path: Path) -> None:
    from android_mcp_host.synthetic_file_push import get_file_push_schema

    worker, live, jobs, store, handle, lid, token, fs = builder(
        tmp_path,
        active=False,
        approved=False,
    )

    async def verify() -> None:
        async with Client(create_server()) as baseline:
            originals = {t.name: t for t in await baseline.list_tools()}
        async with Client(create_server(file_push_worker=worker)) as client:
            tools = {t.name: t for t in await client.list_tools()}
            assert set(tools) == {*originals, "host_file_push"}
            assert all(tools[key] == originals[key] for key in originals)
            tool = tools["host_file_push"]
            Draft202012Validator.check_schema(tool.output_schema)
            assert tool.output_schema == get_file_push_schema()
            hints = tool.annotations.model_dump(mode="json", by_alias=True)
            assert hints["readOnlyHint"] is False
            assert hints["destructiveHint"] is True
            assert hints["openWorldHint"] is False
            plan = await client.call_tool(
                "host_file_push",
                {
                    "action": "plan",
                    "avd_name": NAME,
                    "avd_handle": handle,
                    "lifecycle_job_id": lid,
                    "artifact_handle": token,
                    "artifact_sha256": SHA,
                    "destination_path": DEST,
                },
            )
            assert plan.structured_content["status"] == "planned"
            denied = await client.call_tool(
                "host_file_push",
                {
                    "action": "push",
                    "avd_name": NAME,
                    "avd_handle": handle,
                    "lifecycle_job_id": lid,
                    "artifact_handle": token,
                    "artifact_sha256": SHA,
                    "destination_path": DEST,
                    "request_id": REQ,
                },
            )
            assert denied.structured_content["status"] == "blocked"
            assert denied.structured_content["errors"][0]["code"] == "MUTATION_DISABLED"
            assert denied.structured_content["real_push_enabled"] is False
            Draft202012Validator(get_file_push_schema()).validate(denied.structured_content)

    try:
        asyncio.run(verify())
    finally:
        live.shutdown()
