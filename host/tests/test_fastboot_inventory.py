"""H1.f: fixed read-only Fastboot inventory, no Android mutation or ADB fallback."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator

from android_mcp_host import cli
from android_mcp_host.command_runner import OutputLimitExceeded, bounded_run
from android_mcp_host.fastboot_inventory import FastbootInventory, get_fastboot_output_schema
from android_mcp_host.server import create_server

SERIAL1 = "SYNTHETIC-BOOTLOADER-01"
SERIAL2 = "SYNTHETIC-BOOTLOADER-02"


def binary(tmp_path: Path) -> Path:
    exe = tmp_path / "fixed" / "fastboot"
    exe.parent.mkdir(exist_ok=True)
    exe.write_text("#!/bin/sh\nprintf 'fastboot version 37.0.1\\n'\n", encoding="utf-8")
    exe.chmod(0o700)
    return exe


class FakeRunner:
    def __init__(self, version: str = "37.0.1", devices: str = "") -> None:
        self.version = version
        self.devices = devices
        self.calls: list[list[str]] = []
        self.fail_at: int | None = None
        self.failure: BaseException | None = None

    def __call__(self, argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        assert 0 < timeout <= 10
        if self.fail_at == len(self.calls) and self.failure is not None:
            raise self.failure
        if argv[1:] == ["--version"]:
            output = "fastboot version " + self.version + "\n"
        elif argv[1:] == ["devices", "-l"]:
            output = self.devices
        else:
            raise AssertionError(f"Unexpected Fastboot CLI argv: {argv!r}")
        return subprocess.CompletedProcess(argv, 0, output, "")


def check(result: dict[str, Any]) -> dict[str, Any]:
    Draft202012Validator(get_fastboot_output_schema()).validate(result)
    assert result["schema_version"] == 1 and result["runtime"] == "host"
    return result


def codes(result: dict[str, Any]) -> list[str]:
    return [e["code"] for e in result["errors"]]


def test_t_h1f_01_mac37_and_debian34_independent_unverified_bootloader_rows(
    tmp_path: Path,
) -> None:
    exe = binary(tmp_path)
    for version, rows in (
        ("37.0.1", f"{SERIAL1}\tfastboot usb:1-2\n{SERIAL2}\tfastboot\n"),
        ("34.0.5-1", f"{SERIAL1}\tfastboot usb:3-2\n{SERIAL2}\tfastboot\n"),
    ):
        fake = FakeRunner(version, rows)
        result = check(FastbootInventory(executable=exe, reader=fake).discover())
        assert result["status"] == "ok"
        assert result["fastboot"] == {"available": True, "version": version}
        assert result["devices"] == [
            {
                "device_id": SERIAL1,
                "state": "fastboot",
                "transport": "usb",
                "mode": "unverified",
                "device_authorized": False,
            },
            {
                "device_id": SERIAL2,
                "state": "fastboot",
                "transport": "unknown",
                "mode": "unverified",
                "device_authorized": False,
            },
        ]
        assert fake.calls == [[str(exe), "--version"], [str(exe), "devices", "-l"]]


def test_t_h1f_02_absent_binary_and_empty_fastboot_not_confused_with_adb(
    tmp_path: Path,
) -> None:
    fake = FakeRunner()
    missing = check(
        FastbootInventory(executable=tmp_path / "missing-fastboot", reader=fake).discover()
    )
    assert missing["status"] == "unavailable"
    assert codes(missing) == ["FASTBOOT_NOT_FOUND"]
    assert missing["devices"] == [] and fake.calls == []
    exe = binary(tmp_path)
    empty = check(FastbootInventory(executable=exe, reader=fake).discover())
    assert empty["status"] == "ok"
    assert empty["devices"] == []
    assert empty["fastboot"]["available"] is True
    assert all(command[0] == str(exe) for command in fake.calls)


def test_t_h1f_03_duplicate_malformed_and_wrong_mode_fail_closed(tmp_path: Path) -> None:
    exe = binary(tmp_path)
    fixtures = [
        (
            f"{SERIAL1} fastboot usb:1-2\n{SERIAL1} fastboot usb:1-3\n",
            "error",
            "AMBIGUOUS_FASTBOOT_SERIAL",
        ),
        (f"{SERIAL1} device usb:1-2\n", "partial", "INVALID_FASTBOOT_MODE"),
        ("BAD;rm-fastboot fastboot usb:1-2\n", "partial", "MALFORMED_FASTBOOT_ROW"),
        (f"{SERIAL1} fastboot usb:bad/token\n", "partial", "MALFORMED_FASTBOOT_ROW"),
    ]
    for rows, status, expected in fixtures:
        result = check(
            FastbootInventory(executable=exe, reader=FakeRunner(devices=rows)).discover()
        )
        assert result["status"] == status
        assert codes(result) == [expected]
        assert result["devices"] == []


def test_t_h1f_04_run_only_version_and_device_listing_no_privileged_cli(
    tmp_path: Path,
) -> None:
    exe = binary(tmp_path)
    fake = FakeRunner(devices=f"{SERIAL1} fastboot\n")
    result = check(FastbootInventory(executable=exe, reader=fake).discover())
    assert result["status"] == "ok"
    assert [argv[1:] for argv in fake.calls] == [["--version"], ["devices", "-l"]]
    assert all(
        action not in str(fake.calls)
        for action in ("flash", "getvar", "unlock", "erase", "oem", "reboot", "update")
    )
    assert all(record["device_authorized"] is False for record in result["devices"])


def test_t_h1f_05_timeout_flood_and_reaped_synthetic_process(
    tmp_path: Path, monkeypatch: Any
) -> None:
    exe = binary(tmp_path)
    fake = FakeRunner()
    fake.fail_at = 1
    fake.failure = subprocess.TimeoutExpired([str(exe), "--version"], 0.1)
    timed = check(FastbootInventory(executable=exe, reader=fake).discover())
    assert timed["status"] == "unavailable" and codes(timed) == ["FASTBOOT_TIMEOUT"]
    fake = FakeRunner()
    fake.fail_at = 2
    fake.failure = OutputLimitExceeded("PRIVATE_DUMP")
    overflow = check(FastbootInventory(executable=exe, reader=fake).discover())
    assert overflow["status"] == "partial" and codes(overflow) == ["OUTPUT_LIMIT"]
    assert "PRIVATE_DUMP" not in str(overflow)

    popen = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []

    def record(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        proc: subprocess.Popen[bytes] = popen(*args, **kwargs)
        children.append(proc)
        return proc

    monkeypatch.setattr(subprocess, "Popen", record)
    with pytest.raises(subprocess.TimeoutExpired):
        bounded_run([sys.executable, "-c", "import time;time.sleep(8)"], 0.15, 65536)
    assert len(children) == 1 and children[0].poll() is not None
    with pytest.raises(ProcessLookupError):
        os.killpg(children[0].pid, 0)


def test_t_h1f_06_true_read_only_fastmcp_and_fake_localhost_http(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []

    class Stub:
        def run(self, **kwargs: Any) -> None:
            assert kwargs == {"transport": "http", "host": "127.0.0.1", "port": 8765}

    def make_server(**kwargs: Any) -> Stub:
        calls.append(kwargs)
        return Stub()

    with monkeypatch.context() as scoped:
        scoped.setattr(cli, "create_server", make_server)
        scoped.setattr(cli.platform, "system", lambda: "Linux")
        assert cli.main(["serve", "--fastboot-inventory"]) == 0
    assert len(calls) == 1 and "fastboot_inventory" in calls[0]

    exe = binary(tmp_path)
    fake_runner = FakeRunner(devices=f"{SERIAL1} fastboot usb:1-1\n")

    async def inprocess() -> None:
        async with Client(create_server()) as baseline:
            original = {tool.name: tool for tool in await baseline.list_tools()}
        assert set(original) == {"device_status", "adb_observe", "adb_develop"}
        inventory = FastbootInventory(executable=exe, reader=fake_runner)
        async with Client(create_server(fastboot_inventory=inventory)) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert set(tools) == {*original, "fastboot_devices_list"}
            for name, old in original.items():
                new = tools[name]
                assert (
                    old.title,
                    old.description,
                    old.annotations,
                    old.input_schema,
                    old.output_schema,
                ) == (
                    new.title,
                    new.description,
                    new.annotations,
                    new.input_schema,
                    new.output_schema,
                )
            tool = tools["fastboot_devices_list"]
            assert "No getvar" in tool.description
            assert tool.output_schema is not None
            assert tool.output_schema["$id"] == "urn:android-mcp:host-fastboot-inventory:v1"
            assert tool.annotations is not None
            hints = tool.annotations.model_dump(mode="json", by_alias=True)
            assert hints["readOnlyHint"] is True
            assert hints["destructiveHint"] is False
            assert hints["openWorldHint"] is False
            assert tool.input_schema.get("required", []) == []
            Draft202012Validator.check_schema(tool.input_schema)
            Draft202012Validator.check_schema(tool.output_schema)
            result = await client.call_tool("fastboot_devices_list", {})
            assert not result.is_error and isinstance(result.structured_content, dict)
            Draft202012Validator(tool.output_schema).validate(result.structured_content)
            assert result.structured_content["status"] == "ok"
            assert result.structured_content["devices"][0]["device_authorized"] is False

    asyncio.run(inprocess())

    trace = tmp_path / "fastboot-argv.jsonl"
    exe.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys\n"
        "from pathlib import Path\n"
        "a=sys.argv[1:]\n"
        "with Path(os.environ['H1F_FAKE_TRACE']).open('a') as f:f.write(json.dumps(a)+'\\n')\n"
        "if a == ['--version']: print('fastboot version 34.0.5')\n"
        "elif a == ['devices','-l']:\n"
        " print('SYNTHETIC-BOOTLOADER-01 fastboot usb:1-2')\n"
        "else: raise SystemExit(41)\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["H1F_FAKE_TRACE"] = str(trace)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    script = (
        "from pathlib import Path\n"
        "from android_mcp_host.fastboot_inventory import FastbootInventory\n"
        "from android_mcp_host.server import create_server\n"
        "import sys\n"
        "create_server(fastboot_inventory=FastbootInventory(executable=Path(sys.argv[1]))).run("
        "transport='http',host='127.0.0.1',port=int(sys.argv[2]))\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(exe), str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def http_check() -> None:
        last: Exception | None = None
        for _ in range(45):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    tools = {tool.name: tool for tool in await client.list_tools()}
                    reply = await client.call_tool("fastboot_devices_list", {})
                    assert not reply.is_error and isinstance(reply.structured_content, dict)
                    Draft202012Validator(tools["fastboot_devices_list"].output_schema).validate(
                        reply.structured_content
                    )
                    assert reply.structured_content["status"] == "ok"
                    assert reply.structured_content["fastboot"]["version"] == "34.0.5"
                    assert reply.structured_content["devices"][0]["mode"] == "unverified"
                    return
            except Exception as exc:
                last = exc
                await asyncio.sleep(0.1)
        raise AssertionError(f"Synthetic Fastboot localhost MCP failed: {last!r}")

    try:
        asyncio.run(http_check())
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)

    assert process.poll() is not None
    assert [json.loads(line) for line in trace.read_text().splitlines()] == [
        ["--version"],
        ["devices", "-l"],
    ]
