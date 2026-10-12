"""Public FastMCP surface characterization via real tools/list and tools/call.

Intent markers used below:

* REQUIRED: behavior protected by docs/security.md or the refactor plan. A
  future FastMCP refactor must keep it (or change it through an approved
  contract decision).
* OBSERVED_ONLY: behavior seen at the Wave 0 baseline that is deliberately
  asserted loosely, so it is documented but not frozen.

Application JSON schemas live in contracts/; nothing here duplicates them.
Advertised output schemas, titles, annotations and string->bool coercion are
intentionally NOT asserted. Everything uses injected fakes: no ADB, no device.
"""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Awaitable, Callable
from typing import Any

from fastmcp import Client

from android_mcp_host.adb import AdbReport, Device
from android_mcp_host.command_runner import RunResult
from android_mcp_host.operations import MAX_RESULT_CHARS, OperationService
from android_mcp_host.probes import ProbeService
from android_mcp_host.server import create_server

TOOLS = ["device_status", "adb_observe", "adb_develop"]
DEVICE = "MOCK-01"
LOGCAT = {"type": "logcat_snapshot"}
INSTRUMENT = {
    "type": "instrument_test",
    "package": "com.example.tests",
    "runner": "androidx.test.runner.AndroidJUnitRunner",
}


class FakeAdb:
    def __init__(self, *devices: Device):
        self.devices = devices or (Device(DEVICE, "device", {}),)

    def inspect(self) -> AdbReport:
        return AdbReport(True, "/fake/adb", "37", None, self.devices)


class Recorder:
    """Fake probe reader and operation runner that log every dispatch."""

    def __init__(
        self, stdout: str = "ok\n", returncode: int = 0, timeout_after: int | None = None
    ) -> None:
        self.stdout = stdout
        self.timeout_after = timeout_after
        self.returncode = returncode
        self.reads: list[list[str]] = []
        self.runs: list[list[str]] = []

    def read(self, argv, timeout_s):
        self.reads.append(list(argv))
        if self.timeout_after is not None and len(self.reads) > self.timeout_after:
            raise subprocess.TimeoutExpired(argv, timeout_s)
        return subprocess.CompletedProcess(argv, self.returncode, stdout=self.stdout, stderr="")

    def run(self, argv, timeout_s, byte_limit):
        self.runs.append(list(argv))
        return RunResult(self.returncode, self.stdout, "", False)


def _exercise(
    body: Callable[[Client, Recorder], Awaitable[None]],
    *devices: Device,
    recorder: Recorder | None = None,
) -> Recorder:
    rec = recorder or Recorder()

    async def go() -> None:
        adb = FakeAdb(*devices)
        server = create_server(
            adb=adb,  # type: ignore[arg-type]
            probes=ProbeService(adb, reader=rec.read),  # type: ignore[arg-type]
            operations=OperationService(adb, runner=rec.run),  # type: ignore[arg-type]
        )
        async with Client(server) as client:
            await body(client, rec)

    asyncio.run(go())
    return rec


def _errors(result: Any) -> list[str]:
    return [error["code"] for error in result.structured_content["errors"]]


def test_required_catalog_and_input_metadata():
    async def body(client, _rec):
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert sorted(tools) == sorted(TOOLS)  # REQUIRED: exactly these three
        for tool in tools.values():
            assert tool.description  # REQUIRED: model-visible description
            assert tool.input_schema["type"] == "object"
        assert tools["device_status"].input_schema.get("required", []) == []
        observe = tools["adb_observe"].input_schema
        assert set(observe["required"]) == {"device_id", "probes"}
        develop = tools["adb_develop"].input_schema
        assert set(develop["required"]) == {"device_id", "action"}
        assert "dry_run" in develop["properties"]  # optional, defaulted
        # Not asserted: outputSchema, title, annotations (OBSERVED_ONLY/proposed).

    _exercise(body)


def test_required_status_envelope_and_read_only_observation():
    async def body(client, rec):
        status = await client.call_tool("device_status", {})
        assert not status.is_error
        assert status.structured_content["schema_version"] == 1
        assert status.structured_content["runtime"] == "host"
        for key in ("host", "capabilities", "adb", "devices", "errors"):
            assert key in status.data
        assert [d["device_id"] for d in status.structured_content["devices"]] == [DEVICE]

        seen = await client.call_tool("adb_observe", {"device_id": DEVICE, "probes": ["selinux"]})
        assert not seen.is_error
        assert seen.structured_content["schema_version"] == 1
        assert seen.structured_content["runtime"] == "host"
        assert seen.structured_content["device_id"] == DEVICE
        assert seen.structured_content["status"] == "ok"
        assert seen.structured_content["errors"] == []
        assert seen.structured_content["results"][0]["probe"] == "selinux"
        # REQUIRED: fixed argv with an explicit -s serial and no free-form shell.
        assert rec.reads == [["/fake/adb", "-s", DEVICE, "shell", "getenforce"]]

    _exercise(body)


