"""N7.a user-mediated PackageInstaller model has no real Android installation."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol/NativePackageInstallerPlan.kt"
APP = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
BOUNDARY = APP / "AndroidPackageInstallerPlanBoundary.kt"
GATEWAY = APP / "LocalMcpGateway.kt"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"
ANDROID = "{http://schemas.android.com/apk/res/android}"


def test_n7a_01_trusted_artifact_versioned_digest_and_allowlist_plan_only() -> None:
    code = SRC.read_text()
    for marker in (
        "item.packageName !in env.allowedPackages",
        "item.apkSha256 !in env.pinnedApkDigests",
        "item.signingCertSha256 !in env.trustedSigningCerts",
        "item.abi != env.nativeAbi",
        '"n7a-v1"',
        "NativeInstallPlanStatus.PLAN_ONLY",
        "requiresUserConfirmation = true",
    ):
        assert marker in code


def test_n7a_02_untrusted_apk_target_cert_and_file_uri_denied() -> None:
    code = SRC.read_text()
    for marker in (
        "item.sourceUri != null", "!item.signed",
        "!item.privateArtifactPresent", "item.minSdk !in 30..env.apiLevel",
        "item.targetSdk !in 30..env.apiLevel", "!HANDLE.matches(item.handle)",
        "NativeInstallPlanStatus.NOT_TRUSTED",
    ):
        assert marker in code


def test_n7a_03_model_approved_silent_install_or_broad_permission_denied() -> None:
    code = SRC.read_text()
    assert "request.installWithoutPrompt" in code
    assert "request.requestBroadInstallPermission" in code
    assert "!request.callerVerified" in code
    assert "request.approvedByModel)" not in code
    assert "fun realInstallerEnabled(): Boolean = false" in code


def test_n7a_04_api_unknown_sources_is_not_an_automatic_grant() -> None:
    code = SRC.read_text()
    assert "env.apiLevel !in 30..36" in code
    assert "requiresUnknownSourcesSettings = env.unknownSourcesAllowed != true" in code
    assert 'put("unknown_sources_granted", false)' in code
    assert 'put("requires_user_confirmation", requiresUserConfirmation)' in code
    assert "val unknownSourcesGranted: Boolean = false" in code


def test_n7a_05_cancel_replay_stop_keep_zero_sessions() -> None:
    code = SRC.read_text()
    for marker in (
        "@Synchronized", "request.requestId in seenRequests",
        "plans.size >= MAX_PLANS", "NativeInstallPlanStatus.REPLAY_DENIED",
        "NativeInstallPlanStatus.CANCELLED", "NativeInstallPlanStatus.STOPPED",
        "fun activeInstallerSessions(): Int = 0",
        'put("automatic_retry", false)',
    ):
        assert marker in code


def test_n7a_06_production_mcp_no_install_tool_and_manifest_unexpanded() -> None:
    gateway = GATEWAY.read_text()
    assert gateway.count("server.addTool(") == 1
    assert 'name = "device_status"' in gateway
    assert "AndroidPackageInstallerPlanBoundary" not in gateway
    assert "NativePackageInstallerPlans" not in gateway
    boundary = BOUNDARY.read_text()
    assert "NativeInstallPlanReceipt(NativeInstallPlanStatus.DENIED)" in boundary
    assert "fun realPackageInstallAllowed(): Boolean = false" in boundary
    for unsafe in ("createSession(", "openSession(", "PackageInstaller(", "startActivity("):
        assert unsafe not in boundary
    root = ET.parse(MANIFEST).getroot()
    permissions = {e.get(ANDROID + "name") for e in root.findall("uses-permission")}
    assert permissions == {
        "android.permission.INTERNET", "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }
    assert "android.permission.REQUEST_INSTALL_PACKAGES" not in permissions
