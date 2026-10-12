"""H1.b: target-pinned, read-only ADB transport and forwarding inspection.

No tests use a physical device, connection write, pairing or port creation.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator

from android_mcp_host import cli
from android_mcp_host.adb import AdbReport, Device, Diagnostic
from android_mcp_host.adb_transport import AdbTransport, get_transport_output_schema
from android_mcp_host.command_runner import OutputLimitExceeded, bounded_run
from android_mcp_host.server import create_server

SERIAL = "SYNTHETIC-TABLET-01"
OTHER = "SYNTHETIC-TABLET-02"
TRANSPORT = "7"


def _report(
    serial: str = SERIAL,
    state: str = "device",
    transport: str = TRANSPORT,
    *,
    available: bool = True,
    error: Diagnostic | None = None,
    others: tuple[Device, ...] = (),
) -> AdbReport:
    devices = (Device(serial, state, {"transport_id": transport}), *others)
    return AdbReport(available, "/fake/adb", "37.0.1", error, devices)


class FakeAdb:
    def __init__(self, *reports: AdbReport):
        self._reports = reports
        self.calls = 0

    def inspect(self) -> AdbReport:
        index = min(self.calls, len(self._reports) - 1)
        self.calls += 1
        return self._reports[index]


class FakeReader:
    def __init__(self, *, forward: str = "", reverse: str = "", mdns: str = "") -> None:
        self.calls: list[list[str]] = []
        self.forward = forward
        self.reverse = reverse
        self.mdns = mdns
        self.failed: BaseException | None = None
        self.exit_code = 0

    def __call__(
        self, argv: Any, timeout_s: float, byte_limit: int
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        assert 0 < timeout_s <= 3.0 and byte_limit == 65536
        if self.failed is not None:
            raise self.failed
        if argv[1:] == ["-s", SERIAL, "forward", "--list"]:
            output = self.forward
        elif argv[1:] == ["-s", SERIAL, "reverse", "--list"]:
            output = self.reverse
        elif argv[1:] == ["mdns", "services"]:
            output = self.mdns
        else:
            raise AssertionError(f"Unexpected command: {argv!r}")
        return subprocess.CompletedProcess(argv, self.exit_code, output, "")


def _checked(response: dict[str, Any]) -> dict[str, Any]:
    Draft202012Validator(get_transport_output_schema()).validate(response)
    assert response["schema_version"] == 1
    assert response["runtime"] == "host"
    return response


def _codes(response: dict[str, Any]) -> list[str]:
    return [error["code"] for error in response["errors"]]


def test_t_h1b_01_exact_offline_device_becomes_ready_with_bounded_poll() -> None:
    clock = [0.0]
    waits: list[float] = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        clock[0] += seconds

    adb = FakeAdb(_report(state="offline"), _report(state="device"))
    runner = FakeReader()
    service = AdbTransport(adb=adb, runner=runner, clock=lambda: clock[0], sleeper=sleep)  # type: ignore[arg-type]
    reply = _checked(service.inspect(device_id=SERIAL, transport_id=TRANSPORT, wait_seconds=1.0))
    assert reply["status"] == "ok"
    assert reply["observed_state"] == "device"
    assert reply["device_id"] == SERIAL and reply["transport_id"] == TRANSPORT
    assert reply["routes"] == [] and reply["mdns"] is None and reply["errors"] == []
    assert waits == [0.25]
    assert adb.calls == 2
    assert runner.calls == []


def test_t_h1b_02_missing_stale_unauthorized_ambiguous_and_changed_targets_denied() -> None:
    cases = [
        (_report(serial=OTHER), "DEVICE_NOT_FOUND"),
        (_report(transport="99"), "STALE_TRANSPORT_ID"),
        (_report(state="unauthorized"), "DEVICE_NOT_READY"),
        (_report(state="authorizing"), "DEVICE_NOT_READY"),
        (_report(state="no_permissions"), "DEVICE_NOT_READY"),
        (_report(others=(Device(SERIAL, "device", {"transport_id": "8"}),)), "AMBIGUOUS_DEVICE_ID"),
        (
            _report(others=(Device(OTHER, "device", {"transport_id": TRANSPORT}),)),
            "AMBIGUOUS_TRANSPORT_ID",
        ),
        (_report(error=Diagnostic("ADB_LIST_FAILED", "sensitive stderr")), "ADB_LIST_FAILED"),
        (_report(available=False), "ADB_NOT_FOUND"),
    ]
    for report, code in cases:
        runner = FakeReader()
        adb = FakeAdb(report)
        service = AdbTransport(adb=adb, runner=runner)  # type: ignore[arg-type]
        reply = _checked(
            service.inspect(device_id=SERIAL, transport_id=TRANSPORT, include_routes=True)
        )
        assert reply["status"] == "error" and _codes(reply) == [code]
        assert runner.calls == []
        assert adb.calls == 1
        assert "sensitive" not in str(reply)

    clock = [0.0]
    stale = FakeAdb(_report(state="offline"), _report(transport="11"))
    waiting = AdbTransport(
        adb=stale,
        clock=lambda: clock[0],
        sleeper=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )  # type: ignore[arg-type]
    reply = _checked(waiting.inspect(device_id=SERIAL, transport_id=TRANSPORT, wait_seconds=2.0))
    assert reply["status"] == "error" and _codes(reply) == ["STALE_TRANSPORT_ID"]
    assert reply["observed_state"] == "offline"
    assert stale.calls == 2


def test_t_h1b_03_bad_serial_transport_state_wait_and_mdns_are_pre_dispatch_denials() -> None:
    inputs = [
        ({"device_id": "-s"}, "INVALID_TARGET"),
        ({"device_id": "SYNTHETIC; rm /tmp/test"}, "INVALID_TARGET"),
        ({"transport_id": "0"}, "INVALID_TARGET"),
        ({"transport_id": "7; shell id"}, "INVALID_TARGET"),
        ({"target_state": "reboot"}, "INVALID_TARGET_STATE"),
        ({"target_state": "disconnect"}, "INVALID_TARGET_STATE"),
        ({"wait_seconds": -0.1}, "INVALID_WAIT"),
        ({"wait_seconds": 100}, "INVALID_WAIT"),
        ({"wait_seconds": float("nan")}, "INVALID_WAIT"),
        ({"wait_seconds": True}, "INVALID_WAIT"),
        ({"include_routes": "true"}, "INVALID_OPTIONS"),
        ({"include_mdns": 1}, "INVALID_OPTIONS"),
        ({"mdns_endpoint": "10.0.0.5:37000"}, "INVALID_MDNS_ENDPOINT"),
        ({"include_mdns": True, "mdns_endpoint": "10.0.0.5:99999"}, "INVALID_MDNS_ENDPOINT"),
        (
            {"include_mdns": True, "mdns_endpoint": "host.local:4444;rm -rf /"},
            "INVALID_MDNS_ENDPOINT",
        ),
        ({"include_mdns": True, "mdns_endpoint": "[invalid]:4444"}, "INVALID_MDNS_ENDPOINT"),
    ]
    for arguments, expected in inputs:
        fake = FakeAdb(_report())
        reader = FakeReader()
        service = AdbTransport(adb=fake, runner=reader)  # type: ignore[arg-type]
        reply = _checked(
            service.inspect(**{"device_id": SERIAL, "transport_id": TRANSPORT, **arguments})
        )
        assert reply["status"] == "error" and _codes(reply) == [expected]
        assert fake.calls == 0 and reader.calls == []
        assert "rm -rf" not in str(reply)


def test_t_h1b_04_read_only_forward_reverse_and_mdns_inspection_redacts_addresses() -> None:
    runner = FakeReader(
        forward=(
            f"{SERIAL} tcp:4001 tcp:6001\n"
            f"{OTHER} tcp:9999 tcp:9999\n"
            f"{SERIAL} localabstract:SECRET_TOKEN tcp:1234\n"
        ),
        reverse=f"{SERIAL} tcp:7555 tcp:8100\n",
        mdns=(
            "List of discovered mdns services\n"
            "SYNTHETIC._adb-tls-connect._tcp. 10.0.0.5:37123\n"
            "BOGUS._adb-tls-connect._tcp. token:password\n"
        ),
    )
    service = AdbTransport(adb=FakeAdb(_report()), runner=runner)  # type: ignore[arg-type]
    reply = _checked(
        service.inspect(
            device_id=SERIAL,
            transport_id=TRANSPORT,
            include_routes=True,
            include_mdns=True,
            mdns_endpoint="10.0.0.5:37123",
        )
    )
    assert reply["status"] == "partial"
    assert reply["routes"] == [
        {"direction": "forward", "local_port": 4001, "remote_port": 6001},
        {"direction": "reverse", "local_port": 7555, "remote_port": 8100},
    ]
    assert reply["mdns"] == {"service_count": 1, "endpoint_found": True}
    assert _codes(reply) == ["MALFORMED_ROUTE", "MALFORMED_MDNS_ROW"]
    assert runner.calls == [
        ["/fake/adb", "-s", SERIAL, "forward", "--list"],
        ["/fake/adb", "-s", SERIAL, "reverse", "--list"],
        ["/fake/adb", "mdns", "services"],
    ]
    rendered = json.dumps(reply)
    assert "10.0.0.5" not in rendered and "SECRET_TOKEN" not in rendered
    assert "token:password" not in rendered and OTHER not in rendered
    assert "tcp:" not in rendered


def test_t_h1b_05_disconnection_timeout_cancel_output_limit_and_reaped_child(
    monkeypatch: Any,
) -> None:
    clock = [0.0]

    def sleep(seconds: float) -> None:
        clock[0] += seconds

    disconnected = AdbTransport(
        adb=FakeAdb(_report(state="offline"), AdbReport(True, "/fake/adb", "37", None, ())),
        clock=lambda: clock[0],
        sleeper=sleep,
    )  # type: ignore[arg-type]
    gone = _checked(disconnected.inspect(device_id=SERIAL, transport_id=TRANSPORT, wait_seconds=1))
    assert gone["status"] == "error" and _codes(gone) == ["DISCONNECTED"]

    clock[0] = 0
    offline = FakeAdb(_report(state="offline"))
    waiting = AdbTransport(adb=offline, clock=lambda: clock[0], sleeper=sleep)  # type: ignore[arg-type]
    timed = _checked(waiting.inspect(device_id=SERIAL, transport_id=TRANSPORT, wait_seconds=0.5))
    assert timed["status"] == "timeout" and _codes(timed) == ["WAIT_TIMEOUT"]
    assert offline.calls == 3

    event = threading.Event()
    clock[0] = 0
    cancelled = FakeAdb(_report(state="offline"))

    def cancel_during_wait(seconds: float) -> None:
        clock[0] += seconds
        event.set()

    cancel_service = AdbTransport(adb=cancelled, clock=lambda: clock[0], sleeper=cancel_during_wait)  # type: ignore[arg-type]
    stop = _checked(
        cancel_service.inspect(
            device_id=SERIAL, transport_id=TRANSPORT, wait_seconds=2, cancel=event
        )
    )
    assert stop["status"] == "cancelled" and _codes(stop) == ["CANCELLED"]
    assert cancelled.calls == 1

    runner = FakeReader()
    runner.failed = OutputLimitExceeded("private flooded stderr")
    partial = _checked(
        AdbTransport(adb=FakeAdb(_report()), runner=runner).inspect(  # type: ignore[arg-type]
            device_id=SERIAL, transport_id=TRANSPORT, include_routes=True
        )
    )
    assert partial["status"] == "partial" and _codes(partial) == ["OUTPUT_LIMIT"]
    assert "private flooded" not in str(partial)

    real_popen = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []

    def track(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        child = real_popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", track)
    with pytest.raises(subprocess.TimeoutExpired):
        bounded_run([sys.executable, "-c", "import time; time.sleep(8)"], 0.1, 65536)
    assert len(children) == 1 and children[0].poll() is not None
    with pytest.raises(ProcessLookupError):
        os.killpg(children[0].pid, 0)


def test_t_h1b_06_opt_in_mcp_contract_and_fake_localhost_http(tmp_path: Path) -> None:
    class StubTransport:
        def inspect(self, **kwargs: Any) -> dict[str, Any]:
            return _checked(
                AdbTransport(adb=FakeAdb(_report())).inspect(  # type: ignore[arg-type]
                    device_id=kwargs["device_id"], transport_id=kwargs["transport_id"]
                )
            )

    async def inprocess() -> None:
        async with Client(create_server()) as base:
            original = {tool.name: tool for tool in await base.list_tools()}
        assert set(original) == {"device_status", "adb_observe", "adb_develop"}
        async with Client(create_server(adb_transport=StubTransport())) as client:  # type: ignore[arg-type]
            catalog = {tool.name: tool for tool in await client.list_tools()}
            assert set(catalog) == {*original, "adb_transport_inspect"}
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
            tool = catalog["adb_transport_inspect"]
            assert "inspect" in tool.description.lower()
            assert tool.output_schema is not None
            assert tool.output_schema["$id"] == "urn:android-mcp:adb-transport-inspection:v1"
            assert tool.annotations is not None
            hints = tool.annotations.model_dump(mode="json", by_alias=True)
            assert hints["readOnlyHint"] is False  # ADB may start local daemon
            assert hints["destructiveHint"] is False
            assert hints["openWorldHint"] is False
            Draft202012Validator.check_schema(tool.output_schema)
            Draft202012Validator.check_schema(tool.input_schema)
            assert set(tool.input_schema["required"]) == {"device_id", "transport_id"}
            response = await client.call_tool(
                "adb_transport_inspect", {"device_id": SERIAL, "transport_id": TRANSPORT}
            )
            assert not response.is_error and isinstance(response.structured_content, dict)
            Draft202012Validator(tool.output_schema).validate(response.structured_content)
            assert response.structured_content["status"] == "ok"
            denied = await client.call_tool(
                "adb_transport_inspect", {"device_id": "-s", "transport_id": TRANSPORT}
            )
            assert not denied.is_error
            assert [e["code"] for e in denied.structured_content["errors"]] == ["INVALID_TARGET"]

    asyncio.run(inprocess())
    fake = tmp_path / "adb"
    trace = tmp_path / "requests.jsonl"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys\n"
        "from pathlib import Path\n"
        "a=sys.argv[1:]\n"
        "with Path(os.environ['FAKE_ADB_H1B_TRACE']).open('a') as f: f.write(json.dumps(a)+'\\n')\n"
        "if a == ['version']: print('Version 37.0.1')\n"
        "elif a == ['devices','-l']:\n"
        " print('List of devices attached')\n"
        " print('SYNTHETIC-TABLET-01 device transport_id:7')\n"
        "elif a == ['-s','SYNTHETIC-TABLET-01','forward','--list']:\n"
        " print('SYNTHETIC-TABLET-01 tcp:4001 tcp:6001')\n"
        "elif a == ['-s','SYNTHETIC-TABLET-01','reverse','--list']:\n"
        " print('SYNTHETIC-TABLET-01 tcp:7555 tcp:8100')\n"
        "else: raise SystemExit(41)\n",
        encoding="utf-8",
    )
    fake.chmod(0o700)
    env = os.environ.copy()
    env["FAKE_ADB_H1B_TRACE"] = str(trace)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    program = (
        "from pathlib import Path\n"
        "import sys\n"
        "from android_mcp_host.adb import AdbClient\n"
        "from android_mcp_host.adb_transport import AdbTransport\n"
        "from android_mcp_host.server import create_server\n"
        "create_server(adb_transport=AdbTransport(AdbClient(executable=sys.argv[1]))).run("
        "transport='http',host='127.0.0.1',port=int(sys.argv[2]))\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", program, str(fake), str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )

    async def http_check() -> None:
        last: Exception | None = None
        for _ in range(50):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    catalog = {tool.name: tool for tool in await client.list_tools()}
                    assert "adb_transport_inspect" in catalog
                    output = await client.call_tool(
                        "adb_transport_inspect",
                        {
                            "device_id": SERIAL,
                            "transport_id": TRANSPORT,
                            "include_routes": True,
                        },
                    )
                    assert not output.is_error
                    assert isinstance(output.structured_content, dict)
                    Draft202012Validator(catalog["adb_transport_inspect"].output_schema).validate(
                        output.structured_content
                    )
                    assert output.structured_content["status"] == "ok"
                    assert len(output.structured_content["routes"]) == 2
                    return
            except Exception as error:
                last = error
                await asyncio.sleep(0.1)
        raise AssertionError(f"Synthetic H1.b HTTP transport inspection failed: {last!r}")

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
    commands = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    assert commands == [
        ["version"],
        ["devices", "-l"],
        ["-s", SERIAL, "forward", "--list"],
        ["-s", SERIAL, "reverse", "--list"],
    ]


def test_t_h1b_06_transport_tool_is_explicitly_opt_in(monkeypatch: Any) -> None:
    """A Host-local flag, not a model argument, controls tool registration."""

    class Server:
        def run(self, **kwargs: Any) -> None:
            assert kwargs == {"transport": "http", "host": "127.0.0.1", "port": 8765}

    calls: list[dict[str, Any]] = []

    def make_server(**kwargs: Any) -> Server:
        calls.append(kwargs)
        return Server()

    monkeypatch.setattr(cli, "create_server", make_server)
    monkeypatch.setattr(cli.platform, "system", lambda: "Linux")
    assert cli.main(["serve", "--adb-transport-inspect"]) == 0
    assert len(calls) == 1
    assert "adb_transport" in calls[0]
