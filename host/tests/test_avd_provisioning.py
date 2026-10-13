"""H3.b disposable local MCP-owned AVD provisioning: six mandated cases."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator

from android_mcp_host.server import create_server

NAME = "mcp_fixture_api36"
OTHER = "other-owner"
OWNER = "fixture-build-owner"
API = 36
ABI = "arm64-v8a"
SOURCE = (
    b"Pkg.Revision=1.0.0\nAndroidVersion.ApiLevel=36\n"
    b"SystemImage.Abi=arm64-v8a\nSystemImage.TagId=default\n"
)
LICENSE = b"synthetic-license-fixture-no-real-license"
SYSTEM = b"fake-synthetic-system-image"


def provider(tmp_path: Path, *, license_present: bool = True, image_present: bool = True) -> Any:
    from android_mcp_host.avd_provisioning import AvdProvisioner

    sdk = tmp_path / "synthetic-sdk"
    image = sdk / "system-images" / "android-36" / "default" / ABI
    image.mkdir(parents=True)
    (image / "source.properties").write_bytes(SOURCE)
    if image_present:
        (image / "system.img").write_bytes(SYSTEM)
    licenses = sdk / "licenses"
    licenses.mkdir()
    if license_present:
        (licenses / "android-sdk-license").write_bytes(LICENSE)
    return AvdProvisioner(
        root=tmp_path / "owned-avds",
        sdk_root=sdk,
        owner=OWNER,
        api=API,
        abi=ABI,
        source_properties_sha256=hashlib.sha256(SOURCE).hexdigest(),
        system_image_sha256=hashlib.sha256(SYSTEM).hexdigest(),
        license_sha256=hashlib.sha256(LICENSE).hexdigest(),
    )


def test_t_h3b_01_create_owned_disposable_from_pinned_installed_fixture(
    tmp_path: Path,
) -> None:
    target = provider(tmp_path)
    plan = target.provision("plan", NAME)
    assert plan["status"] == "planned"
    assert not (tmp_path / "owned-avds").exists()
    created = target.provision("create", NAME)
    assert created["status"] == "created"
    assert created["avd"]["name"] == NAME
    assert created["avd"]["api"] == API
    assert created["avd"]["abi"] == ABI
    assert created["avd"]["target"] == "disposable_emulator_only"
    assert created["avd"]["handle"].startswith("mcpavd_")
    assert created["avd"]["artifact_sha256"] == hashlib.sha256(SYSTEM).hexdigest()
    assert len(created["avd"]["owner_ref"]) == 64
    root = tmp_path / "owned-avds"
    config = root / f"{NAME}.avd" / "config.ini"
    ini = root / f"{NAME}.ini"
    assert config.exists() and ini.exists()
    assert (root / f"{NAME}.avd").stat().st_mode & 0o777 == 0o700
    assert (root / ".avd-key").stat().st_mode & 0o777 == 0o600
    assert "image.sysdir.1=system-images/android-36/default/arm64-v8a/" in config.read_text()
    assert str(root / f"{NAME}.avd") in ini.read_text()
    assert "private" not in json.dumps(created)
    assert str(tmp_path) not in json.dumps(created)
    assert target.provision("create", NAME)["avd"]["handle"] == created["avd"]["handle"]


def test_t_h3b_02_never_touch_preexisting_or_foreign_avd(tmp_path: Path) -> None:
    target = provider(tmp_path)
    root = tmp_path / "owned-avds"
    root.mkdir(mode=0o700)
    foreign = root / f"{NAME}.avd"
    foreign.mkdir(mode=0o700)
    (foreign / "my-user-data").write_bytes(b"never-modify-me")
    before = (foreign / "my-user-data").read_bytes()
    failed = target.provision("create", NAME)
    assert failed["status"] == "blocked"
    assert before == (foreign / "my-user-data").read_bytes()
    assert not (root / f"{NAME}.ini").exists()
    rejected = target.provision("delete", NAME, "mcpavd_" + "a" * 32)
    assert rejected["status"] == "blocked"
    assert before == (foreign / "my-user-data").read_bytes()


def test_t_h3b_03_traversal_symlink_and_wrong_api_abi_denied_before_write(
    tmp_path: Path,
) -> None:
    from android_mcp_host.avd_provisioning import AvdProvisioner

    target = provider(tmp_path)
    for name in ("../name", "/tmp/malicious", "-avd", "name with space", "a" * 80):
        assert target.provision("create", name)["status"] == "blocked"
    assert not (tmp_path / "owned-avds").exists()
    sdk = tmp_path / "synthetic-sdk"
    linked = tmp_path / "linked-sdks"
    linked.symlink_to(sdk, target_is_directory=True)
    with pytest.raises(ValueError):
        AvdProvisioner(
            tmp_path / "another-owned",
            linked,
            OWNER,
            api=36,
            abi=ABI,
            source_properties_sha256=hashlib.sha256(SOURCE).hexdigest(),
            system_image_sha256=hashlib.sha256(SYSTEM).hexdigest(),
            license_sha256=hashlib.sha256(LICENSE).hexdigest(),
        )
    with pytest.raises(ValueError):
        AvdProvisioner(
            tmp_path / "another-owned",
            sdk,
            OWNER,
            api=99,
            abi="armeabi-injected/path",
            source_properties_sha256="a" * 64,
            system_image_sha256="c" * 64,
            license_sha256="b" * 64,
        )


def test_t_h3b_04_missing_image_and_unaccepted_license_remain_unavailable(
    tmp_path: Path,
) -> None:
    missing_license = provider(tmp_path / "missing-license", license_present=False)
    missing_image = provider(tmp_path / "missing-image", image_present=False)
    for obj, root in (
        (missing_license, tmp_path / "missing-license" / "owned-avds"),
        (missing_image, tmp_path / "missing-image" / "owned-avds"),
    ):
        result = obj.provision("create", NAME)
        assert result["status"] == "unavailable"
        assert not root.exists()
    assert not (
        tmp_path / "missing-license" / "synthetic-sdk" / "licenses" / "android-sdk-license"
    ).exists()


def test_t_h3b_05_failed_write_rolls_back_and_duplicate_cleanup_is_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from android_mcp_host import avd_provisioning

    target = provider(tmp_path)
    real_writer = avd_provisioning._write_owned
    calls = [0]

    def fail_second(*args: Any, **kwargs: Any) -> Any:
        calls[0] += 1
        if calls[0] == 2:
            raise OSError("synthetic full disk")
        return real_writer(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(avd_provisioning, "_write_owned", fail_second)
        result = target.provision("create", NAME)
    assert result["status"] == "blocked"
    root = tmp_path / "owned-avds"
    assert not (root / f"{NAME}.avd").exists()
    assert not (root / f"{NAME}.ini").exists()
    assert not list(root.glob("*.avd"))
    successful = target.provision("create", NAME)
    assert successful["status"] == "created"
    handle = successful["avd"]["handle"]
    again = target.provision("create", NAME)
    assert again["status"] == "existing"
    assert again["avd"]["handle"] == handle
    denied = target.provision("delete", NAME, "mcpavd_" + "0" * 32)
    assert denied["status"] == "blocked"
    assert (root / f"{NAME}.avd").exists()
    deleted = target.provision("delete", NAME, handle)
    assert deleted["status"] == "deleted"
    assert not (root / f"{NAME}.avd").exists()
    assert not (root / f"{NAME}.ini").exists()
    assert target.provision("delete", NAME, handle)["status"] == "not_found"


def test_t_h3b_06_private_owner_target_artifact_contract_and_fastmcp(
    tmp_path: Path,
) -> None:
    from android_mcp_host.avd_provisioning import get_avd_provision_schema

    target = provider(tmp_path)

    async def inspect() -> None:
        async with Client(create_server()) as baseline:
            original = {tool.name: tool for tool in await baseline.list_tools()}
        async with Client(create_server(avd_provisioner=target)) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert set(tools) == {*original, "host_avd_provision"}
            assert all(tools[name] == original[name] for name in original)
            schema = get_avd_provision_schema()
            Draft202012Validator.check_schema(schema)
            tool = tools["host_avd_provision"]
            assert tool.output_schema == schema
            assert tool.annotations is not None
            hints = tool.annotations.model_dump(mode="json", by_alias=True)
            assert hints["readOnlyHint"] is False
            assert hints["destructiveHint"] is True
            result = await client.call_tool(
                "host_avd_provision", {"action": "create", "name": NAME}
            )
            assert not result.is_error
            info = result.structured_content
            assert info["status"] == "created"
            Draft202012Validator(schema).validate(info)
            assert info["avd"]["target"] == "disposable_emulator_only"
            assert "owner_ref" in info["avd"] and "artifact_sha256" in info["avd"]
            assert str(tmp_path) not in json.dumps(info)
            assert OWNER not in json.dumps(info)

    asyncio.run(inspect())
