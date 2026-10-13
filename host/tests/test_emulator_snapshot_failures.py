"""Durable-job and filesystem failures for private synthetic snapshot records."""

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
from test_avd_provisioning import ABI, LICENSE, NAME, OWNER, SOURCE, SYSTEM, provider
from test_emulator_snapshot_manager import REQ, SNAP, fixture

import android_mcp_host.emulator_snapshot_manager as module
import android_mcp_host.emulator_snapshot_support as support
from android_mcp_host import cli
from android_mcp_host.avd_provision_support import provision_lock, root_key
from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.durable_jobs import DurableJobStore


def test_invalid_owner_is_rejected_at_composition(tmp_path: Path) -> None:
    p = provider(tmp_path)
    ledger = DurableJobStore(tmp_path / "jobs")
    with pytest.raises(ValueError, match="Snapshot owner"):
        module.EmulatorSnapshotManager(p, ledger, owner="foreign-owner")
    assert ledger.list_status(OWNER) == []


def test_nonobject_schema_is_not_advertised(monkeypatch: pytest.MonkeyPatch) -> None:
    class Resource:
        def joinpath(self, name: str) -> Resource:
            assert name == "host-emulator-snapshot.v1.schema.json"
            return self

        def read_text(self, encoding: str) -> str:
            assert encoding == "utf-8"
            return "[]"

    monkeypatch.setattr(module, "files", lambda _: Resource())
    with pytest.raises(ValueError, match="Invalid packaged"):
        module.get_snapshot_output_schema()


def test_invalid_requests_do_not_reserve_jobs_or_create_private_files(tmp_path: Path) -> None:
    manager, handle, jobs = fixture(tmp_path)
    trials = (
        ("launch", NAME, handle, SNAP, REQ),
        ("create", NAME, handle, "../outside", REQ),
        ("create", NAME, handle, SNAP, ""),
        ("create", NAME, handle, SNAP, "bad/id"),
        ("restore", NAME, handle, SNAP, REQ),
    )
    for action, name, avd_handle, snap, request in trials:
        result = manager.operate(action, name, avd_handle, snap, request_id=request)
        assert result["status"] == "blocked"
    assert (
        manager.operate("fault_plan", NAME, handle, condition="unknown_condition")["status"]
        == "blocked"
    )
    assert (
        manager.operate("create", "user_native_avd", handle, SNAP, request_id=REQ)["status"]
        == "blocked"
    )
    assert jobs.list_status(OWNER) == []
    assert not list((tmp_path / "owned-avds").glob(".mcp-snapshot-*"))


def test_existing_snapshot_with_absent_or_wrong_handle_is_not_restored(tmp_path: Path) -> None:
    manager, handle, jobs = fixture(tmp_path)
    initial = manager.operate("create", NAME, handle, SNAP, request_id=REQ)
    assert initial["status"] == "created"
    for action in ("restore", "delete"):
        assert (
            manager.operate(action, NAME, handle, SNAP, request_id=f"missing-handle-{action}")[
                "status"
            ]
            == "blocked"
        )
    missing = manager.operate(
        "restore",
        NAME,
        handle,
        "snap_missing",
        snapshot_handle=initial["snapshot"]["handle"],
        request_id="missing-snapshot",
    )
    assert missing["status"] == "blocked"


def test_finished_requests_return_stable_results_without_new_claim(tmp_path: Path) -> None:
    manager, handle, jobs = fixture(tmp_path)
    created = manager.operate("create", NAME, handle, SNAP, request_id=REQ)
    assert created["status"] == "created"
    assert manager.operate("create", NAME, handle, SNAP, request_id=REQ)["status"] == "existing"
    restored = manager.operate(
        "restore",
        NAME,
        handle,
        SNAP,
        snapshot_handle=created["snapshot"]["handle"],
        request_id="restore-repeat",
    )
    assert restored["status"] == "simulated"
    assert (
        manager.operate(
            "restore",
            NAME,
            handle,
            SNAP,
            snapshot_handle=created["snapshot"]["handle"],
            request_id="restore-repeat",
        )["status"]
        == "simulated"
    )
    deleted = manager.operate(
        "delete",
        NAME,
        handle,
        SNAP,
        snapshot_handle=created["snapshot"]["handle"],
        request_id="delete-repeat",
    )
    assert deleted["status"] == "deleted"
    assert (
        manager.operate(
            "delete",
            NAME,
            handle,
            SNAP,
            snapshot_handle=created["snapshot"]["handle"],
            request_id="delete-repeat",
        )["status"]
        == "deleted"
    )
    assert jobs.status(OWNER, created["job_id"])["job"]["attempts"] == 1
    assert len(jobs.list_status(OWNER)) == 3


