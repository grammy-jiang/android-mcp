"""Status envelope defined by contracts/device-status.v1.schema.json."""

from __future__ import annotations

import platform

from android_mcp_host.adb import AdbClient


def host_platform_name(system: str) -> str:
    return {"Darwin": "macos", "Linux": "linux"}.get(system, "unsupported")


def build_status(
    adb: AdbClient,
    *,
    system: str | None = None,
    architecture: str | None = None,
    python_version: str | None = None,
) -> dict[str, object]:
    report = adb.inspect()
    errors = [report.error.to_dict()] if report.error is not None else []
    return {
        "schema_version": 1,
        "runtime": "host",
        "host": {
            "os": host_platform_name(system or platform.system()),
            "architecture": architecture or platform.machine(),
            "python": python_version or platform.python_version(),
        },
        "capabilities": {
            "adb.discovery": report.available and report.error is None,
            "adb.connected_device": any(device.state == "device" for device in report.devices),
        },
        "adb": {
            "available": report.available,
            "executable": report.executable,
            "version": report.version,
            "error": report.error.to_dict() if report.error else None,
        },
        "devices": [device.to_dict() for device in report.devices],
        "errors": errors,
    }
