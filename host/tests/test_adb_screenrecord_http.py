"""H4.c controlled CLI composition and genuine localhost MCP recording denial."""

from __future__ import annotations

import asyncio
import hashlib
import json
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator
from test_adb_screenrecord_job import ART_OWNER, REQ, mp4_fixture
from test_avd_provisioning import LICENSE, NAME, OWNER, SOURCE, SYSTEM, provider
from test_emulator_lifecycle_cli import make_flags

from android_mcp_host import cli
from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.private_artifact_support import ArtifactStoreError
from android_mcp_host.synthetic_screenrecord import ScreenRecordService, get_screenrecord_schema


def cli_flags(tmp_path: Path) -> list[str]:
    return [
        *make_flags(tmp_path),
        "--artifact-metadata",
        "--artifact-root",
        str(tmp_path / "screenrecord-private"),
        "--artifact-owner",
        ART_OWNER,
        "--screenrecord-plan",
    ]


def test_screenrecord_cli_requires_private_operator_pins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    class Stub:
        def run(self, **kwargs: Any) -> None:
            assert kwargs == {"transport": "http", "host": "127.0.0.1", "port": 8765}

    with monkeypatch.context() as patch:
        patch.setattr(cli.platform, "system", lambda: "Linux")
        patch.setattr(cli, "create_server", lambda **kw: calls.append(kw) or Stub())
        assert cli.main(["serve"]) == 0
        assert calls == [{}]
        calls.clear()
        for bad in (
            ["serve", "--screenrecord-plan"],
            ["serve", "--screenrecord-plan", "--artifact-metadata"],
            ["serve", "--screenrecord-plan", "--emulator-lifecycle-plan"],
            ["serve", "--screenrecord-plan", "--avd-provision"],
        ):
            with pytest.raises(SystemExit) as exc:
                cli.main(bad)
            assert exc.value.code == 2
            assert calls == []
        flags = cli_flags(tmp_path)
        assert cli.main(flags) == 0
        assert len(calls) == 1
        worker = calls[0]["screenrecord_worker"]
        assert isinstance(worker, ScreenRecordService)
        assert worker._fixture is None
        assert worker._approval is None
        assert worker._owner == OWNER
        assert worker._artifact_owner == ART_OWNER


def test_record_cli_cross_owner_rejected_before_creating_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad = cli_flags(tmp_path)
    bad[bad.index("--job-owner") + 1] = "foreign"
    with monkeypatch.context() as patch:
        patch.setattr(cli.platform, "system", lambda: "Linux")
        with pytest.raises(SystemExit) as e:
            cli.main(bad)
    assert e.value.code == 2
    assert not (tmp_path / "owned-avds").exists()
    assert not (tmp_path / "jobs").exists()


def test_private_store_video_mime_rejects_invalid_envelopes_and_is_owner_scoped(
    tmp_path: Path,
) -> None:
    artifacts = PrivateArtifactStore(tmp_path / "media")
    approved = artifacts.put(ART_OWNER, mp4_fixture(), mime_type="video/mp4", ttl_s=90)
    assert approved["mime_type"] == "video/mp4"
    assert artifacts.public_metadata(ART_OWNER, approved["handle"])["status"] == "ok"
    assert artifacts.public_metadata("wrong-owner", approved["handle"])["status"] == "not_found"
    with pytest.raises(ArtifactStoreError) as exc:
        artifacts.put(ART_OWNER, b"not an mp4", mime_type="video/mp4")
    assert exc.value.code == "MIME_MISMATCH"
    assert artifacts.list_metadata(ART_OWNER) == [approved]


def test_actual_localhost_http_recording_is_disabled_without_grant(tmp_path: Path) -> None:
    owner = provider(tmp_path)
    created = owner.provision("create", NAME)
    assert created["status"] == "created"
    handle = created["avd"]["handle"]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    program = (
        "from pathlib import Path\nimport sys\n"
        "from android_mcp_host.server import create_server\n"
        "from android_mcp_host.avd_provisioning import AvdProvisioner\n"
        "from android_mcp_host.durable_jobs import DurableJobStore\n"
        "from android_mcp_host.emulator_lifecycle import EmulatorLifecycle\n"
        "from android_mcp_host.private_artifact_store import PrivateArtifactStore\n"
        "from android_mcp_host.synthetic_screenrecord import ScreenRecordService\n"
        "root=Path(sys.argv[1]);sdk=Path(sys.argv[2]);jobsroot=Path(sys.argv[3])\n"
        "artroot=Path(sys.argv[4]);owner=sys.argv[5];artowner=sys.argv[6]\n"
        "avd=AvdProvisioner(root,sdk,owner,api=36,abi='arm64-v8a',"
        "source_properties_sha256=sys.argv[7],"
        "system_image_sha256=sys.argv[8],license_sha256=sys.argv[9])\n"
        "jobs=DurableJobStore(jobsroot)\n"
        "live=EmulatorLifecycle(avd,jobs,owner=owner)\n"
        "art=PrivateArtifactStore(artroot)\n"
        "record=ScreenRecordService(avd,live,jobs,art,owner=owner,artifact_owner=artowner)\n"
        "create_server(screenrecord_worker=record).run("
        "transport='http',host='127.0.0.1',port=int(sys.argv[10]))\n"
    )
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            program,
            str(tmp_path / "owned-avds"),
            str(tmp_path / "synthetic-sdk"),
            str(tmp_path / "jobs"),
            str(tmp_path / "record-private"),
            OWNER,
            ART_OWNER,
            hashlib.sha256(SOURCE).hexdigest(),
            hashlib.sha256(SYSTEM).hexdigest(),
            hashlib.sha256(LICENSE).hexdigest(),
            str(port),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def inspect() -> None:
        last: Exception | None = None
        for _ in range(55):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    tools = {t.name: t for t in await client.list_tools()}
                    assert set(tools) == {
                        "device_status",
                        "adb_observe",
                        "adb_develop",
                        "host_screenrecord",
                    }
                    t = tools["host_screenrecord"]
                    assert t.output_schema == get_screenrecord_schema()
                    flags = t.annotations.model_dump(mode="json", by_alias=True)
                    assert flags["destructiveHint"] is True
                    assert flags["readOnlyHint"] is False
                    assert flags["openWorldHint"] is False
                    assert "sensitive" in t.description.lower()
                    target = {
                        "avd_name": NAME,
                        "avd_handle": handle,
                        "lifecycle_job_id": "job_" + "z" * 32,
                    }
                    plan = await client.call_tool("host_screenrecord", {"action": "plan", **target})
                    assert plan.structured_content["status"] == "planned"
                    denied = await client.call_tool(
                        "host_screenrecord", {"action": "record", **target, "request_id": REQ}
                    )
                    assert not denied.is_error
                    val = denied.structured_content
                    Draft202012Validator(get_screenrecord_schema()).validate(val)
                    assert val["status"] == "blocked"
                    assert val["errors"][0]["code"] == "CONSENT_REQUIRED"
                    assert val["artifact_handle"] is None
                    assert val["receipt_handle"] is None
                    assert val["real_recording_enabled"] is False
                    assert val["raw_media_returned"] is False
                    raw = json.dumps(val)
                    assert str(tmp_path) not in raw
                    assert mp4_fixture().hex() not in raw
                    assert OWNER not in raw
                    return
            except Exception as err:
                last = err
                await asyncio.sleep(0.1)
        raise AssertionError(f"Private video HTTP MCP unavailable: {type(last).__name__}")

    try:
        asyncio.run(inspect())
    finally:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
    assert child.poll() is not None
