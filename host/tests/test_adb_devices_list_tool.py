"""H1.a: explicit, bounded ADB discovery without any device mutation."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator

from android_mcp_host.adb import AdbClient, AdbReport, Device, Diagnostic, parse_device_listing
from android_mcp_host.command_runner import OutputLimitExceeded, bounded_run
from android_mcp_host.server import create_server

SERIAL1 = "SYNTHETIC-TABLET-01"
SERIAL2 = "SYNTHETIC-EMULATOR-02"


class FakeAdb:
    def __init__(
        self, *devices: Device, error: Diagnostic | None = None, available: bool = True
    ) -> None:
        self.report = AdbReport(available, "/synthetic/adb", "37.0.1", error, devices)
        self.calls = 0

    def inspect(self) -> AdbReport:
        self.calls += 1
        return self.report


def _device(serial: str, state: str, transport: str | None) -> Device:
    return Device(serial, state, {"transport_id": transport} if transport is not None else {})


def _discover(adb: FakeAdb) -> dict[str, Any]:
    from android_mcp_host.device_discovery import DeviceDiscovery

    result: dict[str, Any] = DeviceDiscovery(adb).list_devices()  # type: ignore[arg-type]
    return result


def _codes(result: dict[str, Any]) -> list[str]:
    return [error["code"] for error in result["errors"]]


def test_t_h1a_01_exact_two_targets_preserve_serial_transport_and_states() -> None:
    adb = FakeAdb(
        _device(SERIAL1, "device", "7"),
        _device(SERIAL2, "offline", "11"),
    )
    result = _discover(adb)
    assert result["schema_version"] == 1
    assert result["runtime"] == "host"
    assert result["status"] == "ok"
    assert result["devices"] == [
        {
            "device_id": SERIAL1,
            "state": "device",
            "transport_id": "7",
            "ready_for_read": True,
        },
        {
            "device_id": SERIAL2,
            "state": "offline",
            "transport_id": "11",
            "ready_for_read": False,
        },
    ]
    assert result["errors"] == []
    assert adb.calls == 1


def test_t_h1a_02_empty_discovery_never_falls_back_to_cached_device() -> None:
    adb = FakeAdb()
    result = _discover(adb)
    assert result["status"] == "ok"
    assert result["devices"] == []
    assert result["errors"] == []
    assert adb.calls == 1


def test_t_h1a_03_nonready_and_malformed_rows_are_never_authorized() -> None:
    parsed = parse_device_listing(
        "List of devices attached\n"
        "SYNTHETIC-TABLET-01 offline transport_id:1\n"
        "SYNTHETIC-TABLET-02 unauthorized transport_id:2\n"
        "SYNTHETIC-TABLET-03 recovery transport_id:3\n"
        "SYNTHETIC-TABLET-04 device\n"
        "bad;command device transport_id:5\n"
        "SYNTHETIC-TABLET-05 nonsense transport_id:6\n"
    )
    assert len(parsed) == 4
    result = _discover(FakeAdb(*parsed))
    assert result["status"] == "partial"
    assert [device["state"] for device in result["devices"]] == [
        "offline",
        "unauthorized",
        "recovery",
        "device",
    ]
    assert [item["ready_for_read"] for item in result["devices"]] == [
        False,
        False,
        False,
        False,
    ]
    assert result["devices"][-1]["transport_id"] is None
    assert "MISSING_TRANSPORT_ID" in _codes(result)
    assert "bad;command" not in str(result)


@pytest.mark.parametrize(
    ("devices", "expected"),
    [
        (
            (_device(SERIAL1, "device", "7"), _device(SERIAL1, "device", "8")),
            "AMBIGUOUS_DEVICE_ID",
        ),
        (
            (_device(SERIAL1, "device", "7"), _device(SERIAL2, "device", "7")),
            "AMBIGUOUS_TRANSPORT_ID",
        ),
    ],
)
def test_t_h1a_04_duplicate_identifiers_fail_closed(
    devices: tuple[Device, Device], expected: str
) -> None:
    result = _discover(FakeAdb(*devices))
    assert result["status"] == "error"
    assert result["devices"] == []
    assert _codes(result) == [expected]


def test_t_h1a_05_missing_daemon_failure_timeout_and_64k_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (
        _discover(
            FakeAdb(error=Diagnostic("ADB_NOT_FOUND", "Install Platform Tools"), available=False)
        )["status"]
        == "unavailable"
    )

    commands: list[list[str]] = []

    def failure(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        commands.append(list(argv))
        if argv[-1] == "version":
            return subprocess.CompletedProcess(argv, 0, "Version 37.0.1", "")
        return subprocess.CompletedProcess(argv, 2, "", "SECRET_ENV_PASSWORD=fixture")

    discovery = AdbClient(executable="/synthetic/adb", runner=failure)
    result = _discover(discovery)  # type: ignore[arg-type]
    assert result["status"] == "partial"
    assert _codes(result) == ["ADB_LIST_FAILED"]
    assert "SECRET" not in str(result)
    assert commands == [["/synthetic/adb", "version"], ["/synthetic/adb", "devices", "-l"]]

    def timeout(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(argv, timeout)

    timed = _discover(AdbClient(executable="/synthetic/adb", runner=timeout))  # type: ignore[arg-type]
    assert timed["status"] == "unavailable"
    assert _codes(timed) == ["ADB_TIMEOUT"]

    def flooded(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        raise OutputLimitExceeded("private adb bytes")

    too_big = _discover(AdbClient(executable="/synthetic/adb", runner=flooded))  # type: ignore[arg-type]
    assert too_big["status"] == "unavailable"
    assert _codes(too_big) == ["ADB_OUTPUT_LIMIT"]
    assert "private adb bytes" not in str(too_big)

    real_popen = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []

    def track(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        child: subprocess.Popen[bytes] = real_popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", track)
    result_process = bounded_run(
        [sys.executable, "-c", "import os,time;os.write(1,b'x'*100000);time.sleep(8)"], 2.0, 65536
    )
    assert result_process.truncated and result_process.returncode != 0
    assert len(result_process.stdout.encode()) <= 65536
    assert children[0].poll() is not None
    with pytest.raises(ProcessLookupError):
        os.killpg(children[0].pid, 0)


def test_t_h1a_06_opt_in_real_fastmcp_catalog_schemas_and_local_http(tmp_path: Path) -> None:
    class StubDiscovery:
        def list_devices(self) -> dict[str, object]:
            return {
                "schema_version": 1,
                "runtime": "host",
                "status": "ok",
                "devices": [],
                "errors": [],
            }

    async def inprocess() -> None:
        async with Client(create_server()) as default:
            before = {t.name: t for t in await default.list_tools()}
        assert set(before) == {"device_status", "adb_observe", "adb_develop"}
        async with Client(create_server(adb_discovery=StubDiscovery())) as client:  # type: ignore[call-arg]
            catalog = {t.name: t for t in await client.list_tools()}
            assert set(catalog) == {*before, "adb_devices_list"}
            for name, old in before.items():
                new = catalog[name]
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
            tool = catalog["adb_devices_list"]
            assert tool.input_schema.get("required", []) == []
            assert not tool.input_schema.get("properties")
            assert tool.output_schema is not None
            assert tool.output_schema["$id"] == "urn:android-mcp:adb-device-list:v1"
            assert tool.annotations is not None
            hints = tool.annotations.model_dump(mode="json", by_alias=True)
            assert hints["readOnlyHint"] is False  # ADB discovery can start local daemon
            assert hints["destructiveHint"] is False
            assert hints["openWorldHint"] is False
            Draft202012Validator.check_schema(tool.output_schema)
            response = await client.call_tool("adb_devices_list", {})
            assert not response.is_error
            assert isinstance(response.structured_content, dict)
            Draft202012Validator(tool.output_schema).validate(response.structured_content)
            assert response.structured_content["devices"] == []

    asyncio.run(inprocess())

    fake = tmp_path / "adb"
    trace = tmp_path / "fake-commands.jsonl"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "a=sys.argv[1:]\n"
        "with Path(os.environ['FAKE_ADB_H1A_TRACE']).open('a') as f: f.write(json.dumps(a)+'\\n')\n"
        "if a==['version']: print('Version 37.0.1')\n"
        "elif a==['devices','-l']:\n"
        " print('List of devices attached')\n"
        " print('SYNTHETIC-TABLET-01 device transport_id:7')\n"
        "else: raise SystemExit(42)\n",
        encoding="utf-8",
    )
    fake.chmod(0o700)
    env = os.environ.copy()
    env["FAKE_ADB_H1A_TRACE"] = str(trace)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    script = (
        "import sys\nfrom android_mcp_host.adb import AdbClient\n"
        "from android_mcp_host.device_discovery import DeviceDiscovery\n"
        "from android_mcp_host.server import create_server\n"
        "from pathlib import Path\n"
        "create_server(adb_discovery=DeviceDiscovery(AdbClient(executable=sys.argv[1]))).run("
        "transport='http',host='127.0.0.1',port=int(sys.argv[2]))\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(fake), str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )

    async def smoke() -> None:
        last: Exception | None = None
        for _ in range(50):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    catalog = {t.name: t for t in await client.list_tools()}
                    assert "adb_devices_list" in catalog
                    reply = await client.call_tool("adb_devices_list", {})
                    assert not reply.is_error
                    assert isinstance(reply.structured_content, dict)
                    Draft202012Validator(catalog["adb_devices_list"].output_schema).validate(
                        reply.structured_content
                    )
                    assert reply.structured_content["devices"][0]["device_id"] == SERIAL1
                    return
            except Exception as error:
                last = error
                await asyncio.sleep(0.1)
        raise AssertionError(f"Synthetic device-list localhost MCP failed: {last!r}")

    try:
        asyncio.run(smoke())
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    assert process.poll() is not None
    commands = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    assert commands == [["version"], ["devices", "-l"]]
