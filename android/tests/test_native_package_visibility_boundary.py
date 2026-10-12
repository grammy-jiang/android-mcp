"""N2.a Android PackageManager subset safety, no ADB or physical devices."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = "{http://schemas.android.com/apk/res/android}"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"
APP = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
READER = APP / "AndroidVisiblePackagesReader.kt"
GATEWAY = APP / "LocalMcpGateway.kt"
CODE = ROOT / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol/NativePackageVisibility.kt"


def test_no_query_all_packages_queries_or_cross_user_permissions() -> None:
    root = ET.parse(MANIFEST).getroot()
    permissions = {
        entry.get(ANDROID + "name") for entry in root.findall("uses-permission")
    }
    assert "android.permission.QUERY_ALL_PACKAGES" not in permissions
    assert "android.permission.INTERACT_ACROSS_USERS" not in permissions
    assert "android.permission.INTERACT_ACROSS_USERS_FULL" not in permissions
    assert "android.permission.MANAGE_USERS" not in permissions
    assert root.findall("queries") == []
    assert permissions == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }


def test_adapter_only_requests_current_visible_package_manager_subset() -> None:
    source = READER.read_text()
    assert "internal object AndroidVisiblePackagesReader" in source
    assert "manager.getInstalledPackages(0)" in source
    assert "manager.getPackageInfo(context.packageName, PackageManager.GET_PERMISSIONS)" in source
    assert "broadPermissionDeclared = permissions.contains(Manifest.permission.QUERY_ALL_PACKAGES)" in source
    assert "crossUserRequested = false" in source
    assert "NativePackageVisibilitySampler().use" in source
    for forbidden in (
        "MATCH_UNINSTALLED_PACKAGES",
        "MATCH_ANY_USER",
        "MATCH_ALL",
        "getPackagesForUid(",
        "getInstalledApplications(",
        "createContextAsUser(",
        "UserHandle",
        "Runtime.getRuntime",
        "ProcessBuilder",
        "QUERY_ALL_PACKAGES |",
    ):
        assert forbidden not in source


def test_visibility_model_denies_guessing_and_bounded_results() -> None:
    source = CODE.read_text()
    assert "MAX_RESULT = 64" in source
    assert "MAX_SCAN = 512" in source
    assert "NOT_VISIBLE_OR_MISSING" in source
    assert "broadPermissionDeclared || input.crossUserRequested" in source
    assert "NativePackageVisibility.unavailable()" in source
    assert "TimeoutException" in source
    assert "future.cancel(true)" in source
    assert "Executors.newSingleThreadExecutor" in source
    assert "MAX_RESULT" in source


def test_no_new_native_public_inventory_tool_or_provider() -> None:
    gateway = GATEWAY.read_text()
    assert gateway.count("server.addTool(") == 1
    assert 'name = "device_status"' in gateway
    assert "native_visible_packages" not in gateway
    assert "AndroidVisiblePackagesReader" not in gateway
    app = ET.parse(MANIFEST).getroot().find("application")
    assert app is not None
    assert app.findall("provider") == []
