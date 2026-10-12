"""H1.d: exact, bounded, redacted package inspection and MCP compatibility."""

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
from android_mcp_host.package_inspector import PackageInspector, get_package_output_schema
from android_mcp_host.server import create_server

SERIAL = "SYNTHETIC-DEVICE-01"
PKG = "com.example.app"
DUMP = (
    "Packages:\n"
    "  Package [com.example.app] (57c9):\n"
    "    userId=10444\n"
    "    versionCode=123 minSdk=26 targetSdk=36\n"
    "    versionName=2.1.0\n"
    "    requested permissions:\n"
    "      android.permission.INTERNET\n"
    "      android.permission.CAMERA\n"
    "    install permissions:\n"
    "      android.permission.INTERNET: granted=true\n"
    "      android.permission.CAMERA: granted=false\n"
    "  Package [com.example.app2] (private):\n"
    "    versionCode=98765 targetSdk=35\n"
    "    versionName=SECRET_NEVER_READ\n"
)


class FakeAdb:
    def __init__(
        self,
        *devices: Device,
        error: Diagnostic | None = None,
        available: bool = True,
        executable: str | None = "/fake/adb",
    ) -> None:
        self.calls = 0
        self.report = AdbReport(
            available, executable, "37", error, devices or (Device(SERIAL, "device", {}),)
        )

    def inspect(self) -> AdbReport:
        self.calls += 1
        return self.report


