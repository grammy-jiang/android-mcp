"""N2.b strict target-only PackageManager and no public Tool/permission changes."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = "{http://schemas.android.com/apk/res/android}"
APP = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
READER = APP / "AndroidTargetPackageReader.kt"
VISIBLE = APP / "AndroidVisiblePackagesReader.kt"
GATEWAY = APP / "LocalMcpGateway.kt"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"
CODE = ROOT / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol/NativePackageDetails.kt"


def test_one_visible_exact_target_before_per_package_query() -> None:
    source = READER.read_text()
    assert "NativePackageDetails.validPackageName(packageName)" in source
    assert "AndroidVisiblePackagesReader.read(context)" in source
    assert "currentlyVisible.lookup(packageName)" in source
    assert source.index("currentlyVisible.lookup(packageName)") < source.index(
        "context.packageManager.getPackageInfo("
    )
    assert "PackageManager.GET_SIGNING_CERTIFICATES or PackageManager.GET_ACTIVITIES" in source
    assert "userScope = \"current\"" in source
    for forbidden in (
        "QUERY_ALL_PACKAGES", "MATCH_ANY_USER", "MATCH_ALL", "MATCH_UNINSTALLED_PACKAGES",
        "getInstalledPackages(", "getInstalledApplications(", "getPackagesForUid(",
        "createContextAsUser(", "getRunningAppProcesses(",
    ):
        assert forbidden not in source


def test_private_cert_digest_not_raw_signature_or_other_app_permissions() -> None:
    source = READER.read_text()
    assert 'MessageDigest.getInstance("SHA-256")' in source
    assert "certificateSha256 = digest" in source
    for forbidden in (
        "getPermissions(",
        "getRequestedPermissions(",
        "getInstallSourceInfo(",
        "Log.",
        "println(",
        "android.util.Log",
    ):
        assert forbidden not in source
    model = CODE.read_text()
    assert "NOT_VISIBLE_OR_MISSING" in model
    assert "WRONG_USER" in model
    assert "UNINSTALLED" in model
    assert "VERSION_NAME" in model
    assert "SHA256" in model


def test_public_mcp_and_manifest_unchanged() -> None:
    source = GATEWAY.read_text()
    assert source.count("server.addTool(") == 1
    assert 'name = "device_status"' in source
    assert "AndroidTargetPackageReader" not in source
    manifest = ET.parse(MANIFEST).getroot()
    declared = {item.get(ANDROID + "name") for item in manifest.findall("uses-permission")}
    assert declared == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }
    assert manifest.findall("queries") == []
    assert "getInstalledPackages(0)" in VISIBLE.read_text()
