"""H0.a: locked, device-free baseline of the three public Host MCP tools.

The hashes pin the *advertised* JSON schemas, not just source schema files.
Every synthetic serial and command is fictitious. No real ADB is executed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from typing import Any

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator

from android_mcp_host.adb import AdbReport, Device
from android_mcp_host.command_runner import RunResult, bounded_run
from android_mcp_host.mcp_boundary import get_output_schema
from android_mcp_host.operations import MAX_RESULT_CHARS, OUTPUT_BYTE_LIMIT, OperationService
from android_mcp_host.probes import ProbeService
from android_mcp_host.server import create_server

DEVICE = "SYNTHETIC-H0A-01"
INSTRUMENT = {
    "type": "instrument_test",
    "package": "com.example.test",
    "runner": "com.example.TestRunner",
}
GOLDEN = {
    "device_status": {
        "title": "Inspect Android Host and ADB",
        "description": "Inspect host platform and ADB device states; never change a device.",
        "hints": (False, False, True, False),
        "input_digest": "99334726611ccf58a148b0814696bfa6fe08c1b2d027e946beccf5a74331c9aa",
        "output_digest": "0766d8495eb2cfed9c947f62d77ee59fbffb3c77cf0837fa5b9557ca42e7784f",
        "schema_id": "urn:android-mcp:device-status:v1",
    },
    "adb_observe": {
        "title": "Read Selected Android Device Diagnostics",
        "description": (
            "Read selected device diagnostics: identity, boot, battery, display,\n"
            "storage, selinux, shell_identity, third_party_packages, compatibility. Read-only.\n"
            "The serial must match one online, authorized device from device_status."
        ),
        "hints": (False, False, True, False),
        "input_digest": "e1abaf059d031dfeaae64290ca0792289bb169f4a816576c6bcc2d989f2c0d48",
        "output_digest": "772421db6cd162dd1e66d75b45ad44fe0f4485ad0e0c413b240178a5c71b67c2",
        "schema_id": "urn:android-mcp:adb-observation:v1",
    },
    "adb_develop": {
        "title": "Typed Android Engineering Diagnostics and Plans",
        "description": (
            "Perform typed, bounded package/logcat diagnostics and action planning.\n\n"
            "Instrumentation can be previewed without changing the device. APK\n"
            "installation is refused unless trusted Host directories are configured.\n"
            "Execution of mutation additionally requires independent operator\n"
            "approval, device lease and durable audit; default Host disables it."
        ),
        "hints": (False, True, False, False),
        "input_digest": "a428bcdce35c6276e6d29e1cc7b122759a71049e7e9af0ecc0e585b5ca1ce802",
        "output_digest": "bcb7a9fe51504c5e8f3724ad5c51245945edf59eca8c75279c5489a3ecc27039",
        "schema_id": "urn:android-mcp:adb-development:v1",
    },
}


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _catalog(tools: Any) -> dict[str, dict[str, Any]]:
    observed = {}
    for tool in tools:
        assert tool.annotations is not None
        assert tool.output_schema is not None
        hints = tool.annotations.model_dump(mode="json", by_alias=True)
        observed[tool.name] = {
            "title": tool.title,
            "description": tool.description,
            "hints": tuple(
                hints[field]
                for field in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")
            ),
            "input_digest": _digest(tool.input_schema),
            "output_digest": _digest(tool.output_schema),
            "schema_id": tool.output_schema["$id"],
        }
    return observed


class FakeAdb:
    def __init__(self, *devices: Device) -> None:
        self.devices = devices or (Device(DEVICE, "device", {}),)

    def inspect(self) -> AdbReport:
        return AdbReport(True, "/synthetic/adb", "37.0.1", None, self.devices)


class Recorder:
    def __init__(self) -> None:
        self.reads: list[list[str]] = []
        self.runs: list[list[str]] = []
        self.timeout = False
        self.flood = False

    def read(self, argv: Any, timeout_s: float) -> subprocess.CompletedProcess[str]:
        self.reads.append(list(argv))
        if self.timeout:
            raise subprocess.TimeoutExpired(argv, timeout_s)
        return subprocess.CompletedProcess(argv, 0, "Enforcing\n", "")

    def run(self, argv: list[str], timeout_s: float, byte_limit: int) -> RunResult:
        self.runs.append(list(argv))
        assert byte_limit == OUTPUT_BYTE_LIMIT
        if self.timeout:
            raise subprocess.TimeoutExpired(argv, timeout_s)
        if self.flood:
            return RunResult(-9, "x" * byte_limit, "", True)
        return RunResult(0, "synthetic diagnostic\n", "", False)


def _server(recorder: Recorder, *devices: Device) -> Any:
    adb = FakeAdb(*devices)
    return create_server(
        adb=adb,  # type: ignore[arg-type]
        probes=ProbeService(adb, reader=recorder.read),  # type: ignore[arg-type]
        operations=OperationService(adb, runner=recorder.run),  # type: ignore[arg-type]
    )


def _validated(reply: Any, schema: dict[str, object]) -> dict[str, Any]:
    assert reply.is_error is False
    assert isinstance(reply.structured_content, dict)
    Draft202012Validator(schema).validate(reply.structured_content)
    return reply.structured_content


def test_t_h0a_01_catalog_metadata_and_schemas_are_frozen() -> None:
    async def check() -> None:
        async with Client(_server(Recorder())) as client:
            tools = await client.list_tools()
            assert _catalog(tools) == GOLDEN
            for tool in tools:
                Draft202012Validator.check_schema(tool.input_schema)
                Draft202012Validator.check_schema(tool.output_schema)

    asyncio.run(check())


def test_t_h0a_02_valid_results_match_canonical_structured_schemas() -> None:
    async def check() -> None:
        rec = Recorder()
        async with Client(_server(rec)) as client:
            status = _validated(
                await client.call_tool("device_status", {}), get_output_schema("device_status")
            )
            assert status["devices"][0]["device_id"] == DEVICE
            observe = _validated(
                await client.call_tool("adb_observe", {"device_id": DEVICE, "probes": ["selinux"]}),
                get_output_schema("adb_observe"),
            )
            assert observe["status"] == "ok"
            assert observe["results"][0]["fields"]["enforcement"] == "Enforcing"
            develop = _validated(
                await client.call_tool(
                    "adb_develop", {"device_id": DEVICE, "action": {"type": "logcat_snapshot"}}
                ),
                get_output_schema("adb_develop"),
            )
            assert develop["status"] == "ok" and develop["mutating"] is False
            assert rec.reads == [["/synthetic/adb", "-s", DEVICE, "shell", "getenforce"]]
            assert len(rec.runs) == 1 and rec.runs[0][1:3] == ["-s", DEVICE]

    asyncio.run(check())


def test_t_h0a_03_domain_denials_dispatch_nothing() -> None:
    async def check() -> None:
        rec = Recorder()
        async with Client(_server(rec)) as client:
            for args, code in (
                ({"device_id": "-s", "probes": ["boot"]}, "INVALID_DEVICE_ID"),
                ({"device_id": DEVICE, "probes": ["arbitrary_shell"]}, "INVALID_PROBE"),
                ({"device_id": DEVICE, "probes": ["boot", "boot"]}, "INVALID_PROBES"),
            ):
                body = _validated(
                    await client.call_tool("adb_observe", args), get_output_schema("adb_observe")
                )
                assert body["status"] == "error"
                assert [e["code"] for e in body["errors"]] == [code]
            unknown = _validated(
                await client.call_tool(
                    "adb_develop", {"device_id": DEVICE, "action": {"type": "shell", "cmd": "id"}}
                ),
                get_output_schema("adb_develop"),
            )
            assert unknown["status"] == "error"
            assert [e["code"] for e in unknown["errors"]] == ["UNKNOWN_OPERATION"]
            assert rec.reads == [] and rec.runs == []

    asyncio.run(check())


def test_t_h0a_04_physical_mutation_denied_but_preview_is_inert() -> None:
    async def check() -> None:
        rec = Recorder()
        async with Client(_server(rec)) as client:
            args = {"device_id": DEVICE, "action": INSTRUMENT}
            denied = _validated(
                await client.call_tool("adb_develop", args), get_output_schema("adb_develop")
            )
            assert denied["status"] == "error" and denied["mutating"] is True
            assert [e["code"] for e in denied["errors"]] == ["MUTATION_DISABLED"]
            preview = _validated(
                await client.call_tool("adb_develop", {**args, "dry_run": True}),
                get_output_schema("adb_develop"),
            )
            assert preview["status"] == "planned"
            assert preview["mutating"] is True and preview["result"] is None
            assert preview["command"][:3] == ["adb", "-s", DEVICE]
            assert rec.reads == [] and rec.runs == []

    asyncio.run(check())


def test_t_h0a_05_timeout_target_denial_and_64k_flood_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def check() -> None:
        for state in ("offline", "unauthorized"):
            rec = Recorder()
            async with Client(_server(rec, Device(DEVICE, state, {}))) as client:
                for tool, args, schema in (
                    ("adb_observe", {"device_id": DEVICE, "probes": ["boot"]}, "adb_observe"),
                    (
                        "adb_develop",
                        {"device_id": DEVICE, "action": {"type": "logcat_snapshot"}},
                        "adb_develop",
                    ),
                ):
                    reply = _validated(
                        await client.call_tool(tool, args), get_output_schema(schema)
                    )
                    assert [e["code"] for e in reply["errors"]] == ["DEVICE_NOT_READY"]
                assert rec.reads == [] and rec.runs == []
        rec = Recorder()
        rec.timeout = True
        async with Client(_server(rec)) as client:
            timed = _validated(
                await client.call_tool("adb_observe", {"device_id": DEVICE, "probes": ["selinux"]}),
                get_output_schema("adb_observe"),
            )
            assert [e["code"] for e in timed["errors"]] == ["PROBE_TIMEOUT"]
            timed_op = _validated(
                await client.call_tool(
                    "adb_develop", {"device_id": DEVICE, "action": {"type": "logcat_snapshot"}}
                ),
                get_output_schema("adb_develop"),
            )
            assert [e["code"] for e in timed_op["errors"]] == ["OPERATION_TIMEOUT"]

        rec = Recorder()
        rec.flood = True
        async with Client(_server(rec)) as client:
            flooded = _validated(
                await client.call_tool(
                    "adb_develop", {"device_id": DEVICE, "action": {"type": "logcat_snapshot"}}
                ),
                get_output_schema("adb_develop"),
            )
            assert flooded["status"] == "partial"
            assert flooded["result"]["truncated"] is True
            assert len(flooded["result"]["stdout"]) <= MAX_RESULT_CHARS
            assert [e["code"] for e in flooded["errors"]] == ["OUTPUT_LIMIT"]

    asyncio.run(check())
    # Exercise the real subprocess boundary using an entirely synthetic child.
    # The group leader must be reaped when the 64 KiB capture limit is reached.
    real_popen = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []

    def track(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        child: subprocess.Popen[bytes] = real_popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", track)
    result = bounded_run(
        [sys.executable, "-c", "import os,time;os.write(1,b'x'*100000);time.sleep(8)"],
        2.0,
        OUTPUT_BYTE_LIMIT,
    )
    assert result.truncated is True and result.returncode != 0
    assert len(result.stdout.encode()) + len(result.stderr.encode()) <= OUTPUT_BYTE_LIMIT
    assert len(children) == 1 and children[0].poll() is not None
    with pytest.raises(ProcessLookupError):
        os.killpg(children[0].pid, 0)


def test_t_h0a_06_mutated_golden_fails_and_restored_copy_passes() -> None:
    async def check() -> None:
        async with Client(_server(Recorder())) as client:
            observed = _catalog(await client.list_tools())
            assert observed == GOLDEN
            corrupted = deepcopy(GOLDEN)
            corrupted["adb_observe"]["schema_id"] = "urn:android-mcp:adb-observation:v0"
            with pytest.raises(AssertionError):
                assert observed == corrupted
            assert observed == GOLDEN

    asyncio.run(check())