class Recorder:
    def __init__(self, output: str = DUMP) -> None:
        self.calls: list[list[str]] = []
        self.output = output
        self.stderr = ""
        self.returncode = 0
        self.failure: BaseException | None = None

    def __call__(self, argv: Sequence[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        assert 0 < timeout_s <= 10
        if self.failure is not None:
            raise self.failure
        return subprocess.CompletedProcess(argv, self.returncode, self.output, self.stderr)


def checked(response: dict[str, Any]) -> dict[str, Any]:
    Draft202012Validator(get_package_output_schema()).validate(response)
    assert response["schema_version"] == 1 and response["runtime"] == "host"
    return response


def codes(response: dict[str, Any]) -> list[str]:
    return [error["code"] for error in response["errors"]]


def test_t_h1d_01_one_exact_package_metadata_permissions_and_version() -> None:
    adb = FakeAdb()
    recorder = Recorder()
    body = checked(
        PackageInspector(adb=adb, reader=recorder).inspect(SERIAL, PKG)  # type: ignore[arg-type]
    )
    assert body["status"] == "ok"
    assert body["found"] is True
    assert body["package"] == PKG
    assert body["version_name"] == "2.1.0"
    assert body["version_code"] == 123
    assert body["target_sdk"] == 36
    assert body["requested_permissions"] == [
        "android.permission.INTERNET",
        "android.permission.CAMERA",
    ]
    assert body["granted_permissions"] == ["android.permission.INTERNET"]
    assert body["permissions_truncated"] is False and body["errors"] == []
    assert recorder.calls == [["/fake/adb", "-s", SERIAL, "shell", "dumpsys", "package", PKG]]
    assert adb.calls == 1
    assert "SECRET_NEVER_READ" not in json.dumps(body)
    assert "userId" not in json.dumps(body)


def test_t_h1d_02_absent_or_hidden_package_must_never_substitute_prefix_match() -> None:
    for dump, expected_status, code in (
        (
            DUMP.replace(
                "  Package [com.example.app] (57c9):", "  Package [com.example.other] (57c9):"
            ),
            "unavailable",
            "PACKAGE_VISIBILITY_UNKNOWN",
        ),
        ("Unable to find package: " + PKG, "unavailable", "PACKAGE_NOT_FOUND"),
        ("Packages:\n", "unavailable", "PACKAGE_VISIBILITY_UNKNOWN"),
    ):
        recorder = Recorder(dump)
        body = checked(
            PackageInspector(adb=FakeAdb(), reader=recorder).inspect(SERIAL, PKG)  # type: ignore[arg-type]
        )
        assert body["status"] == expected_status and codes(body) == [code]
        assert body["found"] is False and body["version_name"] is None
        assert body["requested_permissions"] == []
        assert "SECRET_NEVER_READ" not in str(body)
        assert len(recorder.calls) == 1


def test_t_h1d_03_hostile_package_names_and_options_are_denied_before_adb() -> None:
    denied = (
        ("-s", "INVALID_PACKAGE"),
        ("com.example.app; echo PWN", "INVALID_PACKAGE"),
        ("com/example/app", "INVALID_PACKAGE"),
        ("com..example", "INVALID_PACKAGE"),
        ("com.example.", "INVALID_PACKAGE"),
        ("com.1bad", "INVALID_PACKAGE"),
        ("com.exаmple.app", "INVALID_PACKAGE"),  # Cyrillic a
        ("com.example.app\ninstall", "INVALID_PACKAGE"),
        ("com." + "x" * 190, "INVALID_PACKAGE"),
        ("com", "INVALID_PACKAGE"),
    )
    for value, code in denied:
        adb, recorder = FakeAdb(), Recorder()
        body = checked(
            PackageInspector(adb=adb, reader=recorder).inspect(SERIAL, value)  # type: ignore[arg-type]
        )
        assert body["status"] == "error" and codes(body) == [code]
        assert body["package"] == ""
        assert adb.calls == 0 and recorder.calls == []
    for options in (
        {"permission_limit": 0},
        {"permission_limit": 33},
        {"permission_limit": True},
        {"include_permissions": "yes"},
    ):
        adb, recorder = FakeAdb(), Recorder()
        body = checked(
            PackageInspector(adb=adb, reader=recorder).inspect(SERIAL, PKG, **options)  # type: ignore[arg-type]
        )
        assert codes(body) == ["INVALID_OPTIONS"]
        assert adb.calls == 0 and recorder.calls == []


def test_t_h1d_04_permission_flood_and_secrets_are_truncated_not_echoed() -> None:
    permissions = "".join(f"      com.example.fake.P{i}\n" for i in range(200))
    adversarial = (
        "  Package [com.example.app] (test):\n"
        "    versionCode=999 targetSdk=33\n"
        "    versionName=3.0\n"
        "    requested permissions:\n" + permissions + "      token=private-secret\x1b[31m\n"
        "    install permissions:\n"
        "      com.example.fake.P0: granted=true\n"
    )
    recorder = Recorder(adversarial)
    body = checked(
        PackageInspector(adb=FakeAdb(), reader=recorder).inspect(SERIAL, PKG)  # type: ignore[arg-type]
    )
    assert body["status"] == "partial" and codes(body) == ["PARTIAL_DATA"]
    assert body["permissions_truncated"] is True
    assert len(body["requested_permissions"]) == 32
    assert body["granted_permissions"] == ["com.example.fake.P0"]
    assert "private-secret" not in str(body)
    assert "\x1b" not in str(body)

    recorder = Recorder("x" * 70000)
    body = checked(
        PackageInspector(adb=FakeAdb(), reader=recorder).inspect(SERIAL, PKG)  # type: ignore[arg-type]
    )
    assert body["status"] == "error" and codes(body) == ["OUTPUT_LIMIT"]
    assert len(str(body)) < 1500


def test_t_h1d_05_denials_timeout_permission_nonzero_and_reaped_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for adb, expected in (
        (FakeAdb(Device(SERIAL, "offline", {})), "DEVICE_NOT_READY"),
        (FakeAdb(Device(SERIAL, "unauthorized", {})), "DEVICE_NOT_READY"),
        (FakeAdb(Device("SYNTHETIC-OTHER", "device", {})), "DEVICE_NOT_FOUND"),
        (
            FakeAdb(Device(SERIAL, "device", {}), Device(SERIAL, "device", {})),
            "AMBIGUOUS_DEVICE_ID",
        ),
        (FakeAdb(error=Diagnostic("ADB_TIMEOUT", "token=SECRET")), "ADB_TIMEOUT"),
    ):
        recorder = Recorder()
        response = checked(
            PackageInspector(adb=adb, reader=recorder).inspect(SERIAL, PKG)  # type: ignore[arg-type]
        )
        assert codes(response) == [expected] and response["status"] == "error"
        assert recorder.calls == [] and "token=SECRET" not in str(response)

    for failure, code in (
        (subprocess.TimeoutExpired(["fake"], 0.1), "PROBE_TIMEOUT"),
        (PermissionError("PRIVATE_URL"), "PERMISSION_DENIED"),
        (OutputLimitExceeded("token=SECRET"), "OUTPUT_LIMIT"),
    ):
        recorder = Recorder()
        recorder.failure = failure
        response = checked(
            PackageInspector(adb=FakeAdb(), reader=recorder).inspect(SERIAL, PKG)  # type: ignore[arg-type]
        )
        assert codes(response) == [code] and response["status"] == "error"
        assert "PRIVATE_URL" not in str(response) and "SECRET" not in str(response)
    recorder = Recorder("INTERNAL SECRET TOKEN")
    recorder.returncode = 7
    response = checked(
        PackageInspector(adb=FakeAdb(), reader=recorder).inspect(SERIAL, PKG)  # type: ignore[arg-type]
    )
    assert codes(response) == ["PROBE_FAILED"] and response["status"] == "error"
    assert "SECRET" not in str(response)

    real_popen = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []

    def track(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        process = real_popen(*args, **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", track)
    flooded = bounded_run(
        [sys.executable, "-c", "import os,time;os.write(1,b'X'*100000);time.sleep(8)"],
        2.0,
        65536,
    )
    assert flooded.truncated and flooded.returncode != 0
    assert len(flooded.stdout.encode()) <= 65536
    assert len(children) == 1 and children[0].poll() is not None
    with pytest.raises(ProcessLookupError):
        os.killpg(children[0].pid, 0)


def test_t_h1d_06_opt_in_fastmcp_http_and_legacy_compatibility(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[dict[str, Any]] = []

    class StubServer:
        def run(self, **kwargs: Any) -> None:
            assert kwargs == {"transport": "http", "host": "127.0.0.1", "port": 8765}

    def create(**kwargs: Any) -> StubServer:
        events.append(kwargs)
        return StubServer()

    with monkeypatch.context() as patcher:
        patcher.setattr(cli, "create_server", create)
        patcher.setattr(cli.platform, "system", lambda: "Linux")
        assert cli.main(["serve", "--adb-package-inspect"]) == 0
    assert len(events) == 1 and "package_inspector" in events[0]

    async def inprocess() -> None:
        async with Client(create_server()) as old:
            originals = {tool.name: tool for tool in await old.list_tools()}
        assert set(originals) == {"device_status", "adb_observe", "adb_develop"}
        fake = FakeAdb()
        recorder = Recorder()
        async with Client(
            create_server(package_inspector=PackageInspector(fake, reader=recorder))  # type: ignore[arg-type]
        ) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert set(tools) == {*originals, "adb_package_inspect"}
            for name, before in originals.items():
                after = tools[name]
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
            tool = tools["adb_package_inspect"]
            assert tool.output_schema is not None
            assert tool.output_schema["$id"] == "urn:android-mcp:host-package-diagnostics:v1"
            assert tool.input_schema["required"] == ["device_id", "package"] or set(
                tool.input_schema["required"]
            ) == {"device_id", "package"}
            hints = tool.annotations.model_dump(mode="json", by_alias=True)
            assert hints["readOnlyHint"] is False
            assert hints["destructiveHint"] is False
            assert hints["openWorldHint"] is False
            Draft202012Validator.check_schema(tool.input_schema)
            Draft202012Validator.check_schema(tool.output_schema)
            reply = await client.call_tool(
                "adb_package_inspect",
                {"device_id": SERIAL, "package": PKG},
            )
            assert not reply.is_error and isinstance(reply.structured_content, dict)
            Draft202012Validator(tool.output_schema).validate(reply.structured_content)
            assert reply.structured_content["version_code"] == 123
            assert recorder.calls == [
                ["/fake/adb", "-s", SERIAL, "shell", "dumpsys", "package", PKG]
            ]
            denied = await client.call_tool(
                "adb_package_inspect",
                {"device_id": SERIAL, "package": PKG + "; sh"},
            )
            assert not denied.is_error and denied.structured_content["status"] == "error"
            assert denied.structured_content["errors"][0]["code"] == "INVALID_PACKAGE"
            assert len(recorder.calls) == 1
            assert not any(
                "install" in line or "uninstall" in line
                for line in str(tool.input_schema).splitlines()
            )

    asyncio.run(inprocess())
    fake_adb = tmp_path / "adb"
    trace = tmp_path / "trace.jsonl"
    fake_adb.write_text(
        "#!/usr/bin/env python3\n"
        "import os,sys,json\n"
        "from pathlib import Path\n"
        "a=sys.argv[1:]\n"
        "with Path(os.environ['H1D_TRACE']).open('a') as f: f.write(json.dumps(a)+'\\n')\n"
        "if a==['version']: print('Version 37.0.1')\n"
        "elif a==['devices','-l']:\n"
        " print('List of devices attached')\n"
        " print('SYNTHETIC-DEVICE-01 device transport_id:7')\n"
        "elif a==['-s','SYNTHETIC-DEVICE-01','shell','dumpsys','package','com.example.app']:\n"
        " print('  Package [com.example.app] (synthetic):')\n"
        " print('    versionCode=123 minSdk=26 targetSdk=36')\n"
        " print('    versionName=2.1.0')\n"
        "else: raise SystemExit(49)\n",
        encoding="utf-8",
    )
    fake_adb.chmod(0o700)
    env = os.environ.copy()
    env["H1D_TRACE"] = str(trace)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    script = (
        "import sys\n"
        "from android_mcp_host.adb import AdbClient\n"
        "from android_mcp_host.package_inspector import PackageInspector\n"
        "from android_mcp_host.server import create_server\n"
        "create_server(package_inspector=PackageInspector(AdbClient(executable=sys.argv[1]))).run("
        "transport='http',host='127.0.0.1',port=int(sys.argv[2]))\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(fake_adb), str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def http_check() -> None:
        last: Exception | None = None
        for _ in range(50):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    catalog = {t.name: t for t in await client.list_tools()}
                    assert "adb_package_inspect" in catalog
                    reply = await client.call_tool(
                        "adb_package_inspect", {"device_id": SERIAL, "package": PKG}
                    )
                    assert not reply.is_error and isinstance(reply.structured_content, dict)
                    Draft202012Validator(catalog["adb_package_inspect"].output_schema).validate(
                        reply.structured_content
                    )
                    assert reply.structured_content["status"] == "ok"
                    assert reply.structured_content["version_name"] == "2.1.0"
                    return
            except Exception as error:
                last = error
                await asyncio.sleep(0.1)
        raise AssertionError(f"Synthetic package-inspection localhost MCP failed: {last!r}")

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
    assert [json.loads(row) for row in trace.read_text(encoding="utf-8").splitlines()] == [
        ["version"],
        ["devices", "-l"],
        ["-s", SERIAL, "shell", "dumpsys", "package", PKG],
    ]
