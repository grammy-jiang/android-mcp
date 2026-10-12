"""Wave 2 V1: accepted Host MCP metadata safety invariants, no device I/O."""

from __future__ import annotations

import asyncio

from fastmcp import Client

from android_mcp_host.server import create_server

PUBLIC_TOOLS = {"device_status", "adb_observe", "adb_develop"}


async def _published_tools():
    # Creating the server does not inspect ADB or open a network socket.
    async with Client(create_server()) as client:
        return await client.list_tools()


def test_public_metadata_is_coherent_and_stable_at_tool_selection_boundary():
    tools = asyncio.run(_published_tools())
    assert {tool.name for tool in tools} == PUBLIC_TOOLS
    assert len(tools) == len(PUBLIC_TOOLS)

    for tool in tools:
        assert isinstance(tool.description, str)
        assert 20 <= len(tool.description.strip()) <= 1_000
        assert tool.input_schema["type"] == "object"
        assert tool.input_schema["additionalProperties"] is False


def test_required_input_arguments_remain_explicit_not_model_guessed():
    tools = {tool.name: tool for tool in asyncio.run(_published_tools())}
    status = tools["device_status"].input_schema
    assert not status.get("required")
    observation = tools["adb_observe"].input_schema
    assert set(observation["required"]) == {"device_id", "probes"}
    develop = tools["adb_develop"].input_schema
    assert set(develop["required"]) == {"device_id", "action"}
    assert "dry_run" not in develop["required"]
    assert develop["properties"]["dry_run"]["default"] is False


def test_mixed_develop_action_must_never_be_advertised_as_read_only():
    tools = {tool.name: tool for tool in asyncio.run(_published_tools())}
    develop = tools["adb_develop"]
    if develop.annotations is not None:
        # This is a truthfulness guard, not a demand to add annotations now.
        declared = develop.annotations.model_dump(mode="json", by_alias=True)
        assert declared.get("readOnlyHint") is not True


def test_description_expresses_supported_intent_without_advertising_raw_shell():
    tools = {tool.name: tool for tool in asyncio.run(_published_tools())}
    status = tools["device_status"].description.casefold()
    observe = tools["adb_observe"].description.casefold()
    develop = tools["adb_develop"].description.casefold()
    assert "device" in status and "inspect" in status
    assert "read" in observe and "device" in observe
    assert "typed" in develop and "diagnostic" in develop
    assert "execute arbitrary shell" not in develop
