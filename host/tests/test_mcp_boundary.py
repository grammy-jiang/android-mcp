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


def test_canonical_development_action_schema_is_packaged_not_duplicated():
    from android_mcp_host.mcp_boundary import get_development_action_schema

    expected = json.loads(
        (ROOT / "contracts/adb-development-action.v1.schema.json").read_text(encoding="utf-8")
    )
    advertised = get_development_action_schema()
    assert advertised == expected
    Draft202012Validator.check_schema(advertised)
    assert len(advertised["oneOf"]) == 4


def test_development_action_schema_is_returned_as_fresh_object():
    from android_mcp_host.mcp_boundary import get_development_action_schema

    first = get_development_action_schema()
    first["title"] = "SYNTHETIC_IGNORED_MUTATION"
    assert get_development_action_schema()["title"] != first["title"]


def test_advertised_development_actions_inline_pydantic_incompatible_refs():
    from android_mcp_host.mcp_boundary import (
        get_development_action_field_schema,
        get_development_action_schema,
    )

    canonical = get_development_action_schema()
    adapted = get_development_action_field_schema()
    assert adapted["$id"] == canonical["$id"]
    assert len(adapted["oneOf"]) == len(canonical["oneOf"])
    assert "$defs" not in adapted
    assert "#/$defs/package" not in json.dumps(adapted)
    Draft202012Validator.check_schema(adapted)
    choices = [
        {"type": "logcat_snapshot", "lines": 20},
        {"type": "package_details", "package": "com.example.app"},
        {"type": "instrument_test", "package": "com.example.test", "runner": "com.example.Runner"},
        {"type": "install_apk", "apk_path": "/tmp/dummy.apk"},
        {"type": "package_details", "package": "bad!"},
        {"type": "package_details", "package": "com.example.app", "unexpected": True},
        {"type": "instrument_test", "package": "com.example.app", "runner": "not-ok"},
        {"type": "logcat_snapshot", "lines": 1},
        {"type": "arbitrary_shell", "command": "id"},
        {"type": "install_apk", "apk_path": ""},
    ]
    for value in choices:
        assert Draft202012Validator(adapted).is_valid(value) == (
            Draft202012Validator(canonical).is_valid(value)
        ), value


@pytest.mark.parametrize(
    "invalid,expected_message",
    [
        ({"$defs": [], "oneOf": []}, "Invalid canonical development action schema"),
        ({"$defs": {}, "oneOf": "not a list"}, "Invalid canonical development action schema"),
        ({"$defs": {}, "oneOf": ["bad-variant"]}, "Invalid canonical development action variant"),
        (
            {"$defs": {}, "oneOf": [{"properties": []}]},
            "Invalid canonical development action properties",
        ),
        (
            {"$defs": {}, "oneOf": [{"properties": {"package": {"$ref": 42}}}]},
            "Unsupported development action schema reference",
        ),
        (
            {
                "$defs": {},
                "oneOf": [{"properties": {"package": {"$ref": "https://host.invalid/x"}}}],
            },
            "Unsupported development action schema reference",
        ),
        (
            {"$defs": {}, "oneOf": [{"properties": {"package": {"$ref": "#/$defs/missing"}}}]},
            "Invalid development action schema reference",
        ),
        (
            {
                "$defs": {"package": {"type": "string"}},
                "oneOf": [{"properties": {"package": {"$ref": "#/$defs/package", "extra": True}}}],
            },
            "Invalid development action schema reference",
        ),
        (
            {
                "$defs": {"package": {"type": "string"}},
                "oneOf": [{"properties": {"package": {"$ref": "#/$defs/package"}}}],
            },
            None,
        ),
    ],
)
def test_advertised_action_schema_rejects_bad_references_and_shapes(
    monkeypatch: pytest.MonkeyPatch, invalid: dict[str, object], expected_message: str | None
) -> None:
    from copy import deepcopy

    import android_mcp_host.mcp_boundary as boundary

    monkeypatch.setattr(boundary, "get_development_action_schema", lambda: deepcopy(invalid))
    if expected_message is not None:
        with pytest.raises(ValueError, match=expected_message):
            boundary.get_development_action_field_schema()
    else:
        result = boundary.get_development_action_field_schema()
        assert result["oneOf"][0]["properties"]["package"] == {"type": "string"}
