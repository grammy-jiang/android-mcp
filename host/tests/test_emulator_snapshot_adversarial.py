"""H3.d snapshot ownership, compatibility and lifecycle regressions."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from test_avd_provisioning import NAME, OWNER
from test_emulator_snapshot_manager import REQ, SNAP, fixture

import android_mcp_host.emulator_snapshot_support as support
from android_mcp_host.avd_provision_support import _write_owned, root_key


def test_owned_avd_delete_waits_for_snapshot_cleanup(tmp_path: Path) -> None:
    manager, handle, jobs = fixture(tmp_path)
    first = manager.operate("create", NAME, handle, SNAP, request_id=REQ)
    assert first["status"] == "created"
    assert manager.provisioner.provision("delete", NAME, handle)["status"] == "blocked"
    deleted = manager.operate(
        "delete",
        NAME,
        handle,
        SNAP,
        snapshot_handle=first["snapshot"]["handle"],
        request_id="snapshot-delete-001",
    )
    assert deleted["status"] == "deleted"
    assert jobs.status(OWNER, deleted["job_id"])["job"]["state"] == "succeeded"
    assert manager.operate("list", NAME, handle)["snapshots"] == []
    assert manager.provisioner.provision("delete", NAME, handle)["status"] == "deleted"


def test_exact_snapshot_handle_required_for_restore_and_delete(tmp_path: Path) -> None:
    manager, handle, jobs = fixture(tmp_path)
    first = manager.operate("create", NAME, handle, SNAP, request_id=REQ)
    assert first["status"] == "created"
    for action in ("restore", "delete"):
        denied = manager.operate(
            action,
            NAME,
            handle,
            SNAP,
            snapshot_handle="mcpsnap_" + "z" * 32,
            request_id=f"invalid-handle-{action}",
        )
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "INVALID_HANDLE"
    assert manager.operate("list", NAME, handle)["snapshots"] == [first["snapshot"]]


def test_snapshot_identity_cannot_migrate_to_another_avd(tmp_path: Path) -> None:
    manager, handle, jobs = fixture(tmp_path)
    other = manager.provisioner.provision("create", "mcp_second_api36")
    assert other["status"] == "created"
    first = manager.operate("create", NAME, handle, SNAP, request_id=REQ)
    denied = manager.operate(
        "restore",
        "mcp_second_api36",
        other["avd"]["handle"],
        SNAP,
        snapshot_handle=first["snapshot"]["handle"],
        request_id="cross-avd-restore",
    )
    assert denied["status"] == "blocked"
    assert manager.operate("list", "mcp_second_api36", other["avd"]["handle"])["snapshots"] == []


def test_hmac_snapshot_record_matches_pinned_image(tmp_path: Path) -> None:
    manager, handle, jobs = fixture(tmp_path)
    first = manager.operate("create", NAME, handle, SNAP, request_id=REQ)
    root = tmp_path / "owned-avds"
    key = root_key(root, create=False)
    assert isinstance(key, bytes)
    info = manager.provisioner.verify_owned(NAME, handle)
    assert info is not None
    signed = support.signed_record(key, info, SNAP)
    assert signed["snapshot_handle"] == first["snapshot"]["handle"]
    assert signed["image_sha256"] == info["artifact_sha256"]
    assert (
        support.verified_record(support.snapshot_path(root, NAME, SNAP), key, info, SNAP) == signed
    )
    replay = manager.operate("create", NAME, handle, SNAP, request_id="duplicate-creation")
    assert replay["status"] == "existing"
    assert replay["snapshot"] == first["snapshot"]


@pytest.mark.parametrize(
    "field",
    [
        "schema_version",
        "snapshot_version",
        "name",
        "avd_handle",
        "owner_ref",
        "snapshot_name",
        "snapshot_handle",
        "image_sha256",
        "api",
        "abi",
        "fixture_sha256",
        "signature",
    ],
)
def test_modified_snapshot_record_is_never_restored(tmp_path: Path, field: str) -> None:
    manager, handle, jobs = fixture(tmp_path)
    saved = manager.operate("create", NAME, handle, SNAP, request_id=REQ)
    path = tmp_path / "owned-avds" / f".mcp-snapshot-{NAME}-{SNAP}.json"
    record = json.loads(path.read_text())
    record[field] = 33 if field == "api" else "altered"
    path.write_text(json.dumps(record))
    assert manager.operate("list", NAME, handle)["status"] == "blocked"
    denied = manager.operate(
        "restore",
        NAME,
        handle,
        SNAP,
        snapshot_handle=saved["snapshot"]["handle"],
        request_id=f"altered-{field}",
    )
    assert denied["status"] == "blocked"
    assert path.exists()


def test_invalid_json_and_extra_metadata_never_validate(tmp_path: Path) -> None:
    manager, handle, jobs = fixture(tmp_path)
    saved = manager.operate("create", NAME, handle, SNAP, request_id=REQ)
    path = tmp_path / "owned-avds" / f".mcp-snapshot-{NAME}-{SNAP}.json"
    original = path.read_bytes()
    for data in (b"[]", b"invalid", b"", b"{" + b"x" * 4500 + b"}"):
        path.write_bytes(data)
        assert manager.operate("list", NAME, handle)["status"] == "blocked"
    marker = json.loads(original)
    marker["unexpected_field"] = "not allowed"
    path.write_text(json.dumps(marker))
    assert manager.operate("list", NAME, handle)["status"] == "blocked"
    path.write_bytes(original)
    assert manager.operate("list", NAME, handle)["snapshots"] == [saved["snapshot"]]


def test_symlink_and_hardlink_snapshot_denied_without_following(tmp_path: Path) -> None:
    manager, handle, jobs = fixture(tmp_path)
    assert manager.operate("create", NAME, handle, SNAP, request_id=REQ)["status"] == "created"
    path = tmp_path / "owned-avds" / f".mcp-snapshot-{NAME}-{SNAP}.json"
    original = path.read_bytes()
    outside = tmp_path / "foreign-owned"
    outside.write_bytes(original)
    path.unlink()
    path.symlink_to(outside)
    assert manager.operate("list", NAME, handle)["status"] == "blocked"
    assert manager.provisioner.provision("delete", NAME, handle)["status"] == "blocked"
    path.unlink()
    _write_owned(path, original)
    alias = tmp_path / "extra-hardlink"
    os.link(path, alias)
    assert manager.operate("list", NAME, handle)["status"] == "blocked"
    assert alias.read_bytes() == outside.read_bytes()


def test_bounded_snapshot_quota_never_evicts_prior_record(tmp_path: Path) -> None:
    manager, handle, jobs = fixture(tmp_path)
    names = []
    for i in range(support.MAX_SNAPSHOTS_PER_AVD):
        name = f"snap_quota_{i:02}"
        created = manager.operate("create", NAME, handle, name, request_id=f"quota-req-{i:02}")
        assert created["status"] == "created"
        names.append(name)
    listed = manager.operate("list", NAME, handle)
    assert [snap["name"] for snap in listed["snapshots"]] == names
    denied = manager.operate("create", NAME, handle, "snap_quota_over", request_id="quota-over")
    assert denied["status"] == "blocked"
    assert denied["errors"][0]["code"] == "RESOURCE_LIMIT"
    assert len(manager.operate("list", NAME, handle)["snapshots"]) == len(names)


def test_existing_foreign_snapshot_blocks_creation_and_avd_deletion(tmp_path: Path) -> None:
    manager, handle, jobs = fixture(tmp_path)
    root = tmp_path / "owned-avds"
    outside = root / f".mcp-snapshot-{NAME}-snap_foreign.json"
    outside.write_text("pre-existing file", encoding="utf-8")
    denied = manager.operate("create", NAME, handle, "snap_foreign", request_id="foreign-req")
    assert denied["status"] == "blocked"
    assert outside.read_text(encoding="utf-8") == "pre-existing file"
    assert manager.provisioner.provision("delete", NAME, handle)["status"] == "blocked"


def test_replay_after_snapshot_deletion_never_recreates_original(tmp_path: Path) -> None:
    manager, handle, jobs = fixture(tmp_path)
    first = manager.operate("create", NAME, handle, SNAP, request_id=REQ)
    assert first["status"] == "created"
    removed = manager.operate(
        "delete",
        NAME,
        handle,
        SNAP,
        snapshot_handle=first["snapshot"]["handle"],
        request_id="remove-req",
    )
    assert removed["status"] == "deleted"
    replay = manager.operate("create", NAME, handle, SNAP, request_id=REQ)
    assert replay["status"] == "uncertain"
    assert jobs.status(OWNER, first["job_id"])["job"]["attempts"] == 1
    assert manager.operate("list", NAME, handle)["snapshots"] == []


def test_simultaneous_creation_preserves_single_owned_snapshot(tmp_path: Path) -> None:
    manager, handle, jobs = fixture(tmp_path)

    def create(_: int) -> dict[str, Any]:
        return manager.operate("create", NAME, handle, SNAP, request_id=REQ)

    with ThreadPoolExecutor(max_workers=6) as pool:
        outputs = list(pool.map(create, range(12)))
    assert sum(item["status"] == "created" for item in outputs) == 1
    assert all(item["status"] in {"created", "existing", "blocked"} for item in outputs)
    listed = manager.operate("list", NAME, handle)
    assert len(listed["snapshots"]) == 1
    assert len(jobs.list_status(OWNER)) == 1


def test_typed_fault_plans_do_not_write_or_start_emulators(tmp_path: Path) -> None:
    manager, handle, jobs = fixture(tmp_path)
    for condition in ("boot_delay", "network_disconnect", "process_crash"):
        result = manager.operate("fault_plan", NAME, handle, condition=condition)
        assert result["status"] == "planned"
        assert result["condition"] == condition
        assert result["possible_emulator_state_change"] is False
    assert manager.operate("list", NAME, handle)["snapshots"] == []
    assert jobs.list_status(OWNER) == []
    assert not list((tmp_path / "owned-avds").glob(".mcp-snapshot-*"))
