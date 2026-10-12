"""Published canonical adb_observe output, hints, and typed business denials."""

from __future__ import annotations

import asyncio
import subprocess

from fastmcp import Client
from jsonschema import Draft202012Validator

from android_mcp_host.adb import AdbReport, Device
from android_mcp_host.mcp_boundary import get_output_schema
from android_mcp_host.probes import MAX_PROBES, PROBES, ProbeService
from android_mcp_host.server import create_server

DEVICE = "SYNTHETIC-01"


class FakeAdb:
    def inspect(self) -> AdbReport:
        return AdbReport(True, "/synthetic/adb", "37", None, (Device(DEVICE, "device", {}),))


class FakeReader:
    def __init__(self, timeout_after: int | None = None) -> None:
        self.timeout_after = timeout_after
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        if self.timeout_after is not None and len(self.calls) > self.timeout_after:
            raise subprocess.TimeoutExpired(argv, timeout_s)
        return subprocess.CompletedProcess(argv, 0, "Enforcing\n", "")


def test_published_observe_input_limits_and_output_schema() -> None:
    async def check() -> None:
        adb = FakeAdb()
        reader = FakeReader()
        server = create_server(adb=adb, probes=ProbeService(adb, reader=reader))  # type: ignore[arg-type]
        async with Client(server) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert sorted(tools) == ["adb_develop", "adb_observe", "device_status"]
            tool = tools["adb_observe"]
            item = tool.input_schema["properties"]["probes"]
            assert item["type"] == "array"
            assert item["minItems"] == 1
            assert item["maxItems"] == MAX_PROBES
            assert item["uniqueItems"] is True
            assert set(item["items"]["enum"]) == set(PROBES)
            schema = tool.output_schema
            canonical = get_output_schema("adb_observe")
            assert schema is not None
            assert schema["$id"] == canonical["$id"]
            assert schema["additionalProperties"] is False
            assert set(schema["required"]) == set(canonical["required"])
            reply = await client.call_tool(
                "adb_observe", {"device_id": DEVICE, "probes": ["selinux"]}
            )
            assert not reply.is_error
            assert isinstance(reply.structured_content, dict)
            Draft202012Validator(schema).validate(reply.structured_content)
            assert reply.structured_content["results"][0]["fields"]["enforcement"] == "Enforcing"
            assert reader.calls == [["/synthetic/adb", "-s", DEVICE, "shell", "getenforce"]]

    asyncio.run(check())


def test_bad_probes_and_serial_preserve_domain_denials() -> None:
    async def check() -> None:
        adb = FakeAdb()
        reader = FakeReader()
        server = create_server(adb=adb, probes=ProbeService(adb, reader=reader))  # type: ignore[arg-type]
        async with Client(server) as client:
            schema = {t.name: t.output_schema for t in await client.list_tools()}["adb_observe"]
            assert schema is not None
            cases = [
                ({"device_id": DEVICE, "probes": ["unknown"]}, "INVALID_PROBE"),
                ({"device_id": DEVICE, "probes": ["selinux", "selinux"]}, "INVALID_PROBES"),
                ({"device_id": "-s", "probes": ["selinux"]}, "INVALID_DEVICE_ID"),
                ({"device_id": DEVICE, "probes": []}, "INVALID_PROBES"),
            ]
            for args, code in cases:
                result = await client.call_tool("adb_observe", args)
                assert not result.is_error
                body = result.structured_content
                assert isinstance(body, dict)
                Draft202012Validator(schema).validate(body)
                assert body["status"] == "error"
                assert body["errors"][0]["code"] == code
            assert reader.calls == []

    asyncio.run(check())


def test_partial_timeout_preserves_structured_schema() -> None:
    async def check() -> None:
        adb = FakeAdb()
        reader = FakeReader(timeout_after=1)
        server = create_server(adb=adb, probes=ProbeService(adb, reader=reader))  # type: ignore[arg-type]
        async with Client(server) as client:
            schema = {t.name: t.output_schema for t in await client.list_tools()}["adb_observe"]
            assert schema is not None
            result = await client.call_tool(
                "adb_observe", {"device_id": DEVICE, "probes": ["selinux", "shell_identity"]}
            )
            assert not result.is_error
            body = result.structured_content
            assert isinstance(body, dict)
            Draft202012Validator(schema).validate(body)
            assert body["status"] == "partial"
            assert [entry["probe"] for entry in body["results"]] == ["selinux"]
            assert body["errors"][0]["code"] == "PROBE_TIMEOUT"

    asyncio.run(check())
