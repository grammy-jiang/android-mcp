"""Load canonical Host MCP output schemas from installed package resources.

The source of truth is contracts/*.schema.json. In-repository equality tests
reject drift in this wheel-packaged copy. This module intentionally has no
FastMCP dependency, business authorization or ADB process side effects.
"""

from __future__ import annotations

import json
from copy import deepcopy
from importlib.resources import files
from typing import cast

_OUTPUT_SCHEMA_FILES = {
    "device_status": "device-status.v1.schema.json",
    "adb_observe": "adb-observation.v1.schema.json",
    "adb_develop": "adb-development.v1.schema.json",
}


def _load_schema(filename: str) -> dict[str, object]:
    resource = files("android_mcp_host.wire_schemas").joinpath(filename)
    loaded: object = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("Invalid packaged output schema")
    return cast(dict[str, object], loaded)


def get_output_schema(tool_name: str) -> dict[str, object]:
    """Return a fresh v1 schema for one of the three public Host Tools."""
    try:
        filename = _OUTPUT_SCHEMA_FILES[tool_name]
    except KeyError:
        raise ValueError("Unknown Host MCP tool output schema") from None
    return _load_schema(filename)


def get_development_action_schema() -> dict[str, object]:
    """Get the canonical, advertised-only v1 action choices.

    Input variants are enforced in OperationService, preserving its typed
    business denials even when FastMCP advertises stricter JSON Schema.
    """
    return _load_schema("adb-development-action.v1.schema.json")


def get_development_action_field_schema() -> dict[str, object]:
    """Advertise canonical action choices without unresolved Pydantic refs.

    Pydantic's schema generator expects its own internal definitions mapping.
    Expanding canonical local references here preserves JSON Schema semantics,
    without changing runtime domain validation or the source file.
    """
    schema = get_development_action_schema()
    definitions = schema.get("$defs")
    variants = schema.get("oneOf")
    if not isinstance(definitions, dict) or not isinstance(variants, list):
        raise ValueError("Invalid canonical development action schema")
    for variant in variants:
        if not isinstance(variant, dict):
            raise ValueError("Invalid canonical development action variant")
        properties = variant.get("properties")
        if not isinstance(properties, dict):
            raise ValueError("Invalid canonical development action properties")
        for name, value in properties.items():
            if isinstance(value, dict) and "$ref" in value:
                ref = value["$ref"]
                if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
                    raise ValueError("Unsupported development action schema reference")
                definition = definitions.get(ref.removeprefix("#/$defs/"))
                if not isinstance(definition, dict) or set(value) != {"$ref"}:
                    raise ValueError("Invalid development action schema reference")
                properties[name] = deepcopy(definition)
    del schema["$defs"]
    return schema
