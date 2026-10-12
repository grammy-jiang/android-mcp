"""Fail-closed device selection for ambiguous ADB discovery results."""

import pytest

from android_mcp_host.adb import AdbReport, Device
from android_mcp_host.device_guard import require_online


@pytest.mark.parametrize(
    "states",
    [("device", "device"), ("device", "offline"), ("offline", "device")],
)
def test_duplicate_selected_serial_is_ambiguous_even_if_online(states):
    report = AdbReport(
        available=True,
        executable="/fake/adb",
        version="37",
        error=None,
        devices=tuple(Device("SERIAL", state, {}) for state in states),
    )
    assert require_online(report, "SERIAL") == {
        "code": "AMBIGUOUS_DEVICE_ID",
        "message": "ADB discovery returned multiple entries for the selected device",
    }


def test_unrelated_duplicate_does_not_block_unique_target():
    report = AdbReport(
        True,
        "/fake/adb",
        "37",
        None,
        (
            Device("OTHER", "device", {}),
            Device("SERIAL", "device", {}),
            Device("OTHER", "offline", {}),
        ),
    )
    assert require_online(report, "SERIAL") is None
