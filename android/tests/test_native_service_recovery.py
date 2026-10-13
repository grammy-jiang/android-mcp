"""N7.d Android Status MCP Stop/Start recovery must never auto-resume privileges."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = "{http://schemas.android.com/apk/res/android}"
SERVICE = (
    ROOT
    / "android/app/src/main/java/org/androidmcp/nativeapp/NativeMcpForegroundService.kt"
)
ACTIVITY = (
    ROOT / "android/app/src/main/java/org/androidmcp/nativeapp/NativeMcpActivity.kt"
)
FGS_POLICY = (
    ROOT
    / "android/app/src/main/java/org/androidmcp/nativeapp/AndroidPermissionReadiness.kt"
)
PROTOCOL_PERMISSION = (
    ROOT
    / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol/NativePermissionReadiness.kt"
)
LIFECYCLE = (
    ROOT
    / "android/native-lifecycle/src/main/kotlin/org/androidmcp/lifecycle/NativeServiceLifecycle.kt"
)
PORT = (
    ROOT
    / "android/native-lifecycle/src/main/kotlin/org/androidmcp/lifecycle/LocalPortOwner.kt"
)
GATE = (
    ROOT
    / "android/native-lifecycle/src/main/kotlin/org/androidmcp/lifecycle/NativeServiceRecoveryGate.kt"
)
BOUNDARY = (
    ROOT
    / "android/app/src/main/java/org/androidmcp/nativeapp/AndroidServiceRecoveryBoundary.kt"
)
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"
GATEWAY = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp/LocalMcpGateway.kt"


def test_n7d_01_explicit_start_after_verified_stop_only() -> None:
    service = SERVICE.read_text()
    lifecycle = LIFECYCLE.read_text()
    port = PORT.read_text()
    assert "ACTION_START ->" in service
    assert "ACTION_STOP -> requestStop()" in service
    assert "if (AndroidPermissionReadiness.canStartForeground(this))" in service
    assert "if (phase != PortPhase.FREE) return false" in port
    assert "portVerifiedReleased: Boolean" in port
    assert "phase = PortPhase.UNKNOWN" in port
    assert (
        "ServicePhase.STOPPING, ServicePhase.FAILED_CLOSED -> LifecycleDecision.Blocked"
        in lifecycle
    )
    assert "stopSelfResult(latestStartId)" in service


def test_n7d_02_process_reboot_sticky_and_boot_resurrection_denied() -> None:
    service = SERVICE.read_text()
    assert service.count("return START_NOT_STICKY") >= 2
    assert "else -> requestStop()" in service
    assert "override fun onDestroy()" in service
    assert "worker.shutdown()" in service
    manifest = ET.parse(MANIFEST).getroot()
    assert manifest.findall(".//receiver") == []
    assert "android.intent.action.BOOT_COMPLETED" not in MANIFEST.read_text()
    assert "fun implicitRestart(): NativeRecoveryReceipt" in GATE.read_text()


def test_n7d_03_stale_owner_port_and_notification_stop_failure_are_not_success() -> (
    None
):
    source = GATE.read_text()
    for required in (
        "phase != NativeRecoveryState.STOPPED",
        "!request.oldListenerClosed",
        "!request.oldNotificationRemoved",
        "!portReleased || !notificationRemoved",
        "phase = NativeRecoveryState.UNKNOWN",
        "ownerId != owner",
        "NativeRecoveryState.BLOCKED",
    ):
        assert required in source
    assert (
        'updateNotification("Shutdown not confirmed; tap Stop again")'
        in SERVICE.read_text()
    )


def test_n7d_04_api30_33_34_36_notification_and_foreground_enforced() -> None:
    source = GATE.read_text()
    assert "request.api !in setOf(34, 36)" in source
    assert "request.notificationGranted" in source
    assert "request.callerForeground" in source
    assert "request.explicitUserStart" in source
    service = SERVICE.read_text()
    assert "NativeForegroundSupport.supported(Build.VERSION.SDK_INT)" in service
    assert "AndroidPermissionReadiness.canStartForeground(this)" in service
    assert "NativePermissionReadiness(" in FGS_POLICY.read_text()
    assert "POST_NOTIFICATIONS" in PROTOCOL_PERMISSION.read_text()


def test_n7d_05_restart_revokes_all_sensitive_epoch_bindings() -> None:
    source = GATE.read_text()
    for marker in (
        "sensitiveEpoch = null",
        "phase == NativeRecoveryState.RUNNING && sensitiveEpoch == snapshot",
        "fun realSensitiveResumeAllowed(): Boolean = false",
        "pendingProof = null",
        "UUID.randomUUID().toString()",
    ):
        assert marker in source
    boundary = BOUNDARY.read_text()
    for marker in (
        "fun resumeCaptureAfterRestart(): Boolean = false",
        "fun resumeCallerChallengeAfterRestart(): Boolean = false",
        "fun resumeNativeLeaseAfterRestart(): Boolean = false",
    ):
        assert marker in boundary


def test_n7d_06_no_hidden_boot_power_battery_background_bypass_or_public_mutation() -> (
    None
):
    manifest = ET.parse(MANIFEST).getroot()
    permissions = {
        node.get(ANDROID + "name") for node in manifest.findall("uses-permission")
    }
    assert permissions == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }
    assert manifest.findall(".//receiver") == []
    services = manifest.findall(".//service")
    assert len(services) == 1
    assert services[0].get(ANDROID + "exported") == "false"
    gateway = GATEWAY.read_text()
    assert gateway.count("server.addTool(") == 1
    assert 'name = "device_status"' in gateway
    assert "AndroidServiceRecoveryBoundary" not in gateway
    assert "fun allowImplicitServiceStart(): Boolean = false" in BOUNDARY.read_text()


def test_no_hidden_run_on_boot_or_long_term_native_recovery_worker() -> None:
    text = SERVICE.read_text()
    for marker in (
        "WakeLock",
        "WAKE_LOCK",
        "PowerManager",
        "BOOT_COMPLETED",
        "JobScheduler",
        "AlarmManager",
    ):
        assert marker not in text
    assert (
        'text = "Stopped. Read-only; no Root, UI control or remote listener."'
        in ACTIVITY.read_text()
    )
