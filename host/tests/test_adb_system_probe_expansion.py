"""H1.c: typed bounded system probes alongside unchanged legacy v1 catalog."""

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
from android_mcp_host.adb import AdbReport, Device, Diagnostic
from android_mcp_host.command_runner import OutputLimitExceeded, bounded_run
from android_mcp_host.probes import PROBES
from android_mcp_host.server import create_server
from android_mcp_host.system_snapshot import COMMANDS, SystemSnapshot, get_snapshot_output_schema

SERIAL = "SYNTHETIC-SYSTEM-01"
GOOD = {
    "api_level": "36\n",
    "model": "SyntheticTablet\n",
    "battery": (
        "Current Battery Service state:\n"
        "  AC powered: true\n"
        "  USB powered: false\n"
        "  level: 85\n"
        "  scale: 100\n"
        "  temperature: 265\n"
    ),
    "storage": (
        "Filesystem 1K-blocks Used Available Use% Mounted on\n"
        "/dev/block/dm-51 2000000 750000 1250000 37% /data\n"
    ),
    "size": "Physical size: 2560x1600\n",
    "density": "Physical density: 320\n",
    "network": "Active default network: 106\n",
}
EXPECTED = [
    {"group": "identity", "values": {"api_level": 36, "model": "SyntheticTablet"}},
    {
        "group": "battery",
        "values": {
            "battery_percent": 85.0,
            "battery_temperature_c": 26.5,
            "battery_ac_powered": True,
        },
    },
    {"group": "storage", "values": {"total_kib": 2000000, "free_kib": 1250000}},
    {"group": "display", "values": {"width_px": 2560, "height_px": 1600, "density_dpi": 320}},
    {"group": "network", "values": {"default_network_connected": True}},
]


class FakeAdb:
    def __init__(
        self,
        *devices: Device,
        available: bool = True,
        error: Diagnostic | None = None,
    ) -> None:
        self.calls = 0
        self.report = AdbReport(
            available,
            "/fake/adb",
            "37.0.1",
            error,
            devices or (Device(SERIAL, "device", {}),),
        )

    def inspect(self) -> AdbReport:
        self.calls += 1
        return self.report


