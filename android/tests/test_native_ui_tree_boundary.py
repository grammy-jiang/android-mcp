"""N3.e synthetic UI hierarchy and production denial invariants.

All tests are SDK-free; no physical or emulated Android AccessibilityService
is enabled or inspected here.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = "{http://schemas.android.com/apk/res/android}"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"
APP = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
ADAPTER = APP / "AndroidUiTreeReadiness.kt"
ACCESSIBILITY = APP / "AndroidAccessibilityEligibilityReader.kt"
GATEWAY = APP / "LocalMcpGateway.kt"
MODEL = (
    ROOT
    / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol/NativeSyntheticUiTree.kt"
)


def test_T_N3E_01_synthetic_tree_bounds_roles_and_ephemeral_handles() -> None:
    source = MODEL.read_text()
    for expected in (
        "MAX_NODES = 64",
        "MAX_DEPTH = 8",
        "IdentityHashMap",
        'MessageDigest.getInstance("SHA-256")',
        "UUID.randomUUID()",
        "UiNodeRole.REDACTED",
        "SafeUiNode(",
        "synthetic_only",
        "read_only",
        "truncated",
        "parent_handle",
    ):
        assert expected in source


def test_T_N3E_02_raw_password_node_text_and_cross_package_are_never_in_output() -> (
    None
):
    source = MODEL.read_text()
    assert "val text: String?" in source
    assert "val contentDescription: String?" in source
    assert "val isPassword: Boolean" in source
    assert "val packageName: String" in source
    assert "node.packageName != context.expectedPackage" in source
    assert "node.isPassword || node.role == UiNodeRole.INPUT" in source
    assert "node.visible" in source
    assert "context.secureWindow" in source
    assert "context.screenUnlocked" in source
    result_class = source.split("data class SafeUiNode(", 1)[1].split(")", 1)[0]
    assert "text" not in result_class
    assert "contentDescription" not in result_class
    assert "sourceId" not in result_class


def test_T_N3E_03_revoke_and_absent_service_clear_results_not_return_old_tree() -> None:
    source = MODEL.read_text()
    assert "if (revoked)" in source
    assert "context.processEpoch != processEpoch ||" in source
    assert "context.nodeEpoch != nodeEpoch" in source
    assert "!context.serviceDeclared" in source
    assert "!context.serviceEnabled" in source
    assert "!context.serviceConnected" in source
    assert "!context.callerAuthenticated" in source
    assert "!context.fakeUserConsent" in source
    assert "revoked = true" in source
    assert "UiTreeStatus.STALE" in source
    assert "UiTreeStatus.REVOKED" in source


def test_T_N3E_05_android_reader_unconditionally_returns_empty_not_real_hierarchy() -> (
    None
):
    source = ADAPTER.read_text()
    assert "internal object AndroidUiTreeReadiness" in source
    assert "AndroidAccessibilityEligibilityReader.plan(" in source
    assert "SyntheticTreeResult(" in source
    assert "UiTreeStatus.SERVICE_UNAVAILABLE" in source
    assert "UiTreeStatus.DENIED" in source
    assert "nodes = emptyList()" in source
    assert "AccessibilityService" in ACCESSIBILITY.read_text()  # read-only declaration
    for forbidden in (
        "import android.view.accessibility.AccessibilityNodeInfo",
        "getRootInActiveWindow(",
        "getWindows(",
        "dispatchGesture(",
        "performGlobalAction(",
        "startActivity(",
        "requestPermissions(",
        "Settings.Secure",
        "putString(",
    ):
        assert forbidden not in source


def test_T_N3E_06_public_tool_catalog_and_manifest_unchanged() -> None:
    gateway = GATEWAY.read_text()
    assert gateway.count("server.addTool(") == 1
    assert 'name = "device_status"' in gateway
    assert "AndroidUiTreeReadiness" not in gateway
    assert "NativeSyntheticUiTree" not in gateway
    assert "ui_tree" not in gateway.lower()
    manifest = ET.parse(MANIFEST).getroot()
    declared = {
        item.get(ANDROID + "name") for item in manifest.findall("uses-permission")
    }
    assert declared == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }
    app = manifest.find("application")
    assert app is not None
    services = app.findall("service")
    assert len(services) == 1
    assert services[0].get(ANDROID + "name") == ".NativeMcpForegroundService"
    assert services[0].get(ANDROID + "exported") == "false"
