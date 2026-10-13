"""N3.d SDK-free approval and source boundary checks, never enables Accessibility."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = "{http://schemas.android.com/apk/res/android}"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"
APP = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
ADAPTER = APP / "AndroidAccessibilityEligibilityReader.kt"
GATEWAY = APP / "LocalMcpGateway.kt"
MODEL = ROOT / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol/NativeAccessibilityPolicy.kt"


def test_T_N3D_01_accessibility_is_disabled_with_no_system_activation() -> None:
    code = ADAPTER.read_text()
    assert "AndroidAccessibilityEligibilityReader" in code
    assert "context.packageManager.getPackageInfo(" in code
    assert "PackageManager.GET_SERVICES or PackageManager.GET_META_DATA" in code
    assert "context.packageName" in code
    assert "Manifest.permission.BIND_ACCESSIBILITY_SERVICE" in code
    assert 'containsKey("android.accessibilityservice")' in code
    assert "userEnabled = false" in code
    assert "serviceConnected = false" in code
    for forbidden in (
        "Settings.Secure",
        "putString(",
        "putInt(",
        "startActivity(",
        "startService(",
        "startForegroundService(",
        "requestPermissions(",
        "dispatchGesture(",
        "performGlobalAction(",
        "getRootInActiveWindow(",
        "AccessibilityNodeInfo",
    ):
        assert forbidden not in code


def test_T_N3D_03_absent_android_service_is_not_faked_by_manifest() -> None:
    manifest = ET.parse(MANIFEST).getroot()
    app = manifest.find("application")
    assert app is not None
    services = app.findall("service")
    assert len(services) == 1
    assert services[0].get(ANDROID + "name") == ".NativeMcpForegroundService"
    assert services[0].get(ANDROID + "exported") == "false"
    assert services[0].get(ANDROID + "permission") != "android.permission.BIND_ACCESSIBILITY_SERVICE"
    assert app.findall("meta-data") == []
    assert app.findall("receiver") == []


def test_T_N3D_05_lock_screen_and_revoke_are_terminal_fake_only() -> None:
    source = MODEL.read_text()
    for required in (
        "SCREEN_LOCKED",
        "SERVICE_DISCONNECTED",
        "USER_REFUSED",
        "PROCESS_DEATH",
        "FOREGROUND_STOP",
        "simulatedActive = false",
        "revoked = true",
        "SIMULATED_ONLY",
        "REPLAY_DENIED",
        "STALE_DENIED",
        "userEnabled",
        "serviceConnected",
    ):
        assert required in source
    assert "fun liveUiActionAllowed(): Boolean = false" in source
    assert "fun liveUiInspectionAllowed(): Boolean = false" in source


def test_T_N3D_06_public_catalog_and_permission_allowlist_remain_unchanged() -> None:
    gateway = GATEWAY.read_text()
    assert gateway.count("server.addTool(") == 1
    assert 'name = "device_status"' in gateway
    assert "AndroidAccessibilityEligibilityReader" not in gateway
    assert "NativeAccessibilityPolicy" not in gateway
    manifest = ET.parse(MANIFEST).getroot()
    declared = {
        item.get(ANDROID + "name")
        for item in manifest.findall("uses-permission")
    }
    assert declared == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }
    assert "android.permission.BIND_ACCESSIBILITY_SERVICE" not in declared
