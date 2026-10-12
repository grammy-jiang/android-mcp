"""Operation authorization and device-state/failure-path tests."""

import subprocess
import threading

import pytest

from android_mcp_host.adb import AdbReport, Device, Diagnostic
from android_mcp_host.command_runner import RunResult
from android_mcp_host.operations import OperationService, _diagnose, _safe_text


class Discovery:
    def __init__(self, state="device", serial="DEV123", error=None):
        self.report = AdbReport(True, "/opt/adb", "37.0", error, (Device(serial, state, {}),))
        self.calls = 0

    def inspect(self):
        self.calls += 1
        return self.report


def _service(**kwargs):
    discovery = kwargs.pop("adb", Discovery())
    calls = []

    def runner(argv, timeout, limit):
        calls.append((argv, timeout, limit))
        return RunResult(0, "package:com.example\n", "", False)

    service = OperationService(discovery, runner=kwargs.pop("runner", runner), **kwargs)
    return service, discovery, calls


def _apk(tmp_path):
    artifact = tmp_path / "fixture.apk"
    artifact.write_bytes(b"PK\x03\x04dummy bytes")
    return artifact


def test_read_only_diagnostics_use_explicit_online_device_and_bounded_executor():
    service, discovery, calls = _service()
    result = service.execute("DEV123", {"type": "package_details", "package": "com.example"})
    assert result["status"] == "ok"
    assert result["errors"] == []
    assert result["command"] == [
        "adb",
        "-s",
        "DEV123",
        "shell",
        "dumpsys",
        "package",
        "com.example",
    ]
    assert calls == [
        (["/opt/adb", "-s", "DEV123", "shell", "dumpsys", "package", "com.example"], 15.0, 65536)
    ]
    assert discovery.calls == 1


def test_logcat_read_is_bounded_and_control_chars_are_removed():
    calls = []

    def run(argv, timeout, cap):
        calls.append(argv)
        return RunResult(0, "hello\x1b[31m\x7fworld\n", "sensitive error", False)

    service, _, _ = _service(runner=run)
    result = service.execute("DEV123", {"type": "logcat_snapshot", "lines": 37})
    assert result["status"] == "ok"
    assert "\x1b" not in result["result"]["stdout"]
    assert "sensitive" not in str(result)
    assert calls[0][-5:] == ["-d", "-t", "37", "-v", "threadtime"]


def test_invalid_requests_fail_before_looking_at_adb():
    svc, discovery, calls = _service()
    for dev, action, expected in [
        ("bad serial", {"type": "package_details", "package": "com.example"}, "INVALID_DEVICE_ID"),
        ("DEV123", {"type": "shell", "cmd": "reboot"}, "UNKNOWN_OPERATION"),
        ("DEV123", {"type": "package_details", "package": "a;id"}, "INVALID_PACKAGE"),
    ]:
        result = svc.execute(dev, action)
        assert result["errors"][0]["code"] == expected
    assert discovery.calls == 0
    assert calls == []


def test_dry_run_does_not_spawn_subprocess():
    svc, _, calls = _service()
    result = svc.execute("DEV123", {"type": "logcat_snapshot"}, dry_run=True)
    assert result["status"] == "planned"
    assert result["result"] is None
    assert not calls


def test_mutation_disabled_by_default_even_when_dry_run_false(tmp_path):
    artifact = _apk(tmp_path)
    svc, _, calls = _service(allowed_apk_roots=(tmp_path,))
    action = {"type": "install_apk", "apk_path": str(artifact)}
    plan = svc.execute("DEV123", action, dry_run=True)
    assert plan["status"] == "planned"
    assert plan["mutating"] is True
    result = svc.execute("DEV123", action)
    assert result["errors"][0]["code"] == "MUTATION_DISABLED"
    assert not calls


def test_boolean_approval_callback_cannot_be_used_instead_of_signed_grants(tmp_path):
    path = _apk(tmp_path)
    with pytest.raises(TypeError):
        OperationService(Discovery(), mutation_gate=lambda *_: True)
    with pytest.raises(TypeError):
        OperationService(Discovery(), lease_gate=lambda *_: True)
    with pytest.raises(TypeError):
        OperationService(Discovery(), audit_sink=lambda _: None)
    calls = []
    svc, _, _ = _service(allowed_apk_roots=(tmp_path,), runner=lambda *_: calls.append("executed"))
    result = svc.execute("DEV123", {"type": "install_apk", "apk_path": str(path)})
    assert result["errors"][0]["code"] == "MUTATION_DISABLED"
    assert calls == []


@pytest.mark.parametrize("state", ["unauthorized", "offline", "recovery", "bootloader"])
def test_does_not_run_if_device_is_not_ready(state):
    svc, _, calls = _service(adb=Discovery(state=state))
    r = svc.execute("DEV123", {"type": "package_details", "package": "com.example"})
    assert r["errors"][0]["code"] == "DEVICE_NOT_READY"
    assert not calls


