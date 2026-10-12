"""Load canonical Host MCP output schemas from installed package resources.

The source of truth is contracts/*.schema.json. In-repository equality tests
reject drift in this wheel-packaged copy. This module intentionally has no
FastMCP dependency, business authorization or ADB process side effects.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import cast

_OUTPUT_SCHEMA_FILES = {
    "device_status": "device-status.v1.schema.json",
    "adb_observe": "adb-observation.v1.schema.json",
    "adb_develop": "adb-development.v1.schema.json",
}


def get_output_schema(tool_name: str) -> dict[str, object]:
    """Return a fresh v1 schema for one of the three public Host Tools."""
    try:
        filename = _OUTPUT_SCHEMA_FILES[tool_name]
    except KeyError:
        raise ValueError("Unknown Host MCP tool output schema") from None
    resource = files("android_mcp_host.wire_schemas").joinpath(filename)
    loaded: object = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("Invalid packaged output schema")
    return cast(dict[str, object], loaded)
