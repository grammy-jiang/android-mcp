"""I1a: publish the canonical device-status v1 schema without wire drift."""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator, ValidationError

from android_mcp_host.adb import AdbClient, AdbReport, Device
from android_mcp_host.mcp_boundary import get_output_schema
from android_mcp_host.server import create_server


class FakeAdb:
    def inspect(self) -> AdbReport:
        return AdbReport(
            True,
            "/synthetic/adb",
            "37",
            None,
            (Device("MOCK-01", "device", {"model": "Fixture"}),),
        )


def test_device_status_advertises_canonical_fields_and_retains_wire_envelope():
    async def verify() -> None:
        server = create_server(adb=FakeAdb())  # type: ignore[arg-type]
        async with Client(server) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert sorted(tools) == ["adb_develop", "adb_observe", "device_status"]
            schema = tools["device_status"].output_schema
            canonical = get_output_schema("device_status")
            assert schema is not None
            assert schema["$id"] == canonical["$id"]
            assert schema["type"] == "object"
            assert schema["additionalProperties"] is False
            assert set(schema["required"]) == set(canonical["required"])
            assert set(schema["properties"]) == set(canonical["properties"])
            reply = await client.call_tool("device_status", {})
            assert reply.is_error is False
            assert isinstance(reply.structured_content, dict)
            assert reply.structured_content["schema_version"] == 1
            assert reply.structured_content["runtime"] == "host"
            assert reply.structured_content["devices"][0]["device_id"] == "MOCK-01"
            Draft202012Validator(schema).validate(reply.structured_content)
            # FastMCP .data is a client helper and not the stable wire contract.
            assert reply.structured_content["adb"]["available"] is True

    asyncio.run(verify())


def test_no_adb_device_status_still_validates_against_published_schema():
    async def verify() -> None:
        server = create_server(adb=AdbClient(locator=lambda _: None))
        async with Client(server) as client:
            schema = {t.name: t.output_schema for t in await client.list_tools()}["device_status"]
            assert schema is not None
            reply = await client.call_tool("device_status", {})
            assert not reply.is_error
            assert isinstance(reply.structured_content, dict)
            assert reply.structured_content["devices"] == []
            assert reply.structured_content["adb"]["available"] is False
            Draft202012Validator(schema).validate(reply.structured_content)

    asyncio.run(verify())


def test_invalid_device_status_envelope_is_not_accepted_by_schema():
    schema = get_output_schema("device_status")
    data = {
        "schema_version": 1,
        "runtime": "host",
        "capabilities": {},
        "devices": [],
        "errors": [],
        "unexpected_internal_secret": "SYNTHETIC_SECRET_DO_NOT_USE",
    }
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(data)
