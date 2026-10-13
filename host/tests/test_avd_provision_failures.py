"""H3.b negative and real localhost-wire cases; no actual emulator processes."""

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
from test_avd_provisioning import ABI, API, LICENSE, NAME, OWNER, SOURCE, SYSTEM, provider

import android_mcp_host.avd_provision_support as support
import android_mcp_host.avd_provisioning as impl
from android_mcp_host import cli


def test_unsigned_marker_and_invalid_json_are_foreign_even_if_handle_matches(
    tmp_path: Path,
) -> None:
    engine = provider(tmp_path)
    created = engine.provision("create", NAME)
    handle = created["avd"]["handle"]
    marker = tmp_path / "owned-avds" / (NAME + ".avd") / ".mcp-owner.json"
    original = marker.read_bytes()
    for mutated in (
        b"[]",
        b"not-json",
        b'{"signature":"123"}',
        original.replace(b"mcpavd_", b"forged_"),
        original.replace(b"mcp_fixture_api36", b"bad_tagged_avd____"),
    ):
        marker.write_bytes(mutated)
        assert engine.provision("delete", NAME, handle)["status"] == "blocked"
    marker.write_bytes(original)
    assert engine.provision("delete", NAME, handle)["status"] == "deleted"


def test_root_key_is_created_private_and_missing_returns_none(tmp_path: Path) -> None:
    root = tmp_path / "managed"
    assert support.root_key(root, create=False) is None
    secret = support.root_key(root, create=True)
    assert isinstance(secret, bytes) and len(secret) == 32
    assert support.root_key(root, create=False) == secret
    assert root.stat().st_mode & 0o777 == 0o700
    assert (root / ".avd-key").stat().st_mode & 0o777 == 0o600


def test_root_key_failure_leaves_no_partial_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed(path: Path, data: bytes) -> None:
        raise OSError("disk is full")

    root = tmp_path / "private-failed"
    with monkeypatch.context() as patch:
        patch.setattr(support, "_write_owned", failed)
        with pytest.raises(support.OwnedAvdError) as error:
            support.root_key(root, create=True)
        assert error.value.code == "STORAGE_FAILURE"
    assert not root.exists()
    assert len(support.root_key(root, create=True)) == 32


@pytest.mark.parametrize("invalid", [None, 99, "", "x", "/tmp/../danger", "relative"])
def test_invalid_root_initialization_rejects_untrusted_paths(
    invalid: Any,
) -> None:
    path = invalid if isinstance(invalid, Path) else Path(str(invalid))
    if isinstance(invalid, str) and invalid.startswith("/tmp/../"):
        assert support._sane_root(path) is False
    elif not path.is_absolute():
        assert support._sane_root(path) is False


def test_user_avd_root_and_child_never_eligible_for_creation() -> None:
    user_root = Path.home() / ".android" / "avd"
    assert support._sane_root(user_root) is False
    assert support._sane_root(user_root / "native-device.avd") is False


def test_private_lock_blocks_second_process_and_denies_insecure_file(tmp_path: Path) -> None:
    root = tmp_path / "owned"
    support.root_key(root, create=True)
    with support.provision_lock(root):
        with pytest.raises(support.OwnedAvdError, match="RESOURCE_BUSY"):
            with support.provision_lock(root):
                pass
    lock = root / ".avd-lock"
    lock.chmod(0o644)
    with pytest.raises(support.OwnedAvdError, match="UNTRUSTED_ROOT"):
        with support.provision_lock(root):
            pass
    lock.chmod(0o600)
    lock.unlink()
    lock.symlink_to(root / ".avd-key")
    with pytest.raises(support.OwnedAvdError, match="STORAGE_FAILURE"):
        with support.provision_lock(root):
            pass


def test_owner_marker_cannot_be_signed_with_unicode_or_extra_keys(tmp_path: Path) -> None:
    engine = provider(tmp_path)
    created = engine.provision("create", NAME)
    handle = created["avd"]["handle"]
    folder = tmp_path / "owned-avds" / (NAME + ".avd")
    marker_path = folder / ".mcp-owner.json"
    record = json.loads(marker_path.read_text())
    original = marker_path.read_bytes()
    record["injected"] = "➜"
    marker_path.write_text(json.dumps(record), encoding="utf-8")
    assert engine.provision("delete", NAME, handle)["status"] == "blocked"
    marker_path.write_bytes(original)
    assert engine.provision("delete", NAME, handle)["status"] == "deleted"


def test_existing_root_without_owner_key_is_not_adopted(tmp_path: Path) -> None:
    engine = provider(tmp_path)
    root = tmp_path / "owned-avds"
    root.mkdir(mode=0o700)
    secret = root / ".avd-key"
    secret.write_bytes(b"too-short")
    assert engine.provision("create", NAME)["status"] == "blocked"
    assert secret.read_bytes() == b"too-short"


