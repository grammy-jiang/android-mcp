"""Bounded, no-target ADB device discovery with ambiguity fail-closed.

This adapter never selects a device or executes pairing, connect, reconnect,
port-forward or physical device-changing commands. AdbClient inspects using
only its fixed 'version' and 'devices -l' commands and bounded runner.
"""

from __future__ import annotations

import json
import re
from importlib.resources import files
from typing import Any

from android_mcp_host.adb import ALLOWED_STATES, AdbClient, valid_device_serial

MAX_DEVICES = 64
_TRANSPORT = re.compile(r"[1-9][0-9]{0,9}\Z", re.ASCII)
_ERRORS = frozenset(
    {
        "ADB_NOT_FOUND",
        "ADB_VERSION_FAILED",
        "ADB_LIST_FAILED",
        "ADB_OUTPUT_LIMIT",
        "ADB_TIMEOUT",
        "ADB_EXEC_FAILED",
    }
)


def get_device_list_output_schema() -> dict[str, Any]:
    """Return packaged, fixed v1 Host discovery output Schema."""
    data: Any = json.loads(
        files("android_mcp_host.wire_schemas")
        .joinpath("host-adb-device-list.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(data, dict):
        raise ValueError("Invalid packaged device discovery schema")
    return data


def _error(code: str) -> dict[str, str]:
    return {"code": code, "message": "ADB device discovery could not fully confirm its targets"}


class DeviceDiscovery:
    """Synchronous read-only device list with injected AdbClient for fakes."""

    def __init__(self, adb: AdbClient | None = None) -> None:
        self._adb = adb if adb is not None else AdbClient()

    def list_devices(self) -> dict[str, Any]:
        report = self._adb.inspect()
        response: dict[str, Any] = {
            "schema_version": 1,
            "runtime": "host",
            "status": "ok",
            "devices": [],
            "errors": [],
        }
        if report.error is not None:
            code = report.error.code
            response["status"] = "partial" if report.available else "unavailable"
            response["errors"].append(_error(code if code in _ERRORS else "ADB_DISCOVERY_FAILED"))
            return response
        if not report.available:
            response["status"] = "unavailable"
            response["errors"].append(_error("ADB_NOT_FOUND"))
            return response
        if len(report.devices) > MAX_DEVICES:
            response["status"] = "error"
            response["errors"].append(_error("DEVICE_LIMIT"))
            return response
        seen_ids: set[str] = set()
        seen_transports: set[str] = set()
        rows: list[dict[str, Any]] = []
        for device in report.devices:
            serial = device.device_id
            if not valid_device_serial(serial) or device.state not in ALLOWED_STATES:
                response["status"] = "partial"
                response["errors"].append(_error("MALFORMED_DEVICE_ROW"))
                continue
            if serial in seen_ids:
                response["status"] = "error"
                response["errors"] = [_error("AMBIGUOUS_DEVICE_ID")]
                return response
            seen_ids.add(serial)
            transport = device.properties.get("transport_id")
            if not isinstance(transport, str) or _TRANSPORT.fullmatch(transport) is None:
                transport = None
                if device.state == "device":
                    response["status"] = "partial"
                    response["errors"].append(_error("MISSING_TRANSPORT_ID"))
            else:
                if transport in seen_transports:
                    response["status"] = "error"
                    response["errors"] = [_error("AMBIGUOUS_TRANSPORT_ID")]
                    return response
                seen_transports.add(transport)
            rows.append(
                {
                    "device_id": serial,
                    "state": device.state,
                    "transport_id": transport,
                    "ready_for_read": device.state == "device" and transport is not None,
                }
            )
        response["devices"] = rows
        return response
