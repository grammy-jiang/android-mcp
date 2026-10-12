"""ADB is always mocked here; no physical tablet is needed."""

import subprocess

import pytest

from android_mcp_host.adb import AdbClient, parse_device_listing


def _result(argv: list[str], code: int, output: str, stderr: str = ""):
    return subprocess.CompletedProcess(argv, code, stdout=output, stderr=stderr)


def test_parse_empty_and_adb_daemon_messages():
    listing = (
        "* daemon not running; starting now at tcp:5037\n"
        "* daemon started successfully\n"
        "List of devices attached\n\n"
    )
    assert parse_device_listing(listing) == ()


def test_parse_multiple_devices_and_non_authorized_states():
    listing = (
        "List of devices attached\n"
        "emulator-5554 device product:sdk model:Emulator transport_id:1\n"
        "ABCD unauthorized usb:1-2 transport_id:2\n"
        "XYZ offline transport_id:3\n"
        "PERM no permissions (user in plugdev group)\n"
    )
    devices = parse_device_listing(listing)
    assert [device.state for device in devices] == [
        "device",
        "unauthorized",
        "offline",
        "no_permissions",
    ]
    assert devices[0].device_id == "emulator-5554"
    assert devices[0].properties["model"] == "Emulator"
    assert devices[1].properties["transport_id"] == "2"


def test_missing_adb_is_a_structured_nonfatal_result():
    report = AdbClient(locator=lambda _: None).inspect()
    assert not report.available
    assert report.error is not None
    assert report.error.code == "ADB_NOT_FOUND"
    assert not report.devices


def test_successful_listing_passes_argument_vectors_and_timeouts():
    commands = []

    def runner(argv, timeout):
        commands.append((argv, timeout))
        if argv[1:] == ["version"]:
            return _result(argv, 0, "Android Debug Bridge version 1.0.41\nVersion 37.0.1-1\n")
        if argv[1:] == ["devices", "-l"]:
            return _result(argv, 0, "List of devices attached\nserial-1 device model:Demo\n")
        raise AssertionError(argv)

    report = AdbClient(executable="/mock/adb", runner=runner).inspect()
    assert report.available
    assert report.error is None
    assert report.version == "37.0.1-1"
    assert report.devices[0].device_id == "serial-1"
    assert commands == [
        (["/mock/adb", "version"], 5.0),
        (["/mock/adb", "devices", "-l"], 5.0),
    ]


def test_adb_listing_failure_keeps_adb_available_with_error():
    def runner(argv, timeout):
        if argv[1:] == ["version"]:
            return _result(argv, 0, "Version 1.2.3")
        return _result(argv, 1, "", "cannot connect to daemon: unavailable\nextra logs")

    report = AdbClient(executable="adb", runner=runner).inspect()
    assert report.available
    assert report.error is not None
    assert report.error.code == "ADB_LIST_FAILED"
    assert "cannot connect to daemon" not in report.error.message
    assert report.error.message == "ADB command failed; check local Platform Tools diagnostics"


def test_timeout_and_spawn_failure():
    def timeout_runner(argv, timeout):
        raise subprocess.TimeoutExpired(argv, timeout)

    timeout_report = AdbClient(executable="adb", runner=timeout_runner).inspect()
    assert timeout_report.error is not None
    assert timeout_report.error.code == "ADB_TIMEOUT"

    def missing_runner(argv, timeout):
        raise FileNotFoundError()

    missing_report = AdbClient(executable="adb", runner=missing_runner).inspect()
    assert missing_report.error is not None
    assert missing_report.error.code == "ADB_EXEC_FAILED"


def test_timeout_cannot_be_nonpositive():
    with pytest.raises(ValueError, match="positive"):
        AdbClient(timeout_s=0)


def test_adb_listing_rejects_untrusted_device_serial_and_properties():
    listing = (
        "List of devices attached\n"
        "NORMAL device model:OnePlus\x1b[31m product:Safe transport_id:3\n"
        "BAD\x1b[31m device model:bad\n"
        "SAFE device dangerous:CTRL\x00VALUE app:com.example icon:star\n"
    )
    devices = parse_device_listing(listing)
    assert [device.device_id for device in devices] == ["NORMAL", "SAFE"]
    assert devices[0].properties == {"product": "Safe", "transport_id": "3"}
    assert devices[1].properties == {"app": "com.example", "icon": "star"}
    assert "\x1b" not in str(devices)
    assert "\x00" not in str(devices)
