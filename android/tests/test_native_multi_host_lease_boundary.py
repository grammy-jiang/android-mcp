"""N6.d synthetic dual-Host contention, no public mutating bridge."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
ANDROID = "{http://schemas.android.com/apk/res/android}"
SRC = ROOT / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol/NativeMultiHostLease.kt"
ADAPTER = APP / "AndroidMultiHostLeaseBoundary.kt"
GATEWAY = APP / "LocalMcpGateway.kt"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"


def test_n6d_01_two_host_contention_is_synchronized_not_parallel_writes() -> None:
    code = SRC.read_text()
    assert "@Synchronized" in code
    assert "DualHostLeaseState.BUSY" in code
    assert "if (request.fence <= highWater)" in code
    assert "allowedHosts" in code
    assert "active = Active(" in code


def test_n6d_02_wrong_host_ttl_replay_renewal_and_release_denied() -> None:
    code = SRC.read_text()
    for marker in (
        "current.host != request.hostId",
        "current.requestId != request.requestId",
        "current.plan != request.planDigest",
        "DualHostLeaseState.EXPIRED",
        "DualHostLeaseState.ALREADY_RELEASED",
        "DualHostLeaseState.REPLAY",
        "seenPlans",
        "seenRequests",
    ):
        assert marker in code


def test_n6d_03_crash_and_stop_unconfirmed_status_not_retried() -> None:
    code = SRC.read_text()
    assert "fun simulateProcessDeath() = stop()" in code
    assert "fun recoverySnapshot()" in code
    assert "uncertain = active?.fence" in code
    assert "DualHostLeaseState.UNCERTAIN" in code
    assert "automatic_retry" in code
    assert "mutation_executed" in code


def test_n6d_04_schema_future_unknown_fields_fail_closed() -> None:
    code = SRC.read_text()
    assert "request.schemaVersion != 2" in code
    assert "request.unknownRequired.isNotEmpty()" in code
    assert "request.nativeInstallation != nativeInstallation" in code
    assert "request.bootEpoch != bootEpoch" in code
    assert "DualHostLeaseState.PAIRING_REQUIRED" in code
    assert "DualHostLeaseState.UNSUPPORTED" in code


def test_n6d_05_production_android_bridge_always_denied() -> None:
    code = ADAPTER.read_text()
    assert "FakeLeaseReceipt(DualHostLeaseState.DENIED)" in code
    gateway = GATEWAY.read_text()
    assert gateway.count("server.addTool(") == 1
    assert 'name = "device_status"' in gateway
    assert "AndroidMultiHostLeaseBoundary" not in gateway
    assert "NativeMultiHostLease" not in gateway
    assert "fun realDeviceMutationAllowed(): Boolean = false" in SRC.read_text()
    for forbidden in ("startActivity(", "PackageInstaller(", "ProcessBuilder(", "Runtime.getRuntime("):
        assert forbidden not in code


def test_n6d_06_android_manifest_not_expanded() -> None:
    manifest = ET.parse(MANIFEST).getroot()
    permissions = {e.get(ANDROID + "name") for e in manifest.findall("uses-permission")}
    assert permissions == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }


def test_n6d_07_recovery_ledger_and_expiry_fail_closed() -> None:
    code = SRC.read_text()
    assert "recovery.seenRequestIds.size <= 64" in code
    assert "recovery.seenPlanDigests.all { DIGEST.matches(it) }" in code
    assert "seenRequests.toList(), seenPlans.toList()" in code
    assert "if (now > current.expiresAt)" in code
    assert 'override fun toString() = "FakeLeaseRecovery([REDACTED])"' in code