def test_failed_missing_license_does_not_trigger_download_or_accept(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = provider(tmp_path, license_present=False)
    with monkeypatch.context() as patch:
        patch.setattr(
            support,
            "_write_owned",
            lambda *args: (_ for _ in ()).throw(AssertionError("No file should be created")),
        )
        result = engine.provision("create", NAME)
    assert result["status"] == "unavailable"
    assert not (tmp_path / "owned-avds").exists()


@pytest.mark.parametrize(
    "bad_content",
    [
        SOURCE.replace(b"36", b"35"),
        SOURCE.replace(b"default", b"google_apis"),
        SOURCE.replace(b"arm64-v8a", b"x86_64"),
        SOURCE.replace(b"Pkg.Revision=1.0.0\n", b""),
        SOURCE.replace(b"Pkg.Revision=1.0.0", b"Pkg.Revision="),
    ],
)
def test_tampered_pinned_source_properties_are_not_approved(
    tmp_path: Path, bad_content: bytes
) -> None:
    engine = provider(tmp_path)
    source = (
        tmp_path
        / "synthetic-sdk"
        / "system-images"
        / "android-36"
        / "default"
        / ABI
        / "source.properties"
    )
    source.write_bytes(bad_content)
    assert engine.provision("plan", NAME)["status"] == "unavailable"
    assert engine.provision("create", NAME)["status"] == "unavailable"


def test_unverified_root_permissions_do_not_enable_management(tmp_path: Path) -> None:
    engine = provider(tmp_path)
    assert engine.provision("create", NAME)["status"] == "created"
    root = tmp_path / "owned-avds"
    root.chmod(0o755)
    try:
        assert engine.provision("create", "mcp_new_root")["status"] == "blocked"
    finally:
        root.chmod(0o700)


def test_wrong_private_handle_does_not_remove_owned_avd(tmp_path: Path) -> None:
    engine = provider(tmp_path)
    record = engine.provision("create", NAME)
    handle = record["avd"]["handle"]
    denied = engine.provision("delete", NAME, "mcpavd_" + "z" * 32)
    assert denied["status"] == "blocked"
    assert (tmp_path / "owned-avds" / (NAME + ".avd")).exists()
    assert engine.provision("delete", NAME, handle)["status"] == "deleted"


def test_delete_does_not_need_old_sdk_image_to_still_be_present(tmp_path: Path) -> None:
    engine = provider(tmp_path)
    record = engine.provision("create", NAME)
    source = (
        tmp_path / "synthetic-sdk" / "system-images" / "android-36" / "default" / ABI / "system.img"
    )
    source.unlink()
    assert engine.provision("create", "mcp_other_fixture")["status"] == "unavailable"
    assert engine.provision("delete", NAME, record["avd"]["handle"])["status"] == "deleted"


def test_localhost_mcp_synthetic_avd_files_only(tmp_path: Path) -> None:
    engine = provider(tmp_path)
    assert engine.provision("plan", NAME)["status"] == "planned"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    executable = (
        "import sys\nfrom pathlib import Path\n"
        "from android_mcp_host.avd_provisioning import AvdProvisioner\n"
        "from android_mcp_host.server import create_server\n"
        "provider=AvdProvisioner(Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3],"
        "api=int(sys.argv[4]),abi=sys.argv[5],"
        "source_properties_sha256=sys.argv[6],system_image_sha256=sys.argv[7],"
        "license_sha256=sys.argv[8])\n"
        "create_server(avd_provisioner=provider).run("
        "transport='http',host='127.0.0.1',port=int(sys.argv[9]))\n"
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            executable,
            str(tmp_path / "owned-avds"),
            str(tmp_path / "synthetic-sdk"),
            OWNER,
            str(API),
            ABI,
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
        recent: Exception | None = None
        for _ in range(50):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    catalog = {tool.name for tool in await client.list_tools()}
                    assert catalog == {
                        "device_status",
                        "adb_observe",
                        "adb_develop",
                        "host_avd_provision",
                    }
                    create = await client.call_tool(
                        "host_avd_provision", {"action": "create", "name": NAME}
                    )
                    assert not create.is_error
                    data = create.structured_content
                    assert data["status"] == "created"
                    assert data["emulator_execution_enabled"] is False
                    Draft202012Validator(impl.get_avd_provision_schema()).validate(data)
                    assert str(tmp_path) not in json.dumps(data)
                    handle = data["avd"]["handle"]
                    deleted = await client.call_tool(
                        "host_avd_provision", {"action": "delete", "name": NAME, "handle": handle}
                    )
                    assert deleted.structured_content["status"] == "deleted"
                    return
            except (OSError, RuntimeError) as error:
                recent = error
                await asyncio.sleep(0.1)
        raise AssertionError(f"Synthetic AVD Tool unavailable: {type(recent).__name__}")

    try:
        asyncio.run(inspect())
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    assert not (tmp_path / "owned-avds" / (NAME + ".avd")).exists()


def test_cli_provision_requires_all_pins_and_keeps_default_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    class Stub:
        def run(self, **kwargs: Any) -> None:
            assert kwargs == {"transport": "http", "host": "127.0.0.1", "port": 8765}

    def make_server(**kwargs: Any) -> Stub:
        calls.append(kwargs)
        return Stub()

    with monkeypatch.context() as patch:
        patch.setattr(cli, "create_server", make_server)
        patch.setattr(cli.platform, "system", lambda: "Linux")
        assert cli.main(["serve"]) == 0
        assert calls == [{}]
        calls.clear()
        for flags in (
            ["serve", "--avd-provision"],
            ["serve", "--avd-provision-root", str(tmp_path / "owned")],
            ["serve", "--avd-provision", "--avd-owner", OWNER],
        ):
            with pytest.raises(SystemExit) as caught:
                cli.main(flags)
            assert caught.value.code == 2
            assert calls == []
        assert (
            cli.main(
                [
                    "serve",
                    "--avd-provision",
                    "--avd-provision-root",
                    str(tmp_path / "owned"),
                    "--avd-sdk-root",
                    str(tmp_path / "sdk"),
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
                ]
            )
            == 0
        )
        assert isinstance(calls[0]["avd_provisioner"], impl.AvdProvisioner)
    assert not (tmp_path / "owned").exists()


def test_schema_must_be_object(monkeypatch: pytest.MonkeyPatch) -> None:
    class Resource:
        def joinpath(self, name: str) -> Resource:
            assert name == "host-avd-provision.v1.schema.json"
            return self

        def read_text(self, *, encoding: str) -> str:
            return "[]"

    monkeypatch.setattr(impl, "files", lambda _: Resource())
    with pytest.raises(ValueError, match="Invalid packaged"):
        impl.get_avd_provision_schema()


def test_system_image_pin_streams_bytes_and_refuses_size_or_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = tmp_path / "image.bin"
    expected_content = b"x" * (2 * 1024 * 1024 + 31)
    image.write_bytes(expected_content)
    expected = hashlib.sha256(expected_content).hexdigest()
    assert support._system_image_digest(image, expected) is True
    assert support._system_image_digest(image, "0" * 64) is False
    with monkeypatch.context() as patch:
        patch.setattr(support, "MAX_SYSTEM_IMAGE_BYTES", 100)
        assert support._system_image_digest(image, expected) is False
    image.write_bytes(b"")
    assert support._system_image_digest(image, expected) is False
    image.unlink()
    image.symlink_to(tmp_path / "other")
    assert support._system_image_digest(image, expected) is False


def test_untrusted_root_owner_image_symlink_and_empty_licenses_are_rejected(tmp_path: Path) -> None:
    engine = provider(tmp_path)
    sdk = tmp_path / "synthetic-sdk"
    linked = tmp_path / "linked-sdk"
    linked.symlink_to(sdk, target_is_directory=True)
    assert (
        support.image_preflight(
            linked,
            API,
            ABI,
            hashlib.sha256(SOURCE).hexdigest(),
            hashlib.sha256(SYSTEM).hexdigest(),
            hashlib.sha256(LICENSE).hexdigest(),
        )
        is False
    )
    sdk_image = sdk / "system-images" / "android-36" / "default" / ABI
    (sdk_image / "system.img").write_bytes(b"")
    assert engine.provision("create", NAME)["status"] == "unavailable"
    assert not (tmp_path / "owned-avds").exists()


def test_failed_private_key_fsync_does_not_leave_unowned_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "private"
    with monkeypatch.context() as patch:
        patch.setattr(
            support.os,
            "fsync",
            lambda fd: (_ for _ in ()).throw(OSError("disk sync failed")),
        )
        with pytest.raises(OSError):
            support._write_owned(path, b"test-secret")
    assert not path.exists()
    support._write_owned(path, b"test-secret")
    assert path.read_bytes() == b"test-secret"


def test_pinned_source_revision_must_be_semantically_valid(tmp_path: Path) -> None:
    provider(tmp_path)
    sdk = tmp_path / "synthetic-sdk"
    source = sdk / "system-images" / "android-36" / "default" / ABI / "source.properties"
    invalid = SOURCE.replace(b"Pkg.Revision=1.0.0", b"Pkg.Revision=invalid")
    source.write_bytes(invalid)
    assert (
        support.image_preflight(
            sdk,
            API,
            ABI,
            hashlib.sha256(invalid).hexdigest(),
            hashlib.sha256(SYSTEM).hexdigest(),
            hashlib.sha256(LICENSE).hexdigest(),
        )
        is False
    )
