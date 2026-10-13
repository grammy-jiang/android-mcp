"""H3.b second-line owner, resource, concurrency and recovery denials."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from test_avd_provisioning import ABI, API, LICENSE, NAME, SOURCE, SYSTEM, provider

import android_mcp_host.avd_provision_support as support
import android_mcp_host.avd_provisioning as impl


def test_owner_digest_marker_tampering_never_deletes_foreign_avd(tmp_path: Path) -> None:
    provisioner = provider(tmp_path)
    done = provisioner.provision("create", NAME)
    assert done["status"] == "created"
    handle = done["avd"]["handle"]
    marker = tmp_path / "owned-avds" / (NAME + ".avd") / ".mcp-owner.json"
    original = marker.read_bytes()
    record = json.loads(original)
    record["owner_ref"] = "0" * 64
    marker.write_text(json.dumps(record), encoding="utf-8")
    result = provisioner.provision("delete", NAME, handle)
    assert result["status"] == "blocked"
    assert marker.exists()
    marker.write_bytes(original)
    assert provisioner.provision("delete", NAME, handle)["status"] == "deleted"


def test_different_owner_cannot_adopt_owned_avd(tmp_path: Path) -> None:
    first = provider(tmp_path)
    created = first.provision("create", NAME)
    second = impl.AvdProvisioner(
        tmp_path / "owned-avds",
        tmp_path / "synthetic-sdk",
        "different-owner",
        api=API,
        abi=ABI,
        source_properties_sha256=hashlib.sha256(SOURCE).hexdigest(),
        system_image_sha256=hashlib.sha256(SYSTEM).hexdigest(),
        license_sha256=hashlib.sha256(LICENSE).hexdigest(),
    )
    assert second.provision("create", NAME)["status"] == "blocked"
    assert second.provision("delete", NAME, created["avd"]["handle"])["status"] == "blocked"
    assert first.provision("delete", NAME, created["avd"]["handle"])["status"] == "deleted"


@pytest.mark.parametrize("tamper", ["config", "ini", "new-file", "symlink-marker", "snapshots"])
def test_delete_refuses_changed_or_unowned_content(tmp_path: Path, tamper: str) -> None:
    engine = provider(tmp_path)
    created = engine.provision("create", NAME)
    handle = created["avd"]["handle"]
    root = tmp_path / "owned-avds"
    folder = root / (NAME + ".avd")
    if tamper == "config":
        (folder / "config.ini").write_text("owned=false", encoding="utf-8")
    elif tamper == "ini":
        (root / (NAME + ".ini")).write_text("path=/etc/passwd", encoding="utf-8")
    elif tamper == "new-file":
        (folder / "unexpected-user-data").write_bytes(b"user-content")
    elif tamper == "symlink-marker":
        marker = folder / ".mcp-owner.json"
        marker.unlink()
        marker.symlink_to(folder / "config.ini")
    else:
        (folder / "snapshots").mkdir(mode=0o700)
    result = engine.provision("delete", NAME, handle)
    assert result["status"] == "blocked"
    assert folder.exists()


def test_refuse_insecure_secret_and_lock_file(tmp_path: Path) -> None:
    engine = provider(tmp_path)
    assert engine.provision("create", NAME)["status"] == "created"
    root = tmp_path / "owned-avds"
    secret = root / ".avd-key"
    secret.chmod(0o644)
    denied = engine.provision("create", "mcp_second_avd")
    assert denied["status"] == "blocked"
    assert denied["errors"][0]["code"] == "UNTRUSTED_ROOT"
    secret.chmod(0o600)
    lock = root / ".avd-lock"
    lock.chmod(0o644)
    assert engine.provision("create", "mcp_second_avd")["status"] == "blocked"
    lock.chmod(0o600)


def test_private_owner_root_cannot_be_symlinked(tmp_path: Path) -> None:
    engine = provider(tmp_path)
    root = tmp_path / "owned-avds"
    original = tmp_path / "existing"
    original.mkdir(mode=0o700)
    (original / "important-data").write_text("not managed", encoding="utf-8")
    root.symlink_to(original, target_is_directory=True)
    assert engine.provision("create", NAME)["status"] == "blocked"
    assert (original / "important-data").read_text() == "not managed"


@pytest.mark.parametrize(
    "kind",
    [
        "source-properties",
        "source-hash",
        "license-content",
        "system-image",
        "image-symlink",
        "license-symlink",
    ],
)
def test_image_metadata_and_license_must_be_pinned(tmp_path: Path, kind: str) -> None:
    engine = provider(tmp_path)
    sdk = tmp_path / "synthetic-sdk"
    image = sdk / "system-images" / "android-36" / "default" / ABI
    source = image / "source.properties"
    license_file = sdk / "licenses/android-sdk-license"
    system_file = image / "system.img"
    if kind == "source-properties":
        source.write_bytes(SOURCE.replace(b"36", b"35"))
    elif kind == "source-hash":
        source.write_bytes(b"no metadata")
    elif kind == "license-content":
        license_file.write_bytes(b"unknown-license")
    elif kind == "system-image":
        system_file.unlink()
    elif kind == "image-symlink":
        system_file.unlink()
        system_file.symlink_to(source)
    else:
        license_file.unlink()
        license_file.symlink_to(source)
    assert engine.provision("plan", NAME)["status"] == "unavailable"
    assert engine.provision("create", NAME)["status"] == "unavailable"
    assert not (tmp_path / "owned-avds").exists()


def test_disposable_quota_does_not_evict_existing_or_replace_user_data(tmp_path: Path) -> None:
    engine = provider(tmp_path)
    handles = []
    for index in range(16):
        result = engine.provision("create", f"mcp_quota_{index:02}")
        assert result["status"] == "created"
        handles.append(result["avd"]["handle"])
    seventeenth = engine.provision("create", "mcp_quota_99")
    assert seventeenth["status"] == "blocked"
    assert seventeenth["errors"][0]["code"] == "RESOURCE_LIMIT"
    assert len(list((tmp_path / "owned-avds").glob("*.avd"))) == 16
    for index, handle in enumerate(handles):
        assert engine.provision("delete", f"mcp_quota_{index:02}", handle)["status"] == "deleted"


def test_simultaneous_same_avd_creation_has_at_most_one_authority(tmp_path: Path) -> None:
    engine = provider(tmp_path)

    def create(_index: int) -> dict[str, Any]:
        return engine.provision("create", NAME)

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(create, range(12)))
    assert sum(result["status"] == "created" for result in results) == 1
    assert all(result["status"] in {"created", "existing", "blocked"} for result in results)
    root = tmp_path / "owned-avds"
    assert len(list(root.glob("*.avd"))) == 1
    matching = [
        result["avd"]["handle"] for result in results if result["status"] in {"created", "existing"}
    ]
    assert len(set(matching)) == 1


def test_interrupted_third_write_rolls_back_without_removing_prior_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = provider(tmp_path)
    original = support._write_owned
    calls = [0]

    def failed(path: Path, data: bytes) -> None:
        calls[0] += 1
        if calls[0] == 3:
            raise OSError("simulated storage exhaustion")
        original(path, data)

    with monkeypatch.context() as patch:
        patch.setattr(impl, "_write_owned", failed)
        result = engine.provision("create", NAME)
    assert result["status"] == "blocked"
    root = tmp_path / "owned-avds"
    assert not (root / (NAME + ".avd")).exists()
    assert not (root / (NAME + ".ini")).exists()
    assert engine.provision("create", NAME)["status"] == "created"


def test_generated_avd_consumable_by_read_only_h3a_inventory(tmp_path: Path) -> None:
    from android_mcp_host.avd_inventory import AvdInventory
    from android_mcp_host.command_runner import RunResult

    engine = provider(tmp_path)
    assert engine.provision("create", NAME)["status"] == "created"
    binary = tmp_path / "emulator"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o700)
    observer = AvdInventory(
        tmp_path / "owned-avds",
        binary,
        runner=lambda *args: RunResult(0, NAME + "\n", "", False),
    )
    result = observer.inspect(NAME)
    assert result["status"] == "ok"
    assert result["avds"][0]["name"] == NAME
    assert result["avds"][0]["api"] == API
    assert result["avds"][0]["running_state"] == "stale_or_unverified"


def test_invalid_action_name_and_handle_do_not_initialize_root(tmp_path: Path) -> None:
    engine = provider(tmp_path)
    for action, name, handle in (
        ("launch", NAME, None),
        ("create", "another", None),
        ("delete", NAME, None),
        ("delete", NAME, 12),
        ("delete", NAME, "mcpavd_BAD"),
    ):
        result = engine.provision(action, name, handle)
        assert result["status"] == "blocked"
    assert not (tmp_path / "owned-avds").exists()
