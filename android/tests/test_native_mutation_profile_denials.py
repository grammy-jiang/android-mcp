"""N6.e: fake high-risk Tool profiles must never enable an Android mutation."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROTO = ROOT / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol"
APP = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
ANDROID = "{http://schemas.android.com/apk/res/android}"
PROFILE = PROTO / "NativeMutationProfile.kt"
BOUNDARY = APP / "AndroidMutationProfileBoundary.kt"
GATEWAY = APP / "LocalMcpGateway.kt"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"


def test_n6e_01_default_kotlin_public_tools_list_has_no_mutation_tool() -> None:
    gateway = GATEWAY.read_text()
    assert gateway.count("server.addTool(") == 1
    assert 'name = "device_status"' in gateway
    for forbidden in (
        'name = "ui_gesture"', 'name = "apk_install"',
        'name = "system_setting"', 'name = "screen_capture"',
        "AndroidMutationProfileBoundary", "NativeMutationPolicy",
    ):
        assert forbidden not in gateway
    assert "fun publicMutatingTools(): List<String> = emptyList()" in PROFILE.read_text()


def test_n6e_02_model_approval_and_stale_fake_grants_never_authenticate() -> None:
    source = PROFILE.read_text()
    assert "!request.fakeCallerVerified" in source
    assert "!request.fakeSignedActionFresh" in source
    assert "!request.fakeLeasePresent" in source
    assert "request.processEpoch != processEpoch" in source
    assert "NativeMutationStatus.UNAUTHENTICATED" in source
    assert "if (request.modelApproved)" not in source
    assert "NativeMutationStatus.DISABLED" in source
    assert "fun realMutationAllowed(): Boolean = false" in source


def test_n6e_03_no_synthetic_android_consent_to_real_execution_bridge() -> None:
    source = PROFILE.read_text()
    assert "!request.fakeRuntimeConsent" in source
    assert "NativeMutationStatus.CONSENT_REQUIRED" in source
    assert "UI_GESTURE, APK_INSTALL, SYSTEM_SETTING, SCREEN_CAPTURE" in source
    assert "permissionGranted" not in BOUNDARY.read_text()
    for forbidden in ("dispatchGesture(", "startActivity(", "PackageInstaller("):
        assert forbidden not in BOUNDARY.read_text()


def test_n6e_04_inert_metadata_explicitly_nonidempotent_and_disabled() -> None:
    source = PROFILE.read_text()
    for token in (
        'put("enabled", false)', 'put("read_only", false)',
        'put("idempotent", false)', 'put("potentially_destructive",',
        'put("requires_verified_user_consent", true)',
        'put("requires_independent_security_review", true)',
        'put("executable", false)',
    ):
        assert token in source


def test_n6e_05_uncertain_result_and_user_stop_prevent_blind_replay() -> None:
    source = PROFILE.read_text()
    assert "request.actionDigest in ambiguousDigests" in source
    assert "NativeMutationStatus.UNCERTAIN" in source
    assert "ambiguousDigests.size >= MAX_AMBIGUOUS" in source
    assert "private const val MAX_AMBIGUOUS = 32" in source
    assert 'put("automatic_retry", false)' in source
    assert "if (stopped) return denied(NativeMutationStatus.STOPPED)" in source
    assert "fun realMutationAllowed(): Boolean = false" in source


def test_n6e_06_android_manifest_and_production_dispatch_still_denied() -> None:
    manifest = ET.parse(MANIFEST).getroot()
    perms = {item.get(ANDROID + "name") for item in manifest.findall("uses-permission")}
    assert perms == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }
    for component in manifest.findall(".//service"):
        assert component.get(ANDROID + "permission") != "android.permission.BIND_ACCESSIBILITY_SERVICE"
    assert manifest.find(".//receiver") is None
    boundary = BOUNDARY.read_text()
    assert "MutationDenyReceipt(NativeMutationStatus.DISABLED)" in boundary
    assert "fun realMutationAllowed(): Boolean = false" in boundary
    assert "AndroidMutationProfileBoundary" not in GATEWAY.read_text()