def test_request_reuse_with_different_plan_is_denied(tmp_path: Path) -> None:
    manager, handle, jobs = fixture(tmp_path)
    assert manager.operate("create", NAME, handle, SNAP, request_id=REQ)["status"] == "created"
    reused = manager.operate("create", NAME, handle, "snap_second", request_id=REQ)
    assert reused["status"] == "blocked"
    assert reused["errors"][0]["code"] == "IDEMPOTENCY_CONFLICT"
    assert len(jobs.list_status(OWNER)) == 1


def test_durable_storage_failure_is_generic_and_blocks_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, handle, jobs = fixture(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(
            jobs,
            "lookup_request",
            lambda *args: (_ for _ in ()).throw(JobStoreError("PRIVATE-SECRET-STORAGE-ERROR")),
        )
        result = manager.operate("create", NAME, handle, SNAP, request_id=REQ)
    assert result["status"] == "blocked"
    assert result["errors"][0]["code"] == "JOB_UNAVAILABLE"
    assert "PRIVATE-SECRET" not in json.dumps(result)
    assert jobs.list_status(OWNER) == []


def test_running_unfinished_job_imposes_recovery_fence(tmp_path: Path) -> None:
    manager, handle, jobs = fixture(tmp_path)
    info = manager.provisioner.verify_owned(NAME, handle)
    assert info is not None
    digest = manager._plan_digest("create", info, SNAP)
    prior = jobs.prepare(OWNER, REQ, digest, identity=handle, authorized=True)
    jobs.queue(OWNER, prior["job_id"], identity=handle, authorized=True)
    jobs.claim(OWNER, prior["job_id"], "crashed-worker", handle, authorized=True)
    denied = manager.operate("create", NAME, handle, "snap_new", request_id="next-snapshot")
    assert denied["status"] == "blocked"
    assert denied["errors"][0]["code"] == "RECOVERY_REQUIRED"
    assert not list((tmp_path / "owned-avds").glob(".mcp-snapshot-*"))


def test_failed_journal_finalization_never_repeats_written_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, handle, jobs = fixture(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(
            jobs,
            "complete",
            lambda *args, **kwargs: (_ for _ in ()).throw(JobStoreError("STALE_WORKER")),
        )
        result = manager.operate("create", NAME, handle, SNAP, request_id=REQ)
    assert result["status"] == "uncertain"
    path = tmp_path / "owned-avds" / f".mcp-snapshot-{NAME}-{SNAP}.json"
    assert path.exists()
    assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"
    assert manager.operate("create", NAME, handle, SNAP, request_id=REQ)["status"] == "uncertain"
    assert (
        manager.operate("create", NAME, handle, "snap_unrelated", request_id="new-after-uncertain")[
            "status"
        ]
        == "blocked"
    )


def test_partial_file_failure_is_uncertain_and_never_overwrites_prior_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, handle, jobs = fixture(tmp_path)
    initial = manager.operate("create", NAME, handle, SNAP, request_id=REQ)
    assert initial["status"] == "created"
    first = tmp_path / "owned-avds" / f".mcp-snapshot-{NAME}-{SNAP}.json"
    before = first.read_bytes()

    def partial(path: Path, content: bytes) -> None:
        path.write_bytes(b"incomplete-record")
        raise OSError("interrupted-write")

    with monkeypatch.context() as patch:
        patch.setattr(module, "_write_owned", partial)
        outcome = manager.operate(
            "create", NAME, handle, "snap_partial", request_id="partial-create"
        )
    assert outcome["status"] == "uncertain"
    assert first.read_bytes() == before
    assert jobs.status(OWNER, outcome["job_id"])["job"]["state"] == "uncertain"
    assert manager.operate("list", NAME, handle)["status"] == "blocked"


def test_approval_rechecked_within_private_lock_before_each_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, handle, jobs = fixture(tmp_path)
    original = manager.provisioner._record
    calls = [0]

    def flip(name: str, secret: bytes) -> dict[str, Any] | None:
        calls[0] += 1
        return original(name, secret) if calls[0] == 1 else None

    with monkeypatch.context() as patch:
        patch.setattr(manager.provisioner, "_record", flip)
        denied = manager.operate("create", NAME, handle, SNAP, request_id=REQ)
    assert denied["status"] == "blocked"
    assert denied["errors"][0]["code"] == "NOT_OWNED"
    assert jobs.list_status(OWNER) == []


def test_secret_read_failure_does_not_initialize_new_snapshot_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, handle, jobs = fixture(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(module, "root_key", lambda *args, **kwargs: None)
        denied = manager.operate("create", NAME, handle, SNAP, request_id=REQ)
    assert denied["status"] == "blocked"
    assert denied["errors"][0]["code"] == "NOT_OWNED"
    assert jobs.list_status(OWNER) == []


def test_lock_conflict_does_not_create_snapshot_metadata(tmp_path: Path) -> None:
    manager, handle, jobs = fixture(tmp_path)
    root = tmp_path / "owned-avds"
    with provision_lock(root):
        denied = manager.operate("create", NAME, handle, SNAP, request_id=REQ)
        assert denied["status"] == "blocked"
    assert jobs.list_status(OWNER) == []
    assert not list(root.glob(".mcp-snapshot-*"))


def test_forged_snapshot_filename_fails_closed_in_list(tmp_path: Path) -> None:
    manager, handle, jobs = fixture(tmp_path)
    root = tmp_path / "owned-avds"
    fake = root / f".mcp-snapshot-{NAME}-invalid-snapshot-name.json"
    fake.write_text("untrusted", encoding="utf-8")
    denied = manager.operate("list", NAME, handle)
    assert denied["status"] == "blocked"
    assert denied["errors"][0]["code"] == "UNTRUSTED_SNAPSHOT"


def test_list_resource_bound_rejects_thirteen_private_records(tmp_path: Path) -> None:
    manager, handle, jobs = fixture(tmp_path)
    root = tmp_path / "owned-avds"
    secret = root_key(root, create=False)
    info = manager.provisioner.verify_owned(NAME, handle)
    assert isinstance(secret, bytes) and info is not None
    for i in range(support.MAX_SNAPSHOTS_PER_AVD + 1):
        name = f"snap_extra_{i:02}"
        marker = support.signed_record(secret, info, name)
        path = support.snapshot_path(root, NAME, name)
        from android_mcp_host.avd_provision_support import _write_owned

        _write_owned(path, support._canonical(marker))
    denied = manager.operate("list", NAME, handle)
    assert denied["status"] == "blocked"
    assert denied["errors"][0]["code"] == "RESOURCE_LIMIT"


def test_cancelled_or_missing_job_stays_uncertain_and_does_not_replay(tmp_path: Path) -> None:
    manager, handle, jobs = fixture(tmp_path)
    owner = manager.provisioner.verify_owned(NAME, handle)
    assert owner is not None
    digest = manager._plan_digest("create", owner, SNAP)
    prior = jobs.prepare(OWNER, REQ, digest, identity=handle, authorized=True)
    jobs.queue(OWNER, prior["job_id"], identity=handle, authorized=True)
    jobs.claim(OWNER, prior["job_id"], "stale-snapshot", handle, authorized=True)
    cancelled = manager.operate("cancel", NAME, handle, SNAP, job_id=prior["job_id"])
    assert cancelled["status"] == "uncertain"
    assert jobs.status(OWNER, prior["job_id"])["job"]["state"] == "uncertain"
    assert manager.operate("create", NAME, handle, SNAP, request_id=REQ)["status"] == "uncertain"
    assert not list((tmp_path / "owned-avds").glob(".mcp-snapshot-*"))


def test_cli_snapshot_opt_in_requires_matching_pinned_owners(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class Stub:
        def run(self, **kwargs: Any) -> None:
            assert kwargs == {"transport": "http", "host": "127.0.0.1", "port": 8765}

    with monkeypatch.context() as patch:
        patch.setattr(cli.platform, "system", lambda: "Linux")
        patch.setattr(cli, "create_server", lambda **kwargs: calls.append(kwargs) or Stub())
        assert cli.main(["serve"]) == 0
        assert calls == [{}]
        calls.clear()
        for args in (
            ["serve", "--emulator-snapshot-fixture"],
            ["serve", "--emulator-snapshot-fixture", "--avd-provision"],
            ["serve", "--emulator-snapshot-fixture", "--durable-job-status"],
        ):
            with pytest.raises(SystemExit) as error:
                cli.main(args)
            assert error.value.code == 2
            assert calls == []
        args = [
            "serve",
            "--emulator-snapshot-fixture",
            "--avd-provision",
            "--avd-provision-root",
            str(tmp_path / "owned-avds"),
            "--avd-sdk-root",
            str(tmp_path / "synthetic-sdk"),
            "--avd-owner",
            OWNER,
            "--avd-api",
            "36",
            "--avd-abi",
            ABI,
            "--avd-image-sha256",
            hashlib.sha256(SOURCE).hexdigest(),
            "--avd-system-image-sha256",
            hashlib.sha256(SYSTEM).hexdigest(),
            "--avd-license-sha256",
            hashlib.sha256(LICENSE).hexdigest(),
            "--durable-job-status",
            "--job-root",
            str(tmp_path / "jobs"),
            "--job-owner",
            OWNER,
        ]
        assert cli.main(args) == 0
        assert isinstance(calls[0]["snapshot_manager"], module.EmulatorSnapshotManager)
        assert not (tmp_path / "owned-avds").exists()
        assert (tmp_path / "jobs").exists()


def test_real_localhost_mcp_snapshot_records_only(tmp_path: Path) -> None:
    target = provider(tmp_path)
    owned = target.provision("create", NAME)
    assert owned["status"] == "created"
    avd_handle = owned["avd"]["handle"]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    program = (
        "import sys\nfrom pathlib import Path\n"
        "from android_mcp_host.server import create_server\n"
        "from android_mcp_host.avd_provisioning import AvdProvisioner\n"
        "from android_mcp_host.durable_jobs import DurableJobStore\n"
        "from android_mcp_host.emulator_snapshot_manager import EmulatorSnapshotManager\n"
        "owner=AvdProvisioner(Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3],"
        "api=36,abi='arm64-v8a',source_properties_sha256=sys.argv[4],"
        "system_image_sha256=sys.argv[5],license_sha256=sys.argv[6])\n"
        "ledger=DurableJobStore(Path(sys.argv[7]))\n"
        "manager=EmulatorSnapshotManager(owner,ledger,owner=sys.argv[3])\n"
        "create_server(snapshot_manager=manager).run("
        "transport='http',host='127.0.0.1',port=int(sys.argv[8]))\n"
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            program,
            str(tmp_path / "owned-avds"),
            str(tmp_path / "synthetic-sdk"),
            OWNER,
            hashlib.sha256(SOURCE).hexdigest(),
            hashlib.sha256(SYSTEM).hexdigest(),
            hashlib.sha256(LICENSE).hexdigest(),
            str(tmp_path / "jobs"),
            str(port),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def verify() -> None:
        previous: Exception | None = None
        for _ in range(50):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    names = {item.name for item in await client.list_tools()}
                    assert names == {
                        "device_status",
                        "adb_observe",
                        "adb_develop",
                        "host_emulator_snapshot",
                    }
                    args = {
                        "action": "create",
                        "avd_name": NAME,
                        "avd_handle": avd_handle,
                        "snapshot_name": SNAP,
                        "request_id": REQ,
                    }
                    created = await client.call_tool("host_emulator_snapshot", args)
                    assert not created.is_error
                    outcome = created.structured_content
                    assert outcome["status"] == "created"
                    assert outcome["possible_emulator_state_change"] is False
                    assert str(tmp_path) not in json.dumps(outcome)
                    listed = await client.call_tool(
                        "host_emulator_snapshot",
                        {
                            "action": "list",
                            "avd_name": NAME,
                            "avd_handle": avd_handle,
                        },
                    )
                    assert listed.structured_content["snapshots"] == [outcome["snapshot"]]
                    return
            except (OSError, RuntimeError) as error:
                previous = error
                await asyncio.sleep(0.1)
        raise AssertionError(f"Snapshot Tool unavailable: {type(previous).__name__}")

    try:
        asyncio.run(verify())
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    assert process.poll() is not None