class FakeReader:
    def __init__(self, **overrides: str) -> None:
        self.values = {**GOOD, **overrides}
        self.calls: list[list[str]] = []
        self.fail_at: int | None = None
        self.flood_at: int | None = None

    def __call__(self, argv: Sequence[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        assert 0 < timeout_s <= 10
        if self.fail_at is not None and len(self.calls) == self.fail_at:
            raise subprocess.TimeoutExpired(argv, timeout_s)
        if self.flood_at is not None and len(self.calls) == self.flood_at:
            raise OutputLimitExceeded("private output")
        return subprocess.CompletedProcess(argv, 0, self.values[self._key(argv)], "")

    @staticmethod
    def _key(argv: Sequence[str]) -> str:
        lookup = {suffix: name for group in COMMANDS.values() for name, suffix in group}
        key = lookup.get(tuple(argv[3:]))
        if key is None:
            raise AssertionError(f"Disallowed subprocess argv: {argv!r}")
        return key


def _checked(response: dict[str, Any]) -> dict[str, Any]:
    Draft202012Validator(get_snapshot_output_schema()).validate(response)
    assert response["schema_version"] == 1
    assert response["runtime"] == "host"
    return response


def _codes(response: dict[str, Any]) -> list[str]:
    return [entry["code"] for entry in response["errors"]]


def test_t_h1c_01_five_fixed_typed_groups_preserve_v1_host_shape() -> None:
    adb = FakeAdb()
    reader = FakeReader()
    service = SystemSnapshot(adb=adb, reader=reader)  # type: ignore[arg-type]
    reply = _checked(
        service.inspect(SERIAL, ["identity", "battery", "storage", "display", "network"])
    )
    assert reply["status"] == "ok"
    assert reply["device_id"] == SERIAL
    assert reply["results"] == EXPECTED
    assert reply["errors"] == []
    assert len(reader.calls) == 7 and adb.calls == 1
    assert all(argv[:3] == ["/fake/adb", "-s", SERIAL] for argv in reader.calls)
    assert all(argv[3] == "shell" for argv in reader.calls)
    assert [argv[4] for argv in reader.calls] == [
        "getprop",
        "getprop",
        "dumpsys",
        "df",
        "wm",
        "wm",
        "dumpsys",
    ]
    assert set(PROBES) == {
        "identity",
        "compatibility",
        "boot",
        "battery",
        "display",
        "storage",
        "selinux",
        "shell_identity",
        "third_party_packages",
    }


def test_t_h1c_02_invalid_groups_and_count_rejected_without_processes() -> None:
    inputs = [
        ("-s", ["battery"], "INVALID_DEVICE_ID"),
        (SERIAL + "; rm /tmp/fake", ["battery"], "INVALID_DEVICE_ID"),
        (SERIAL, [], "INVALID_GROUPS"),
        (SERIAL, ["identity"] * 6, "INVALID_GROUPS"),
        (SERIAL, "battery", "INVALID_GROUPS"),
        (SERIAL, {"battery": True}, "INVALID_GROUPS"),
        (SERIAL, ["shell"], "UNKNOWN_GROUP"),
        (SERIAL, ["dumpsys activity"], "UNKNOWN_GROUP"),
        (SERIAL, [17], "UNKNOWN_GROUP"),
        (SERIAL, ["battery", "battery"], "DUPLICATE_GROUPS"),
    ]
    for serial, groups, code in inputs:
        adb, reader = FakeAdb(), FakeReader()
        result = _checked(SystemSnapshot(adb=adb, reader=reader).inspect(serial, groups))  # type: ignore[arg-type]
        assert result["status"] == "error"
        assert _codes(result) == [code]
        assert result["results"] == []
        assert adb.calls == 0 and reader.calls == []


def test_t_h1c_03_bad_numeric_utf8_and_missing_fields_stay_explicitly_partial() -> None:
    reader = FakeReader(
        api_level="notanumber\n",
        model="Bad\ufffdModel\n",
        battery="level: 150\nscale: 100\ntemperature: 9999\nAC powered: yes\n",
        storage="Filesystem 1K-blocks Used Available Use% Mounted on\n/dev/a 10 2 20 20% /data",
        size="Physical size: 99999x1600\n",
        density="Physical density: 0\n",
        network="Active default network: Bearer SECRET_TOKEN\n",
    )
    response = _checked(
        SystemSnapshot(adb=FakeAdb(), reader=reader).inspect(  # type: ignore[arg-type]
            SERIAL, ["identity", "battery", "storage", "display", "network"]
        )
    )
    assert response["status"] == "partial"
    assert _codes(response) == ["PARTIAL_DATA"]
    assert [group["values"] for group in response["results"]] == [{}, {}, {}, {}, {}]
    assert "SECRET_TOKEN" not in json.dumps(response)
    assert "Bad" not in json.dumps(response)


def test_t_h1c_04_offline_unauthorized_unknown_ambiguous_denied_before_probe() -> None:
    situations = [
        (FakeAdb(Device(SERIAL, "offline", {})), "DEVICE_NOT_READY"),
        (FakeAdb(Device(SERIAL, "unauthorized", {})), "DEVICE_NOT_READY"),
        (FakeAdb(Device("OTHER", "device", {})), "DEVICE_NOT_FOUND"),
        (
            FakeAdb(Device(SERIAL, "device", {}), Device(SERIAL, "device", {})),
            "AMBIGUOUS_DEVICE_ID",
        ),
        (FakeAdb(available=False), "ADB_NOT_FOUND"),
        (FakeAdb(error=Diagnostic("ADB_TIMEOUT", "sensitive stderr")), "ADB_TIMEOUT"),
    ]
    for adb, code in situations:
        reader = FakeReader()
        response = _checked(
            SystemSnapshot(adb=adb, reader=reader).inspect(SERIAL, ["network"])  # type: ignore[arg-type]
        )
        assert response["status"] == "error" and _codes(response) == [code]
        assert reader.calls == []
        assert "sensitive" not in str(response)


def test_t_h1c_05_timeout_flood_partial_and_reaped_subprocess(monkeypatch: Any) -> None:
    timeout_reader = FakeReader()
    timeout_reader.fail_at = 2
    partial = _checked(
        SystemSnapshot(adb=FakeAdb(), reader=timeout_reader).inspect(  # type: ignore[arg-type]
            SERIAL, ["battery", "storage"]
        )
    )
    assert partial["status"] == "partial" and _codes(partial) == ["PROBE_TIMEOUT"]
    assert partial["results"] == [EXPECTED[1]]
    assert len(timeout_reader.calls) == 2

    overflow_reader = FakeReader()
    overflow_reader.flood_at = 1
    flooded = _checked(
        SystemSnapshot(adb=FakeAdb(), reader=overflow_reader).inspect(  # type: ignore[arg-type]
            SERIAL, ["network"]
        )
    )
    assert flooded["status"] == "error" and _codes(flooded) == ["OUTPUT_LIMIT"]
    assert "private output" not in str(flooded)

    real_popen = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []

    def track(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        child = real_popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", track)
    result = bounded_run(
        [sys.executable, "-c", "import os,time;os.write(1,b'x'*100000);time.sleep(7)"], 2.0, 65536
    )
    assert result.truncated is True and result.returncode != 0
    assert len(result.stdout.encode()) <= 65536
    assert len(children) == 1 and children[0].poll() is not None
    with pytest.raises(ProcessLookupError):
        os.killpg(children[0].pid, 0)


def test_t_h1c_06_opt_in_flag_and_public_inprocess_http_are_v1_compatible(
    monkeypatch: Any, tmp_path: Path
) -> None:
    calls: list[dict[str, Any]] = []

    class Stub:
        def run(self, **kwargs: Any) -> None:
            assert kwargs == {"transport": "http", "host": "127.0.0.1", "port": 8765}

    def make_server(**kwargs: Any) -> Stub:
        calls.append(kwargs)
        return Stub()

    with monkeypatch.context() as patcher:
        patcher.setattr(cli, "create_server", make_server)
        patcher.setattr(cli.platform, "system", lambda: "Linux")
        assert cli.main(["serve", "--adb-system-snapshot"]) == 0
    assert len(calls) == 1 and "system_snapshot" in calls[0]

    class StubSnapshot:
        def inspect(self, serial: str, groups: list[str]) -> dict[str, Any]:
            return _checked(
                SystemSnapshot(adb=FakeAdb(), reader=FakeReader()).inspect(  # type: ignore[arg-type]
                    serial, groups
                )
            )

    async def inprocess() -> None:
        async with Client(create_server()) as old:
            original = {tool.name: tool for tool in await old.list_tools()}
        assert set(original) == {"device_status", "adb_observe", "adb_develop"}
        async with Client(create_server(system_snapshot=StubSnapshot())) as client:  # type: ignore[arg-type]
            catalog = {tool.name: tool for tool in await client.list_tools()}
            assert set(catalog) == {*original, "adb_system_snapshot"}
            for name, before in original.items():
                after = catalog[name]
                assert (
                    before.title,
                    before.description,
                    before.annotations,
                    before.input_schema,
                    before.output_schema,
                ) == (
                    after.title,
                    after.description,
                    after.annotations,
                    after.input_schema,
                    after.output_schema,
                )
            tool = catalog["adb_system_snapshot"]
            assert tool.output_schema is not None
            assert tool.output_schema["$id"] == "urn:android-mcp:host-system-snapshot:v1"
            assert tool.annotations is not None
            hint = tool.annotations.model_dump(mode="json", by_alias=True)
            assert hint["readOnlyHint"] is False
            assert hint["destructiveHint"] is False
            assert hint["openWorldHint"] is False
            Draft202012Validator.check_schema(tool.output_schema)
            Draft202012Validator.check_schema(tool.input_schema)
            assert set(tool.input_schema["required"]) == {"device_id", "groups"}
            result = await client.call_tool(
                "adb_system_snapshot", {"device_id": SERIAL, "groups": ["battery"]}
            )
            assert not result.is_error and isinstance(result.structured_content, dict)
            Draft202012Validator(tool.output_schema).validate(result.structured_content)
            assert result.structured_content["results"] == [EXPECTED[1]]

    asyncio.run(inprocess())

    fake = tmp_path / "adb"
    trace = tmp_path / "trace.jsonl"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import os,sys,json\n"
        "from pathlib import Path\n"
        "a=sys.argv[1:]\n"
        "with Path(os.environ['H1C_FAKE_TRACE']).open('a') as f:f.write(json.dumps(a)+'\\n')\n"
        "if a==['version']: print('Version 37.0.1')\n"
        "elif a==['devices','-l']:\n"
        " print('List of devices attached')\n"
        " print('SYNTHETIC-SYSTEM-01 device transport_id:7')\n"
        "elif a==['-s','SYNTHETIC-SYSTEM-01','shell','getprop','ro.build.version.sdk']:\n"
        " print('36')\n"
        "elif a==['-s','SYNTHETIC-SYSTEM-01','shell','getprop','ro.product.model']:\n"
        " print('SyntheticTablet')\n"
        "else: raise SystemExit(49)\n",
        encoding="utf-8",
    )
    fake.chmod(0o700)
    env = os.environ.copy()
    env["H1C_FAKE_TRACE"] = str(trace)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    script = (
        "import sys\n"
        "from android_mcp_host.adb import AdbClient\n"
        "from android_mcp_host.system_snapshot import SystemSnapshot\n"
        "from android_mcp_host.server import create_server\n"
        "create_server(system_snapshot=SystemSnapshot(AdbClient(executable=sys.argv[1]))).run("
        "transport='http',host='127.0.0.1',port=int(sys.argv[2]))\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(fake), str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def http_check() -> None:
        last: Exception | None = None
        for _ in range(50):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    tool = {t.name: t for t in await client.list_tools()}["adb_system_snapshot"]
                    response = await client.call_tool(
                        "adb_system_snapshot", {"device_id": SERIAL, "groups": ["identity"]}
                    )
                    assert not response.is_error
                    assert isinstance(response.structured_content, dict)
                    Draft202012Validator(tool.output_schema).validate(response.structured_content)
                    assert response.structured_content["status"] == "ok"
                    assert response.structured_content["results"] == [EXPECTED[0]]
                    return
            except Exception as error:
                last = error
                await asyncio.sleep(0.1)
        raise AssertionError(f"Synthetic system-snapshot localhost MCP failed: {last!r}")

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
    assert [json.loads(row) for row in trace.read_text().splitlines()] == [
        ["version"],
        ["devices", "-l"],
        ["-s", SERIAL, "shell", "getprop", "ro.build.version.sdk"],
        ["-s", SERIAL, "shell", "getprop", "ro.product.model"],
    ]