def test_required_observe_denials_never_dispatch_and_app_error_is_not_mcp_error():
    async def body(client, rec):
        cases = {
            "INVALID_DEVICE_ID": {"device_id": "-s", "probes": ["selinux"]},
            "INVALID_PROBE": {"device_id": DEVICE, "probes": ["shell"]},
            "INVALID_PROBES": {"device_id": DEVICE, "probes": ["boot", "boot"]},
            "DEVICE_NOT_FOUND": {"device_id": "OTHER-9", "probes": ["boot"]},
        }
        for code, args in cases.items():
            result = await client.call_tool("adb_observe", args)
            # OBSERVED_ONLY: application failure is a normal MCP result
            # (is_error False) with status "error"; a refactor may change the
            # transport level only via an approved P2 decision.
            assert result.is_error is False
            assert result.structured_content["status"] == "error"
            assert code in _errors(result)
        assert rec.reads == []  # REQUIRED: nothing dispatched for denied calls

    _exercise(body)


def test_required_offline_device_is_refused_without_dispatch():
    async def body(client, rec):
        result = await client.call_tool("adb_observe", {"device_id": DEVICE, "probes": ["boot"]})
        assert result.structured_content["status"] == "error"
        assert _errors(result) == ["DEVICE_NOT_READY"]
        develop = await client.call_tool("adb_develop", {"device_id": DEVICE, "action": LOGCAT})
        assert develop.structured_content["status"] == "error"
        assert _errors(develop) == ["DEVICE_NOT_READY"]
        assert rec.reads == [] and rec.runs == []

    _exercise(body, Device(DEVICE, "offline", {}))


def test_required_duplicate_device_entries_are_ambiguous():
    async def body(client, rec):
        result = await client.call_tool("adb_observe", {"device_id": DEVICE, "probes": ["boot"]})
        assert _errors(result) == ["AMBIGUOUS_DEVICE_ID"]
        assert rec.reads == []

    _exercise(body, Device(DEVICE, "device", {}), Device(DEVICE, "device", {}))


def test_required_develop_denials_never_dispatch():
    async def body(client, rec):
        unknown = await client.call_tool(
            "adb_develop", {"device_id": DEVICE, "action": {"type": "raw_shell", "cmd": "id"}}
        )
        assert unknown.is_error is False  # OBSERVED_ONLY two-level error semantics
        assert unknown.structured_content["status"] == "error"
        assert _errors(unknown) == ["UNKNOWN_OPERATION"]

        bad_device = await client.call_tool("adb_develop", {"device_id": "-s", "action": LOGCAT})
        assert _errors(bad_device) == ["INVALID_DEVICE_ID"]

        mutation = await client.call_tool(
            "adb_develop", {"device_id": DEVICE, "action": INSTRUMENT}
        )
        assert mutation.is_error is False
        assert mutation.structured_content["status"] == "error"
        assert mutation.structured_content["mutating"] is True
        assert _errors(mutation) == ["MUTATION_DISABLED"]
        assert rec.runs == []  # REQUIRED: no command executed for any denial

    _exercise(body)


def test_required_dry_run_previews_mutation_without_dispatch():
    async def body(client, rec):
        plan = await client.call_tool(
            "adb_develop", {"device_id": DEVICE, "action": INSTRUMENT, "dry_run": True}
        )
        assert plan.is_error is False
        assert plan.structured_content["status"] == "planned"
        assert plan.structured_content["mutating"] is True
        assert plan.structured_content["command"][:3] == ["adb", "-s", DEVICE]
        assert rec.runs == []

    _exercise(body)


def test_required_read_only_action_dispatches_once_with_explicit_device():
    async def body(client, rec):
        result = await client.call_tool("adb_develop", {"device_id": DEVICE, "action": LOGCAT})
        assert result.is_error is False
        assert result.structured_content["status"] == "ok"
        assert result.structured_content["mutating"] is False
        assert len(rec.runs) == 1
        assert rec.runs[0][1:3] == ["-s", DEVICE]

    _exercise(body)


def test_required_oversized_output_is_bounded_and_flagged_partial():
    async def body(client, rec):
        result = await client.call_tool("adb_develop", {"device_id": DEVICE, "action": LOGCAT})
        assert result.structured_content["status"] == "partial"  # REQUIRED: never silently "ok"
        assert result.structured_content["result"]["truncated"] is True
        assert len(result.structured_content["result"]["stdout"]) <= MAX_RESULT_CHARS
        assert "OUTPUT_LIMIT" in _errors(result)

    _exercise(body, recorder=Recorder(stdout="x" * (MAX_RESULT_CHARS + 50)))


def test_required_observation_failure_after_first_probe_is_partial():
    async def body(client, _rec):
        result = await client.call_tool(
            "adb_observe", {"device_id": DEVICE, "probes": ["selinux", "shell_identity"]}
        )
        assert result.is_error is False
        assert result.structured_content["status"] == "partial"
        assert [r["probe"] for r in result.structured_content["results"]] == ["selinux"]
        assert _errors(result) == ["PROBE_TIMEOUT"]

    _exercise(body, recorder=Recorder(timeout_after=1))


def test_observed_only_wrong_input_type_is_mcp_level_error():
    """OBSERVED_ONLY: schema violations fail at the MCP layer, not as an envelope."""

    async def body(client, rec):
        result = await client.call_tool(
            "adb_observe",
            {"device_id": DEVICE, "probes": "selinux"},
            raise_on_error=False,
        )
        assert result.is_error is True  # exact message/shape intentionally unchecked
        assert rec.reads == []

    _exercise(body)
