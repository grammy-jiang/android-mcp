"""H3.a six mandatory read-only AVD inventory cases; no emulator starts."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from fastmcp import Client
from jsonschema import Draft202012Validator

from android_mcp_host.command_runner import RunResult
from android_mcp_host.server import create_server

AVD = "fixture_api36"


def fake_avd(
    tmp_path: Path,
    name: str = AVD,
    *,
    api: int = 36,
    abi: str = "arm64-v8a",
    snapshot: bool = True,
    pid: bytes | None = b"12345\x00",
) -> tuple[Path, Path]:
    avd_root = tmp_path / "avds"
    avd_root.mkdir(mode=0o700, exist_ok=True)
    sdk = tmp_path / "sdk" / "emulator"
    sdk.mkdir(parents=True)
    binary = sdk / "emulator"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o700)
    data_root = avd_root / f"{name}.avd"
    data_root.mkdir(mode=0o700)
    (avd_root / f"{name}.ini").write_text(
        f"avd.ini.encoding=UTF-8\npath={data_root}\ntarget=android-{api}\n",
        encoding="utf-8",
    )
    (data_root / "config.ini").write_text(
        f"AvdId={name}\nabi.type={abi}\n"
        f"hw.cpu.arch=arm64\n"
        f"image.sysdir.1=system-images/android-{api}/default/{abi}/\n"
        f"target=android-{api}\n",
        encoding="utf-8",
    )
    if snapshot:
        # H3.a private metadata fixtures must be portable across runner umasks.
        # Keep production trusted_dir() strict: the fixture must meet its contract.
        snapshots = data_root / "snapshots"
        snapshots.mkdir(mode=0o700)
        quickboot = snapshots / "quickboot"
        quickboot.mkdir(mode=0o700)
        (quickboot / "snapshot.pb").write_bytes(b"stub")
    if pid is not None:
        (data_root / "hardware-qemu.ini.lock").write_bytes(pid)
    return avd_root, binary


def test_h3a_private_fixture_permissions_do_not_depend_on_ci_umask(tmp_path: Path) -> None:
    from android_mcp_host.avd_inventory import AvdInventory

    previous = os.umask(0o022)
    try:
        root, binary = fake_avd(tmp_path)
    finally:
        os.umask(previous)
    assert (root / f"{AVD}.avd" / "snapshots").stat().st_mode & 0o777 == 0o700
    assert (root / f"{AVD}.avd" / "snapshots" / "quickboot").stat().st_mode & 0o777 == 0o700
    assert AvdInventory(root, binary, runner=runner_list(AVD)).inspect()["status"] == "ok"


def runner_list(names: str) -> Any:
    def fake(argv: Any, timeout: float, limit: int) -> RunResult:
        assert argv[1:] == ["-list-avds"]
        assert timeout <= 5 and limit <= 8192
        return RunResult(0, names, "", False)

    return fake


def fake_process(binary: Path, name: str = AVD, pid: int = 12345) -> Any:
    def ps(argv: Any, timeout: float, limit: int) -> RunResult:
        assert str(pid) in argv
        assert "--kill" not in argv and "-9" not in argv
        command = binary.parent / "qemu/darwin-aarch64/qemu-system-aarch64-headless"
        return RunResult(0, f"{command} -avd {name} -port 5554\n", "", False)

    return ps


def test_t_h3a_01_fixed_avd_name_api_abi_snapshot_and_verified_process(tmp_path: Path) -> None:
    from android_mcp_host.avd_inventory import AvdInventory

    root, binary = fake_avd(tmp_path)
    engine = AvdInventory(
        avd_root=root,
        emulator_binary=binary,
        runner=runner_list(f"{AVD}\n"),
        process_runner=fake_process(binary),
    )
    result = engine.inspect()
    assert result["status"] == "ok"
    assert result["runtime"] == "host" and result["schema_version"] == 1
    assert len(result["avds"]) == 1
    item = result["avds"][0]
    assert item == {
        "name": AVD,
        "api": 36,
        "abi": "arm64-v8a",
        "snapshot_count": 1,
        "snapshot_state": "present_unverified",
        "running_state": "verified_running",
    }
    assert engine.inspect(AVD)["avds"] == [item]
    assert str(tmp_path) not in json.dumps(result)
    assert "device_id" not in json.dumps(result)
    assert result["errors"] == []


def test_t_h3a_02_sdk_missing_and_emulator_absent_unavailable_without_adb(
    tmp_path: Path,
) -> None:
    from android_mcp_host.avd_inventory import AvdInventory

    root, binary = fake_avd(tmp_path)
    binary.unlink()
    result = AvdInventory(root, binary, runner=lambda *args: 1 / 0).inspect()
    assert result["status"] == "unavailable"
    assert result["avds"] == []
    assert result["errors"][0]["code"] == "EMULATOR_UNAVAILABLE"
    engine = AvdInventory(tmp_path / "missing", tmp_path / "no-emulator")
    assert engine.inspect()["status"] == "unavailable"
    assert engine.inspect("invalid -avd")["status"] == "invalid"


def test_t_h3a_03_malformed_cli_duplicate_names_and_invalid_config(
    tmp_path: Path,
) -> None:
    from android_mcp_host.avd_inventory import AvdInventory

    root, binary = fake_avd(tmp_path)
    for listing in (f"{AVD}\n{AVD}\n", "name\nname\n", "\x00evil\n", "x" * 9000):
        engine = AvdInventory(root, binary, runner=runner_list(listing))
        outcome = engine.inspect()
        assert outcome["status"] in {"invalid", "partial"}
        assert not outcome["avds"]

    config = root / f"{AVD}.avd" / "config.ini"
    config.write_text("abi.type=evil/../../sys\ninvalid\n", encoding="utf-8")
    outcome = AvdInventory(root, binary, runner=runner_list(f"{AVD}\n")).inspect()
    assert outcome["status"] == "partial"
    assert not outcome["avds"]


def test_t_h3a_04_hostile_name_and_symlink_never_become_command_or_escape_store(
    tmp_path: Path,
) -> None:
    from android_mcp_host.avd_inventory import AvdInventory

    root, binary = fake_avd(tmp_path)
    calls: list[list[str]] = []

    def fake(argv: Any, timeout: float, limit: int) -> RunResult:
        calls.append(list(argv))
        return RunResult(0, f"{AVD}\n", "", False)

    inventory = AvdInventory(root, binary, runner=fake)
    for bad in ("-avd", "../outside", "name with space", "X" * 200, "/etc/passwd"):
        result = inventory.inspect(bad)
        assert result["status"] == "invalid"
        assert calls == []
    config = root / f"{AVD}.avd" / "config.ini"
    config.unlink()
    config.symlink_to(tmp_path / "outside.ini")
    assert inventory.inspect()["status"] == "partial"
    assert calls and all(call == [str(binary), "-list-avds"] for call in calls)


def test_t_h3a_05_stale_pid_timeout_and_oversized_files_never_signal_process(
    tmp_path: Path,
) -> None:
    from android_mcp_host.avd_inventory import AvdInventory

    root, binary = fake_avd(tmp_path)
    engine = AvdInventory(
        root,
        binary,
        runner=runner_list(f"{AVD}\n"),
        process_runner=lambda *args: RunResult(
            0, "/usr/bin/unrelated -avd fixture_api36", "", False
        ),
    )
    result = engine.inspect()
    assert result["avds"][0]["running_state"] == "stale_or_unverified"
    (root / f"{AVD}.avd" / "hardware-qemu.ini.lock").write_bytes(b"987654321012345")
    assert engine.inspect()["avds"][0]["running_state"] == "stale_or_unverified"
    oversized = root / f"{AVD}.avd" / "config.ini"
    oversized.write_bytes(b"Z" * 70000)
    assert engine.inspect()["status"] == "partial"
    hung = AvdInventory(
        root,
        binary,
        runner=lambda *args: (_ for _ in ()).throw(subprocess.TimeoutExpired(["emulator"], 0.1)),
    )
    assert hung.inspect()["errors"][0]["code"] == "EMULATOR_TIMEOUT"


def test_t_h3a_06_versioned_fastmcp_default_unchanged_and_status_schema(
    tmp_path: Path,
) -> None:
    from android_mcp_host.avd_inventory import AvdInventory, get_avd_output_schema

    root, binary = fake_avd(tmp_path, pid=None)
    engine = AvdInventory(root, binary, runner=runner_list(f"{AVD}\n"))

    async def verify() -> None:
        async with Client(create_server()) as base:
            original = {tool.name: tool for tool in await base.list_tools()}
        assert set(original) == {"device_status", "adb_observe", "adb_develop"}
        async with Client(create_server(avd_inventory=engine)) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert set(tools) == {*original, "host_avd_inventory"}
            assert all(tools[name] == original[name] for name in original)
            tool = tools["host_avd_inventory"]
            Draft202012Validator.check_schema(tool.output_schema)
            assert tool.output_schema == get_avd_output_schema()
            assert tool.annotations is not None
            hints = tool.annotations.model_dump(mode="json", by_alias=True)
            assert hints["readOnlyHint"] is True
            assert hints["destructiveHint"] is False
            assert hints["openWorldHint"] is False
            response = await client.call_tool("host_avd_inventory", {"name": AVD})
            assert not response.is_error
            payload = response.structured_content
            assert isinstance(payload, dict)
            Draft202012Validator(tool.output_schema).validate(payload)
            assert payload["avds"][0]["running_state"] == "stale_or_unverified"
            assert str(tmp_path) not in json.dumps(payload)

    asyncio.run(verify())
