"""MCP H2 tooling remains fail-closed unless an explicitly trusted coordinator is injected."""

from android_mcp_host.adb import AdbReport, Device
from android_mcp_host.command_runner import RunResult
from android_mcp_host.operations import OperationService
from android_mcp_host.security.coordinator import SecureOutcome


class FakeDiscovery:
    def inspect(self):
        return AdbReport(True, "/mock/adb", "37", None, (Device("ABC-1", "device", {}),))


class TrustedFakeCoordinator:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def perform(self, **kwargs):
        self.calls.append(kwargs)
        return self.outcome


ACTION = {"type": "instrument_test", "package": "com.sample.tests", "runner": "com.test.Runner"}


def test_mutations_are_disabled_without_a_trusted_coordinator():
    calls = []
    service = OperationService(FakeDiscovery(), runner=lambda *args: calls.append(args))
    result = service.execute("ABC-1", ACTION)
    assert result["errors"][0]["code"] == "MUTATION_DISABLED"
    assert calls == []


def test_injected_coordinator_is_only_configured_via_host_side_dependency():
    fake = TrustedFakeCoordinator(
        SecureOutcome("completed", "NONE", RunResult(0, "OK (1 test)", "", False))
    )
    service = OperationService(FakeDiscovery(), secure_coordinator=fake)
    result = service.execute("ABC-1", ACTION)
    assert result["status"] == "ok"
    assert result["errors"] == []
    assert fake.calls[0]["device_id"] == "ABC-1"
    assert fake.calls[0]["plan"].mutating
    assert fake.calls[0]["binary"] == "/mock/adb"
    assert "secure_coordinator" not in ACTION


def test_coordinator_denial_is_not_hidden_by_h2():
    fake = TrustedFakeCoordinator(SecureOutcome("blocked", "OPERATOR_APPROVAL_REQUIRED"))
    service = OperationService(FakeDiscovery(), secure_coordinator=fake)
    result = service.execute("ABC-1", ACTION)
    assert result["status"] == "error"
    assert result["result"] is None
    assert result["errors"][0]["code"] == "OPERATOR_APPROVAL_REQUIRED"


def test_partial_audit_reflected_in_host_mcp_result():
    fake = TrustedFakeCoordinator(
        SecureOutcome("partial", "AUDIT_INCOMPLETE", RunResult(0, "OK", "", False))
    )
    service = OperationService(FakeDiscovery(), secure_coordinator=fake)
    result = service.execute("ABC-1", ACTION)
    assert result["status"] == "partial"
    assert result["errors"][0]["code"] == "AUDIT_INCOMPLETE"
    assert result["result"]["exit_code"] == 0


def test_read_actions_do_not_use_high_privilege_coordinator():
    fake = TrustedFakeCoordinator(SecureOutcome("completed", "NONE"))
    service = OperationService(
        FakeDiscovery(),
        secure_coordinator=fake,
        runner=lambda *_: RunResult(0, "normal logs", "", False),
    )
    r = service.execute("ABC-1", {"type": "logcat_snapshot"})
    assert r["status"] == "ok"
    assert fake.calls == []