def test_unregistered_device_and_adb_discovery_error():
    svc, _, calls = _service()
    r = svc.execute("OTHER", {"type": "logcat_snapshot"})
    assert r["errors"][0]["code"] == "DEVICE_NOT_FOUND"
    assert not calls
    svc, _, _ = _service(adb=Discovery(error=Diagnostic("ADB_LIST_FAILED", "a secret")))
    result = svc.execute("DEV123", {"type": "logcat_snapshot"})
    assert result["errors"][0]["code"] == "ADB_LIST_FAILED"


def test_no_binary_after_discovery_refuses():
    d = Discovery()
    d.report = AdbReport(True, None, "x", None, (Device("DEV123", "device", {}),))
    svc, _, _ = _service(adb=d, locate=lambda _: None)
    result = svc.execute("DEV123", {"type": "logcat_snapshot"})
    assert result["errors"][0]["code"] == "ADB_NOT_FOUND"


def test_run_errors_are_typed_and_never_echo_private_exception():
    for exception, code in [
        (subprocess.TimeoutExpired("adb", 3), "OPERATION_TIMEOUT"),
        (PermissionError("private"), "OPERATION_EXEC_FAILED"),
        (ValueError("private"), "OPERATION_EXEC_FAILED"),
    ]:

        def explode(argv, timeout, cap, problem=exception):
            raise problem

        svc, _, _ = _service(runner=explode)
        result = svc.execute("DEV123", {"type": "logcat_snapshot"})
        assert result["errors"][0]["code"] == code
        assert "private" not in str(result)


def test_bounded_output_and_device_failures_are_not_reported_as_success():
    for result, code, state in [
        (RunResult(0, "X" * 90000, "", True), "OUTPUT_LIMIT", "partial"),
        (RunResult(3, "", "password=abc", False), "ADB_OPERATION_FAILED", "error"),
    ]:
        svc, _, _ = _service(runner=lambda *_, value=result: value)
        response = svc.execute("DEV123", {"type": "package_details", "package": "com.example"})
        assert response["status"] == state
        assert response["errors"][0]["code"] == code
        if response["result"]:
            assert len(response["result"]["stdout"]) <= 25000
        assert "password=abc" not in str(response)


def test_instrumentation_and_install_result_must_be_confirmed():
    for kind, text, error in [
        ("instrument_test", "no marker", "TEST_RESULT_UNCONFIRMED"),
        ("instrument_test", "INSTRUMENTATION_FAILED: test", "TEST_FAILED"),
        ("instrument_test", "OK (1 test)\nINSTRUMENTATION_CODE: -1", None),
        ("instrument_test", "INSTRUMENTATION_CODE: -1", "TEST_RESULT_UNCONFIRMED"),
        ("install_apk", "unclear", "APK_RESULT_UNCONFIRMED"),
        ("install_apk", "Failure [INSTALL_FAILED_OLDER_SDK]", "APK_INSTALL_FAILED"),
    ]:
        status, issue = _diagnose(kind, RunResult(0, text, "", False))
        assert (issue["code"] if issue else None) == error
        expected = "ok" if error is None else "error" if error.endswith("FAILED") else "partial"
        assert status == expected


def test_device_lock_rejects_concurrent_operation():
    entered = threading.Event()
    release = threading.Event()

    def blocked(argv, timeout, cap):
        entered.set()
        assert release.wait(3)
        return RunResult(0, "OK", "", False)

    svc, _, _ = _service(runner=blocked)
    first = []
    thread = threading.Thread(
        target=lambda: first.append(svc.execute("DEV123", {"type": "logcat_snapshot"}))
    )
    thread.start()
    assert entered.wait(2)
    try:
        r = svc.execute("DEV123", {"type": "logcat_snapshot"})
        assert r["errors"][0]["code"] == "DEVICE_BUSY"
    finally:
        release.set()
        thread.join(4)
    assert first[0]["status"] == "ok"


def test_safe_text_filters_controls_and_bounds():
    assert _safe_text("A\x1b\x7fB") == "AB"
    assert len(_safe_text("c" * 50000)) == 25000


def test_invalid_dry_run_and_action_type_keep_schema_consistent():
    service, discovery, _ = _service()
    bad = service.execute("DEV123", {"type": 42}, dry_run="no")
    assert bad["errors"][0]["code"] == "INVALID_DRY_RUN"
    assert bad["operation"] == ""
    assert bad["dry_run"] is False
    assert discovery.calls == 0


def test_instrumentation_code_zero_is_not_success():
    state, issue = _diagnose("instrument_test", RunResult(0, "INSTRUMENTATION_CODE: 0", "", False))
    assert state == "error"
    assert issue["code"] == "TEST_FAILED"
