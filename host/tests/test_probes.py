"""Proof that Android Host observations require one authorized target.

Every test uses a fake ADB discovery/executor; no platform-tools binary or
physical device is needed. Failure cases must not trigger an ADB probe.
"""

import subprocess

import pytest

from android_mcp_host.adb import AdbReport, Device, Diagnostic
from android_mcp_host.probes import (
    MAX_PROBES,
    PROBES,
    ProbeService,
    _bounded,
    _run,
)


class StaticDiscovery:
    def __init__(self, report=None):
        self.report = report if report is not None else _report()
        self.calls = 0

    def inspect(self):
        self.calls += 1
        return self.report


def _report(state="device", *, serial="SAMPLE-42", error=None):
    return AdbReport(
        available=True,
        executable="/fake/adb",
        version="37.0.1",
        error=error,
        devices=(Device(serial, state, {"model": "TEST"}),),
    )


def _cp(argv, code=0, stdout="OK\n", stderr=""):
    return subprocess.CompletedProcess(argv, code, stdout=stdout, stderr=stderr)


def _service(*, state="device", report=None, on_run=None, path="/fake/adb"):
    adb = StaticDiscovery(_report(state) if report is None else report)
    calls = []

    def reader(argv, timeout):
        calls.append((argv, timeout))
        return on_run(argv, timeout) if on_run is not None else _cp(argv)

    return ProbeService(adb, adb_executable=path, reader=reader), adb, calls


def test_good_device_runs_only_whitelisted_commands_and_preserves_order():
    service, adb, calls = _service()
    response = service.observe("SAMPLE-42", ["selinux", "boot"])
    assert response["status"] == "ok"
    assert response["errors"] == []
    assert response["results"][0]["fields"] == {"enforcement": "OK"}
    assert [item["probe"] for item in response["results"]] == ["selinux", "boot"]
    assert [cmd[0] for cmd in calls] == [
        ["/fake/adb", "-s", "SAMPLE-42", "shell", "getenforce"],
        ["/fake/adb", "-s", "SAMPLE-42", "shell", "getprop", "sys.boot_completed"],
        ["/fake/adb", "-s", "SAMPLE-42", "shell", "getprop", "ro.debuggable"],
        ["/fake/adb", "-s", "SAMPLE-42", "shell", "getprop", "ro.boot.verifiedbootstate"],
    ]
    assert all(timeout == 5.0 for _, timeout in calls)
    assert adb.calls == 1


def test_compatibility_probe_uses_only_fixed_readonly_properties():
    service, _, calls = _service(on_run=lambda argv, timeout: _cp(argv, stdout="a-b-12\n"))
    result = service.observe("SAMPLE-42", ["compatibility"])
    assert result["status"] == "ok"
    assert result["results"][0]["fields"] == {
        "primary_abi": "a-b-12",
        "security_patch": "a-b-12",
        "soc_model": "a-b-12",
        "kernel_release": "a-b-12",
    }
    assert [call[0][3:] for call in calls] == [
        ["shell", "getprop", "ro.product.cpu.abi"],
        ["shell", "getprop", "ro.build.version.security_patch"],
        ["shell", "getprop", "ro.soc.model"],
        ["shell", "uname", "-r"],
    ]


@pytest.mark.parametrize("state", ["unauthorized", "offline", "recovery", "bootloader"])
def test_not_ready_is_reported_without_running_any_shell(state):
    service, _, calls = _service(state=state)
    response = service.observe("SAMPLE-42", ["identity"])
    assert response["errors"][0]["code"] == "DEVICE_NOT_READY"
    assert response["status"] == "error"
    assert calls == []


def test_wrong_serial_is_not_implicitly_replaced_by_first_connected_device():
    service, _, calls = _service()
    response = service.observe("OTHER", ["battery"])
    assert response["status"] == "error"
    assert response["errors"][0]["code"] == "DEVICE_NOT_FOUND"
    assert not calls


@pytest.mark.parametrize("invalid", ["", "-s", "a b", "abc\nother", "c" * 200, None])
def test_bad_serial_rejected_before_discovery(invalid):
    service, adb, calls = _service()
    response = service.observe(invalid, ["battery"])
    assert response["errors"][0]["code"] == "INVALID_DEVICE_ID"
    assert adb.calls == 0
    assert calls == []


@pytest.mark.parametrize(
    "invalid",
    [
        [],
        ["no_such_probe"],
        ["battery", "battery"],
        ["battery"] * (MAX_PROBES + 1),
        "battery",
        None,
    ],
)
def test_bad_probe_names_rejected_before_discovery(invalid):
    service, adb, calls = _service()
    response = service.observe("SAMPLE-42", invalid)
    assert response["status"] == "error"
    assert response["errors"][0]["code"].startswith("INVALID_")
    assert adb.calls == 0
    assert calls == []


def test_missing_binary_blocks_shell_even_if_device_listed():
    service, _, calls = _service(path="")
    service._locate = lambda _: None
    response = service.observe("SAMPLE-42", ["battery"])
    assert response["errors"][0]["code"] == "ADB_NOT_FOUND"
    assert not calls


def test_adb_discovery_error_blocks_command_dispatch():
    report = _report(error=Diagnostic("ADB_LIST_FAILED", "broken service"))
    service, _, calls = _service(report=report)
    response = service.observe("SAMPLE-42", ["battery"])
    assert response["errors"][0]["code"] == "ADB_LIST_FAILED"
    assert not calls


