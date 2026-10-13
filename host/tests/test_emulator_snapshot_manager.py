"""Six mandated H3.d fake snapshot ownership, restore, and MCP conformance cases."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator
from test_avd_provisioning import NAME, OWNER, provider

from android_mcp_host.durable_jobs import DurableJobStore
from android_mcp_host.server import create_server

SNAP = "snap_clean_boot"
REQ = "snapshot-creation-001"


def fixture(tmp_path: Path) -> tuple[Any, str, DurableJobStore]:
    from android_mcp_host.emulator_snapshot_manager import EmulatorSnapshotManager

    provisioner = provider(tmp_path)
    avd = provisioner.provision("create", NAME)
    assert avd["status"] == "created"
    jobs = DurableJobStore(tmp_path / "jobs", lease_seconds=90)
    manager = EmulatorSnapshotManager(provisioner, jobs, owner=OWNER)
    return manager, avd["avd"]["handle"], jobs


def test_t_h3d_01_create_list_simulated_restore_image_bound(tmp_path: Path) -> None:
    manager, handle, jobs = fixture(tmp_path)
    created = manager.operate("create", NAME, handle, SNAP, request_id=REQ)
    assert created["status"] == "created"
    assert created["snapshot"]["name"] == SNAP
    assert created["snapshot"]["handle"].startswith("mcpsnap_")
    assert (
        created["snapshot"]["image_sha256"]
        == manager.provisioner.verify_owned(NAME, handle)["artifact_sha256"]
    )
    assert created["target"] == "disposable_emulator_only"
    assert created["real_snapshot_execution_enabled"] is False
    assert created["physical_device_writes_enabled"] is False
    assert created["job_id"].startswith("job_")
    assert jobs.status(OWNER, created["job_id"])["job"]["state"] == "succeeded"

    listed = manager.operate("list", NAME, handle)
    assert listed["status"] == "ok"
    assert listed["snapshots"] == [created["snapshot"]]
    restored = manager.operate(
        "restore",
        NAME,
        handle,
        SNAP,
        snapshot_handle=created["snapshot"]["handle"],
        request_id="snapshot-restore-001",
    )
    assert restored["status"] == "simulated"
    assert restored["possible_emulator_state_change"] is False
    assert restored["snapshot"] == created["snapshot"]
    assert jobs.status(OWNER, restored["job_id"])["job"]["state"] == "succeeded"
    assert str(tmp_path) not in json.dumps(restored)
    assert OWNER not in json.dumps(restored)


def test_t_h3d_02_never_touch_another_avd_or_preexisting_snapshot(tmp_path: Path) -> None:
    manager, handle, jobs = fixture(tmp_path)
    for name, avd_handle in (
        ("android_mcp_native_api36", handle),
        (NAME, "mcpavd_" + "x" * 32),
    ):
        result = manager.operate("create", name, avd_handle, SNAP, request_id=REQ)
        assert result["status"] == "blocked"
    root = tmp_path / "owned-avds"
    previous = root / f".mcp-snapshot-{NAME}-{SNAP}.json"
    previous.write_bytes(b"PRE-EXISTING USER SNAPSHOT")
    denied = manager.operate("create", NAME, handle, SNAP, request_id=REQ)
    assert denied["status"] == "blocked"
    assert previous.read_bytes() == b"PRE-EXISTING USER SNAPSHOT"
    assert (
        manager.operate(
            "delete",
            NAME,
            handle,
            SNAP,
            snapshot_handle="mcpsnap_" + "x" * 32,
            request_id="delete-preexisting-001",
        )["status"]
        == "blocked"
    )
    assert previous.exists()


def test_t_h3d_03_invalid_snapshot_paths_and_version_are_denied(tmp_path: Path) -> None:
    manager, handle, jobs = fixture(tmp_path)
    for snap in ("../bad", "/absolute", "-snapshot", "spaces are bad", "x" * 100):
        denied = manager.operate("create", NAME, handle, snap, request_id=REQ)
        assert denied["status"] == "blocked"
    result = manager.operate("create", NAME, handle, SNAP, request_id=REQ)
    assert result["status"] == "created"
    record = tmp_path / "owned-avds" / f".mcp-snapshot-{NAME}-{SNAP}.json"
    blob = json.loads(record.read_text())
    blob["snapshot_version"] = 999
    record.write_text(json.dumps(blob), encoding="utf-8")
    restored = manager.operate(
        "restore",
        NAME,
        handle,
        SNAP,
        snapshot_handle=result["snapshot"]["handle"],
        request_id="restore-corrupt-version",
    )
    assert restored["status"] == "blocked"
    assert record.exists()


def test_t_h3d_04_incompatible_image_api_abi_never_migrated(tmp_path: Path) -> None:
    manager, handle, jobs = fixture(tmp_path)
    initial = manager.operate("create", NAME, handle, SNAP, request_id=REQ)
    assert initial["status"] == "created"
    path = tmp_path / "owned-avds" / f".mcp-snapshot-{NAME}-{SNAP}.json"
    sealed = path.read_bytes()
    for changed in ("image_sha256", "api", "abi"):
        payload = json.loads(sealed)
        payload[changed] = (
            "a" * 64 if changed == "image_sha256" else (30 if changed == "api" else "x86_64")
        )
        path.write_text(json.dumps(payload))
        denied = manager.operate(
            "restore",
            NAME,
            handle,
            SNAP,
            snapshot_handle=initial["snapshot"]["handle"],
            request_id=f"incompatible-{changed}",
        )
        assert denied["status"] == "blocked"
    path.write_bytes(sealed)
    assert manager.operate("list", NAME, handle)["status"] == "ok"


def test_t_h3d_05_faults_timeout_and_cancel_preserve_previous_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import android_mcp_host.emulator_snapshot_manager as module

    manager, handle, jobs = fixture(tmp_path)
    first = manager.operate("create", NAME, handle, SNAP, request_id=REQ)
    assert first["status"] == "created"
    path = tmp_path / "owned-avds" / f".mcp-snapshot-{NAME}-{SNAP}.json"
    previous = path.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(
            module, "_write_owned", lambda *args: (_ for _ in ()).throw(OSError("disk full"))
        )
        failed = manager.operate(
            "create", NAME, handle, "snap_second", request_id="storage-failure"
        )
    assert failed["status"] == "failed"
    assert path.read_bytes() == previous
    assert jobs.status(OWNER, failed["job_id"])["job"]["state"] == "failed"
    with monkeypatch.context() as patch:
        patch.setattr(
            module,
            "_before_mutation",
            lambda *args: (_ for _ in ()).throw(
                subprocess.TimeoutExpired(["synthetic-snapshot"], 0.1)
            ),
        )
        uncertain = manager.operate(
            "create", NAME, handle, "snap_timeout", request_id="timeout-req"
        )
    assert uncertain["status"] == "uncertain"
    assert path.read_bytes() == previous
    assert jobs.status(OWNER, uncertain["job_id"])["job"]["state"] == "uncertain"
    assert (
        manager.operate("create", NAME, handle, "snap_third", request_id="after-timeout")["status"]
        == "blocked"
    )
    assert manager.operate(
        "cancel", NAME, handle, SNAP, request_id=REQ, job_id=uncertain["job_id"]
    )["status"] in {"uncertain", "blocked"}


def test_t_h3d_06_mcp_synthetic_provenance_and_default_catalog(tmp_path: Path) -> None:
    from android_mcp_host.emulator_snapshot_manager import get_snapshot_output_schema

    manager, handle, jobs = fixture(tmp_path)

    async def verify() -> None:
        async with Client(create_server()) as baseline:
            old = {tool.name: tool for tool in await baseline.list_tools()}
        async with Client(create_server(snapshot_manager=manager)) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert set(tools) == {*old, "host_emulator_snapshot"}
            assert all(tools[name] == old[name] for name in old)
            contract = get_snapshot_output_schema()
            Draft202012Validator.check_schema(contract)
            assert tools["host_emulator_snapshot"].output_schema == contract
            hints = tools["host_emulator_snapshot"].annotations.model_dump(
                mode="json", by_alias=True
            )
            assert hints["destructiveHint"] is True
            plan = await client.call_tool(
                "host_emulator_snapshot",
                {
                    "action": "fault_plan",
                    "avd_name": NAME,
                    "avd_handle": handle,
                    "condition": "boot_delay",
                },
            )
            assert not plan.is_error
            assert plan.structured_content["status"] == "planned"
            assert plan.structured_content["possible_emulator_state_change"] is False
            Draft202012Validator(contract).validate(plan.structured_content)
            assert str(tmp_path) not in json.dumps(plan.structured_content)

    asyncio.run(verify())
    assert jobs.list_status(OWNER) == []
