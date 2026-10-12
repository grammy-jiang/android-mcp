"""H1.e fixed allowlisted, bounded, best-effort-redacted Logcat."""

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
from android_mcp_host.logcat_filters import LogcatFilters, get_logcat_output_schema
from android_mcp_host.server import create_server

SERIAL = "FAKE-DEVICE-01"
L1 = "10-12 12:00:00.000 1000 1000 I MyTag: network waiting\n"
L2 = "10-12 12:00:00.100 1000 1000 E MyTag: password=hunter2 Bearer secret123\n"
L3 = "10-12 12:00:00.200 1000 1000 W Other: password=private\n"


class FakeAdb:
    def __init__(self, *devices: Device, available: bool = True, error: Diagnostic | None = None):
        self.calls = 0
        self.report = AdbReport(
            available,
            "/synthetic/adb",
            "37.0.1",
            error,
            devices or (Device(SERIAL, "device", {}),),
        )

    def inspect(self) -> AdbReport:
        self.calls += 1
        return self.report


class Reader:
    def __init__(self, output: str = L1 + L2 + L3, *, pid_output: str = "1234\n"):
        self.output = output
        self.pid_output = pid_output
        self.calls: list[list[str]] = []
        self.failure: BaseException | None = None
        self.returncode = 0
        self.stderr = ""

    def __call__(self, argv: Sequence[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        assert 0.1 <= timeout_s <= 10
        if self.failure is not None:
            raise self.failure
        if argv[3:] == ["shell", "pidof", "com.example.application"]:
            return subprocess.CompletedProcess(argv, 0, self.pid_output, "")
        return subprocess.CompletedProcess(argv, self.returncode, self.output, self.stderr)


def capture(reader: Reader, *, adb: FakeAdb | None = None, **kwargs: Any) -> dict[str, Any]:
    return LogcatFilters(adb=adb or FakeAdb(), reader=reader).capture(SERIAL, **kwargs)  # type: ignore[arg-type]


def checked(reply: dict[str, Any]) -> dict[str, Any]:
    Draft202012Validator(get_logcat_output_schema()).validate(reply)
    assert reply["schema_version"] == 1 and reply["runtime"] == "host"
    return reply


def codes(reply: dict[str, Any]) -> list[str]:
    return [error["code"] for error in reply["errors"]]


def test_t_h1e_01_exact_tag_package_priority_compiles_fixed_argv_and_redacts() -> None:
    runner = Reader()
    result = checked(
        capture(runner, lines=20, tag="MyTag", severity="W", package="com.example.application")
    )
    assert result["status"] == "ok"
    assert result["filters"] == {
        "tag": "MyTag",
        "severity": "W",
        "package": "com.example.application",
    }
    assert result["entries"] == [
        {"priority": "E", "tag": "MyTag", "message": "password=[REDACTED] Bearer [REDACTED]"}
    ]
    assert runner.calls == [
        ["/synthetic/adb", "-s", SERIAL, "shell", "pidof", "com.example.application"],
        [
            "/synthetic/adb",
            "-s",
            SERIAL,
            "logcat",
            "-d",
            "-t",
            "20",
            "-v",
            "threadtime",
            "--pid=1234",
            "MyTag:W",
            "*:S",
        ],
    ]


def test_t_h1e_02_malformed_filters_times_and_oversized_lines_prevent_dispatch() -> None:
    cases = [
        {"lines": 1},
        {"lines": 201},
        {"lines": True},
        {"tag": "Tag;rm -rf /"},
        {"tag": "a" * 50},
        {"tag": ["MyTag"]},
        {"severity": "S"},
        {"severity": "arbitrary"},
        {"severity": 2},
        {"package": "com.example; touch /tmp/fake"},
        {"package": "/data/data/com.example"},
        {"timeout_s": -1},
        {"timeout_s": 11},
        {"timeout_s": float("nan")},
        {"timeout_s": "forever"},
    ]
    for args in cases:
        runner, adb = Reader(), FakeAdb()
        result = checked(capture(runner, adb=adb, **args))
        assert result["status"] == "error"
        assert codes(result) == ["INVALID_ARGUMENTS"]
        assert runner.calls == [] and adb.calls == 0


def test_t_h1e_03_tokens_credentials_identifiers_ansi_and_emails_are_redacted() -> None:
    log = (
        "10-12 12:00:00.010 1000 1000 E Auth: "
        'Authorization: Bearer abc-token token=very-secret password="secret phrase" '
        "api_key=ABCDEF email=a.person@example.com ip=192.168.12.1 "
        "mac=aa:bb:cc:dd:ee:ff id=123456789012 mobile=0400111222 "
        + SERIAL
        + " \x1b[31mALERT\x1b[0m\n"
    )
    result = checked(capture(Reader(output=log), lines=20))
    assert result["status"] == "ok"
    text = result["entries"][0]["message"]
    for secret in (
        "abc-token",
        "very-secret",
        "secret phrase",
        "ABCDEF",
        "a.person@example.com",
        "192.168.12.1",
        "aa:bb:cc:dd:ee:ff",
        "123456789012",
        "0400111222",
        SERIAL,
        "\x1b",
    ):
        assert secret not in text
    assert "Authorization=[REDACTED]" in text
    assert "password=[REDACTED]" in text
    assert "[DEVICE]" in text


def test_t_h1e_04_offline_unauthorized_ambiguous_missing_device_never_fallback() -> None:
    cases = [
        (FakeAdb(Device(SERIAL, "offline", {})), "DEVICE_NOT_READY"),
        (FakeAdb(Device(SERIAL, "unauthorized", {})), "DEVICE_NOT_READY"),
        (
            FakeAdb(Device(SERIAL, "device", {}), Device(SERIAL, "device", {})),
            "AMBIGUOUS_DEVICE_ID",
        ),
        (FakeAdb(Device("OTHER", "device", {})), "DEVICE_NOT_FOUND"),
        (FakeAdb(available=False), "ADB_NOT_FOUND"),
        (FakeAdb(error=Diagnostic("ADB_TIMEOUT", "private stderr")), "ADB_TIMEOUT"),
    ]
    for adb, error in cases:
        runner = Reader()
        result = checked(capture(runner, adb=adb))
        assert result["status"] == "error" and codes(result) == [error]
        assert runner.calls == []
        assert "private stderr" not in str(result)
    invalid = LogcatFilters(adb=FakeAdb(), reader=Reader()).capture("-s")  # type: ignore[arg-type]
    assert codes(checked(invalid)) == ["INVALID_DEVICE_ID"]


def test_t_h1e_05_timeouts_oversized_and_partial_capture_cleanup(monkeypatch: Any) -> None:
    runner = Reader()
    runner.failure = subprocess.TimeoutExpired(["/fake/adb"], 0.1)
    timed = checked(capture(runner))
    assert timed["status"] == "timeout" and codes(timed) == ["LOGCAT_TIMEOUT"]
    runner.failure = OutputLimitExceeded("sensitive logcat payload")
    truncated = checked(capture(runner))
    assert truncated["status"] == "partial" and codes(truncated) == ["OUTPUT_LIMIT"]
    assert "sensitive logcat" not in str(truncated)
    partly = checked(capture(Reader(output=L1 + "unparsed private log entry\n" + L2)))
    assert partly["status"] == "partial" and partly["truncated"] is True
    assert codes(partly) == ["PARTIAL_DATA"] and len(partly["entries"]) == 2
    assert "private log entry" not in str(partly)

    popen = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []

    def track(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        child: subprocess.Popen[bytes] = popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", track)
    with pytest.raises(subprocess.TimeoutExpired):
        bounded_run([sys.executable, "-c", "import time;time.sleep(8)"], 0.15, 65536)
    assert len(children) == 1 and children[0].poll() is not None
    with pytest.raises(ProcessLookupError):
        os.killpg(children[0].pid, 0)


def test_t_h1e_06_legacy_tool_catalog_and_opt_in_mcp_http(monkeypatch: Any, tmp_path: Path) -> None:
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
        assert cli.main(["serve", "--adb-logcat-filter"]) == 0
    assert len(calls) == 1 and "logcat_filter" in calls[0]

    async def check_inprocess() -> None:
        async with Client(create_server()) as baseline:
            before = {tool.name: tool for tool in await baseline.list_tools()}
        assert set(before) == {"device_status", "adb_observe", "adb_develop"}
        injected = LogcatFilters(adb=FakeAdb(), reader=Reader())  # type: ignore[arg-type]
        async with Client(create_server(logcat_filter=injected)) as client:
            catalog = {tool.name: tool for tool in await client.list_tools()}
            assert set(catalog) == {*before, "adb_logcat_filter"}
            for name, original in before.items():
                current = catalog[name]
                assert (
                    original.title,
                    original.description,
                    original.annotations,
                    original.input_schema,
                    original.output_schema,
                ) == (
                    current.title,
                    current.description,
                    current.annotations,
                    current.input_schema,
                    current.output_schema,
                )
            tool = catalog["adb_logcat_filter"]
            assert "sensitive" in tool.description.lower()
            assert tool.output_schema is not None
            assert tool.output_schema["$id"] == "urn:android-mcp:host-logcat-filters:v1"
            assert tool.annotations is not None
            hints = tool.annotations.model_dump(mode="json", by_alias=True)
            assert hints["readOnlyHint"] is False
            assert hints["destructiveHint"] is False
            assert hints["openWorldHint"] is False
            assert set(tool.input_schema["required"]) == {"device_id"}
            Draft202012Validator.check_schema(tool.input_schema)
            Draft202012Validator.check_schema(tool.output_schema)
            response = await client.call_tool(
                "adb_logcat_filter", {"device_id": SERIAL, "lines": 20, "tag": "MyTag"}
            )
            assert not response.is_error
            assert isinstance(response.structured_content, dict)
            Draft202012Validator(tool.output_schema).validate(response.structured_content)
            assert response.structured_content["status"] == "ok"
            assert len(response.structured_content["entries"]) == 2

    asyncio.run(check_inprocess())

    adb = tmp_path / "adb"
    trace = tmp_path / "trace.jsonl"
    adb.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys\n"
        "from pathlib import Path\n"
        "args=sys.argv[1:]\n"
        "with Path(os.environ['H1E_FAKE_TRACE']).open('a') as f:"
        " f.write(json.dumps(args)+'\\n')\n"
        "if args==['version']: print('Version 37.0.1')\n"
        "elif args==['devices','-l']:\n"
        " print('List of devices attached')\n"
        " print('FAKE-DEVICE-01 device transport_id:7')\n"
        "elif args==['-s','FAKE-DEVICE-01','logcat','-d','-t','20',"
        "'-v','threadtime','MyTag:E','*:S']:\n"
        " print('10-12 12:00:00.100 1000 1000 E MyTag: password=hunter2')\n"
        "else: raise SystemExit(44)\n",
        encoding="utf-8",
    )
    adb.chmod(0o700)
    env = os.environ.copy()
    env["H1E_FAKE_TRACE"] = str(trace)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    script = (
        "import sys\n"
        "from android_mcp_host.adb import AdbClient\n"
        "from android_mcp_host.logcat_filters import LogcatFilters\n"
        "from android_mcp_host.server import create_server\n"
        "create_server(logcat_filter=LogcatFilters(AdbClient(executable=sys.argv[1]))).run("
        "transport='http',host='127.0.0.1',port=int(sys.argv[2]))\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(adb), str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def http_check() -> None:
        last: Exception | None = None
        for _ in range(40):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    tools = {tool.name: tool for tool in await client.list_tools()}
                    output = await client.call_tool(
                        "adb_logcat_filter",
                        {"device_id": SERIAL, "lines": 20, "tag": "MyTag", "severity": "E"},
                    )
                    assert not output.is_error and isinstance(output.structured_content, dict)
                    Draft202012Validator(tools["adb_logcat_filter"].output_schema).validate(
                        output.structured_content
                    )
                    assert output.structured_content["status"] == "ok"
                    assert (
                        output.structured_content["entries"][0]["message"] == "password=[REDACTED]"
                    )
                    return
            except Exception as error:
                last = error
                await asyncio.sleep(0.1)
        raise AssertionError(f"H1.e synthetic localhost HTTP failed: {last!r}")

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
        ["version"],
        ["devices", "-l"],
        ["-s", SERIAL, "logcat", "-d", "-t", "20", "-v", "threadtime", "MyTag:E", "*:S"],
    ]
