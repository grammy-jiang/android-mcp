"""Shared explicit-device validation for both Host ADB tool surfaces."""

from __future__ import annotations

import re

from android_mcp_host.adb import AdbReport

SERIAL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}\Z", re.ASCII)


def valid_device_id(device_id: object) -> bool:
    """Restrict serial syntax; actual membership is checked separately."""
    return isinstance(device_id, str) and SERIAL_RE.fullmatch(device_id) is not None


def require_online(report: AdbReport, device_id: str) -> dict[str, str] | None:
    """Fail closed if ADB discovery is unavailable or device is not online."""
    if report.error is not None:
        return {"code": report.error.code, "message": "ADB discovery is not ready"}
    if not report.available:
        return {"code": "ADB_NOT_FOUND", "message": "Android Platform Tools are not available"}
    matches = [item for item in report.devices if item.device_id == device_id]
    if not matches:
        return {"code": "DEVICE_NOT_FOUND", "message": "The selected device is not attached"}
    if len(matches) != 1:
        return {
            "code": "AMBIGUOUS_DEVICE_ID",
            "message": "ADB discovery returned multiple entries for the selected device",
        }
    if matches[0].state != "device":
        return {
            "code": "DEVICE_NOT_READY",
            "message": "The selected device is not authorized and online",
        }
    return None