def test_version_error_and_no_adb_are_nonfatal():
    report = AdbReport(False, None, None, Diagnostic("ADB_NOT_FOUND", "not here"), ())
    service, _, calls = _service(report=report)
    result = service.observe("SAMPLE-42", ["battery"])
    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "ADB_NOT_FOUND"
    assert not calls


def test_probe_returns_bounded_non_sensitive_failure_without_stderr_echo():
    def failed(argv, timeout):
        return _cp(argv, 1, "", "PRIVATE_TOKEN_1234: failure details")

    service, _, _ = _service(on_run=failed)
    response = service.observe("SAMPLE-42", ["battery"])
    assert response["errors"][0] == {"code": "PROBE_FAILED", "message": "ADB command failed"}
    assert "PRIVATE_TOKEN_1234" not in str(response)


def test_failed_second_probe_returns_first_as_partial():
    def reader(argv, timeout):
        if "battery" in argv:
            return _cp(argv, 1, "", "fail")
        return _cp(argv, 0, "Enforcing\n")

    service, _, _ = _service(on_run=reader)
    response = service.observe("SAMPLE-42", ["selinux", "battery"])
    assert response["status"] == "partial"
    assert [r["probe"] for r in response["results"]] == ["selinux"]
    assert response["errors"][0]["code"] == "PROBE_FAILED"


def test_timeout_on_second_probe_returns_partial():
    def reader(argv, timeout):
        if argv[-1] == "id":
            raise subprocess.TimeoutExpired(argv, timeout)
        return _cp(argv)

    service, _, _ = _service(on_run=reader)
    response = service.observe("SAMPLE-42", ["battery", "shell_identity"])
    assert response["status"] == "partial"
    assert response["errors"][0]["code"] == "PROBE_TIMEOUT"


def test_os_error_is_typed_not_raised():
    def explode(argv, timeout):
        raise PermissionError("privacy protected path")

    service, _, _ = _service(on_run=explode)
    response = service.observe("SAMPLE-42", ["battery"])
    assert response["status"] == "error"
    assert response["errors"][0]["code"] == "PROBE_EXEC_FAILED"
    assert "privacy protected path" not in str(response)


def test_large_output_is_truncated_with_field_level_evidence():
    def huge(argv, timeout):
        return _cp(argv, stdout="X" * 50000)

    service, _, calls = _service(on_run=huge)
    response = service.observe("SAMPLE-42", ["battery"])
    assert response["status"] == "ok"
    assert len(response["results"][0]["fields"]["battery"]) == 4096
    assert response["results"][0]["truncated_fields"] == ["battery"]
    assert len(calls) == 1


def test_output_limit_fails_closed_without_infinite_logging():
    # 6 identity fields + three boot fields consume at most 9 x 2048 chars,
    # which does not reach the 25,000-char ceiling. All probes together can.
    service, _, calls = _service(on_run=lambda argv, timeout: _cp(argv, stdout="X" * 40000))
    response = service.observe(
        "SAMPLE-42",
        [
            "identity",
            "boot",
            "battery",
            "display",
            "storage",
            "selinux",
            "shell_identity",
            "third_party_packages",
        ],
    )
    assert response["status"] == "partial"
    assert response["errors"][0]["code"] == "OUTPUT_LIMIT"
    assert len(str(response)) < 40000
    assert calls


def test_readonly_registry_contains_no_root_su_or_user_arguments():
    assert set(PROBES) == {
        "identity",
        "compatibility",
        "boot",
        "battery",
        "display",
        "storage",
        "selinux",
        "shell_identity",
        "third_party_packages",
    }
    for steps in PROBES.values():
        for step in steps:
            assert step.argv[0] == "shell"
            assert all(piece not in {"su", "root", "sh", "bash"} for piece in step.argv)
            assert not any(";" in piece or "\n" in piece for piece in step.argv)


def test_invalid_timeout_configuration_is_rejected():
    for invalid in (0, -1, 10.01):
        with pytest.raises(ValueError):
            ProbeService(timeout_s=invalid)


def test_subprocess_wrapper_passes_arguments_without_host_shell():
    import sys

    token = "a; echo INJECTED"
    response = _run([sys.executable, "-c", "import sys; print(sys.argv[1])", token], 2.0)
    assert response.returncode == 0
    assert response.stdout.strip() == token
    assert response.stderr == ""


def test_bounded_preserves_text_without_extra_reformatting():
    assert _bounded("line\r\n", 100) == ("line", False)
    assert _bounded("abcdef", 3) == ("abc", True)


def test_missing_adb_executable_report_without_diagnostic_is_still_closed():
    report = AdbReport(False, None, None, None, ())
    service, _, commands = _service(report=report)
    response = service.observe("SAMPLE-42", ["battery"])
    assert response["errors"][0]["code"] == "ADB_NOT_FOUND"
    assert commands == []


def test_control_characters_are_removed_from_device_text():
    assert _bounded("Enforcing\x00\x1b[31m\n", 99) == ("Enforcing[31m", False)


def test_probe_does_not_hold_unlimited_device_output():
    import sys

    from android_mcp_host.command_runner import OutputLimitExceeded

    with pytest.raises(OutputLimitExceeded):
        _run([sys.executable, "-c", "print('X' * 300000)"], 3)


def test_capture_limit_is_classified_without_leaking_output():
    from android_mcp_host.command_runner import OutputLimitExceeded

    def flooded(argv, timeout):
        raise OutputLimitExceeded("private device material")

    service, _, _ = _service(on_run=flooded)
    response = service.observe("SAMPLE-42", ["battery"])
    assert response["status"] == "error"
    assert response["errors"][0]["code"] == "OUTPUT_LIMIT"
    assert "private device material" not in str(response)
