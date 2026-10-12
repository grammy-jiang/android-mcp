"""N0.d APK-source negative checks; separate actual binary allowlist gate exists.

No ADB or permission changes here. The final real Android QEMU matrix tests
live notification refusal and foreground-service behavior.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = "{http://schemas.android.com/apk/res/android}"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"
PERMISSION_MODEL = (
    ROOT / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol"
    / "NativePermissionReadiness.kt"
)
ACTIVITY = (
    ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
    / "BackgroundMcpActivity.kt"
)
FGS = (
    ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
    / "NativeMcpForegroundService.kt"
)
ADAPTER = (
    ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
    / "AndroidPermissionReadiness.kt"
)
GATEWAY = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp/LocalMcpGateway.kt"


def test_T_N0D_02_no_sensitive_manifest_permissions_added() -> None:
    root = ET.parse(MANIFEST).getroot()
    actual = {entry.get(ANDROID + "name") for entry in root.findall("uses-permission")}
    assert actual == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }
    assert not any(
        forbidden in " ".join(sorted(actual))
        for forbidden in (
            "ACCESSIBILITY",
            "MEDIA_PROJECTION",
            "QUERY_ALL_PACKAGES",
            "MANAGE_EXTERNAL_STORAGE",
            "READ_EXTERNAL_STORAGE",
            "WRITE_EXTERNAL_STORAGE",
            "BIND_DEVICE_ADMIN",
            "ROOT",
        )
    )


def test_T_N0D_04_activity_and_service_both_read_current_os_state() -> None:
    activity = ACTIVITY.read_text()
    service = FGS.read_text()
    adapter = ADAPTER.read_text()
    assert "AndroidPermissionReadiness.canStartForeground(this)" in activity
    assert "AndroidPermissionReadiness.canStartForeground(this)" in service
    assert "context.checkSelfPermission(permission)" in adapter
    assert "requestStop()" in service
    assert "Build.VERSION.SDK_INT" in adapter
    assert "PackageManager.PERMISSION_GRANTED" in adapter


def test_T_N0D_06_snapshot_is_internal_not_registered_or_remote() -> None:
    model = PERMISSION_MODEL.read_text()
    gateway = GATEWAY.read_text()
    assert "AndroidPermissionProbe" in model
    assert "fun foregroundMayStart()" in model
    assert "devices" not in model
    assert "RuntimeException" in model
    assert 'name = "device_status"' in gateway
    assert "native_permission_status" not in gateway
    assert "127.0.0.1" in gateway
    assert "0.0.0.0" not in gateway
