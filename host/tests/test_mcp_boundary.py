"""Canonical Host MCP schemas must remain identical inside installed wheels."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from android_mcp_host.mcp_boundary import get_output_schema

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = {
    "device_status": "device-status.v1.schema.json",
    "adb_observe": "adb-observation.v1.schema.json",
    "adb_develop": "adb-development.v1.schema.json",
}


@pytest.mark.parametrize("tool_name,filename", CANONICAL.items())
def test_packaged_schema_equals_canonical_shared_contract(tool_name: str, filename: str):
    expected = json.loads((ROOT / "contracts" / filename).read_text(encoding="utf-8"))
    actual = get_output_schema(tool_name)
    assert actual == expected  # Guard against manually maintained copy drift.
    Draft202012Validator.check_schema(actual)
    assert actual["$id"] == expected["$id"]


@pytest.mark.parametrize("tool_name", CANONICAL)
def test_schema_return_is_defensive_copy(tool_name: str):
    first = get_output_schema(tool_name)
    first["title"] = "synthetic mutation that must never stick"
    assert get_output_schema(tool_name)["title"] != first["title"]


def test_unknown_tool_schema_is_refused():
    with pytest.raises(ValueError, match="Unknown Host MCP tool"):
        get_output_schema("arbitrary_shell")


def test_corrupted_packaged_schema_fails_closed(monkeypatch):
    import android_mcp_host.mcp_boundary as boundary

    monkeypatch.setattr(boundary.json, "loads", lambda _: ["not an object"])
    with pytest.raises(ValueError, match="Invalid packaged output schema"):
        get_output_schema("device_status")


def test_existing_canonical_fixture_matches_packaged_status_contract():
    status = json.loads((ROOT / "contracts/fixtures/host-no-device.json").read_text())
    Draft202012Validator(get_output_schema("device_status")).validate(status)
