"""Failure-path and parser tests for the privileged ADB-facing boundary."""

import subprocess
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

from android_mcp_host.adb import (
    ALLOWED_STATES,
    AdbClient,
    Device,
    _clean_error,
    _execute,
    _version,
    parse_device_listing,
)


def _result(argv, code, stdout="", stderr=""):
    return subprocess.CompletedProcess(argv, code, stdout=stdout, stderr=stderr)


def test_real_process_runner_uses_portable_argument_vector():
    result = _execute([sys.executable, "-c", "print('argument-vector')"], 4.0)
    assert result.returncode == 0
    assert result.stdout.strip() == "argument-vector"


def test_version_parser_without_normal_version_line():
    assert _version("Android Debug Bridge version 1.0.41\n") == "1.0.41"
    assert _version("unknown build\n") is None
    assert _version("") is None
    assert _version("header\nVersion 42\n") == "42"


def test_error_report_is_bounded_and_safe_when_no_stderr():
    assert _clean_error("") == "ADB returned a non-zero status"
    assert _clean_error("problem\ninternal stack\n") == "problem"
    assert len(_clean_error("x" * 5000)) == 240


def test_parsing_skips_unknown_and_malformed_lines_and_blank_properties():
    output = (
        "strayline\n"
        "SERIAL unexpectedstate x:y\n"
        "OK device meaningless_key: :bad empty: serial:with:colons\n"
        "CONN recovery usb:1-2\n"
        "* daemon started successfully\n"
    )
    devices = parse_device_listing(output)
    assert [d.device_id for d in devices] == ["OK", "CONN"]
    assert devices[0].properties == {"serial": "with:colons"}
    assert devices[1].properties["usb"] == "1-2"
    assert devices[0].to_dict() == {
        "device_id": "OK",
        "state": "device",
        "properties": {"serial": "with:colons"},
    }


@settings(max_examples=125, deadline=None)
@given(st.text(max_size=1000))
def test_arbitrary_adb_device_output_never_raises_or_invents_states(text):
    devices = parse_device_listing(text)
    assert len(devices) <= len(text.splitlines())
    assert all(item.state in ALLOWED_STATES for item in devices)
    assert all(item.device_id for item in devices)


def test_adb_version_failure_remains_diagnostic():
    def runner(argv, timeout):
        assert argv == ["adb", "version"]
        return _result(argv, 1, stderr="binary failure\nstacktrace")

    report = AdbClient(executable="adb", runner=runner).inspect()
    assert report.available is False
    assert report.version is None
    assert report.error is not None
    assert report.error.code == "ADB_VERSION_FAILED"
    assert report.error.message == "binary failure"
    assert report.devices == ()


def test_adb_listing_error_does_not_return_fake_devices():
    def runner(argv, timeout):
        if argv[1:] == ["version"]:
            return _result(argv, 0, stdout="garbled version")
        return _result(argv, 2, stderr="")

    report = AdbClient(executable="adb", runner=runner).inspect()
    assert report.available
    assert report.version is None
    assert report.devices == ()
    assert report.error is not None
    assert report.error.message == "ADB returned a non-zero status"


def test_explicit_executable_bypasses_locator_and_handles_real_device_state():
    def do_not_lookup(_):
        raise AssertionError("explicit executable must be used")

    def runner(argv, timeout):
        if argv[1] == "version":
            return _result(argv, 0, stdout="Version 37.0.1\n")
        return _result(argv, 0, stdout="List of devices attached\nABC offline\n")

    report = AdbClient(executable="adb", runner=runner, locator=do_not_lookup).inspect()
    assert report.available and report.error is None
    assert len(report.devices) == 1
    assert report.devices[0].state == "offline"
    assert isinstance(report.devices[0], Device)


def test_adb_discovery_rejects_large_subprocess_output(tmp_path):
    from pathlib import Path

    path = Path(tmp_path) / "adb"
    path.write_text(
        "#!" + sys.executable + "\n"
        "import sys\n"
        "if 'version' in sys.argv: print('Version 37.0.1')\n"
        "else: print('D' * 300000)\n",
        encoding="utf-8",
    )
    path.chmod(0o700)
    report = AdbClient(executable=str(path)).inspect()
    assert report.available is False
    assert report.error is not None
    assert report.error.code == "ADB_OUTPUT_LIMIT"
    assert report.devices == ()


def test_adb_version_also_rejects_unbounded_output(tmp_path):
    path = tmp_path / "adb"
    path.write_text(
        "#!" + sys.executable + "\nprint('V' * 300000)\n",
        encoding="utf-8",
    )
    path.chmod(0o700)
    report = AdbClient(executable=str(path)).inspect()
    assert report.error is not None
    assert report.error.code == "ADB_OUTPUT_LIMIT"
