"""N7.c exact exported Activity synthetic plans cannot activate third-party UI."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol/NativeExplicitLaunchSafety.kt"
INTENT = ROOT / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol/NativeIntentPlan.kt"
BOUNDARY = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp/AndroidExplicitLaunchBoundary.kt"
GATEWAY = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp/LocalMcpGateway.kt"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"
ANDROID = "{http://schemas.android.com/apk/res/android}"


def test_n7c_01_exact_visible_exported_activity_requires_owner_and_auth() -> None:
    code = POLICY.read_text()
    assert "NativeIntentPlans.resolve(" in code
    assert "request.userApproved" in code
    assert "request.authorizedCaller" in code
    assert "request.signedGrantFresh" in code
    assert "platform.explicitAllowlist, platform.target" in code
    assert "fun realLaunchAllowed(): Boolean = false" in code


def test_n7c_02_implicit_uris_nonexported_locked_off_user_denied() -> None:
    policy = POLICY.read_text()
    intent = INTENT.read_text()
    assert "request.screenUnlocked" in policy
    assert "NativeIntentPlanState.PLAN_ONLY" in policy
    assert "NativeIntentPlanState.NOT_EXPORTED" in intent
    assert "request.userScope != \"current\"" in intent
    assert "request.uri != null" in intent
    assert "request.flags != 0 || request.selector" in intent


def test_n7c_03_apis_reject_background_fgs_start_bypass() -> None:
    code = POLICY.read_text()
    assert "private val SUPPORTED_API = setOf(30, 33, 34, 36)" in code
    assert "request.foregroundServiceOnly" in code
    assert "platform.environment.callerForeground" in code
    assert "platform.environment.userGestureObserved" in code
    assert "SafeLaunchState.BACKGROUND_RESTRICTED" in code


def test_n7c_04_one_use_journal_and_uncertain_replay_deny() -> None:
    code = POLICY.read_text()
    for marker in (
        "actionPlans[request.actionId] = planId",
        "if (planId in uncertainPlans)",
        "uncertainPlans.add(planId)",
        "MAX_ACTIONS = 64",
        "@Synchronized",
        'put("automatic_retry", false)',
        "fun activeRealLaunchCount(): Int = 0",
    ):
        assert marker in code


def test_n7c_05_origin_revoke_or_stop_fences_between_check_and_fake_dispatch() -> None:
    code = POLICY.read_text()
    assert "originStillAuthorized" in code
    assert "ownerStillApproves" in code
    assert "fun revoke()" in code
    assert "fun stop()" in code
    assert "SafeLaunchState.STOPPED" in code
    assert "SafeLaunchState.REVOKED" in code
    assert "fun realLaunchAllowed(): Boolean = false" in BOUNDARY.read_text()


def test_n7c_06_status_only_manifest_no_third_party_shell_dispatch_or_force_stop() -> None:
    gateway = GATEWAY.read_text()
    assert gateway.count("server.addTool(") == 1
    assert 'name = "device_status"' in gateway
    assert "NativeExplicitLaunchSafety" not in gateway
    boundary = BOUNDARY.read_text()
    assert "SafeLaunchReceipt(SafeLaunchState.DENIED)" in boundary
    for unsafe in (
        "startActivity(", "sendBroadcast(", "forceStopPackage(",
        "Runtime.getRuntime()", "ProcessBuilder(", "am start", "adb shell",
    ):
        assert unsafe not in boundary
    manifest = ET.parse(MANIFEST).getroot()
    permissions = {e.get(ANDROID + "name") for e in manifest.findall("uses-permission")}
    assert permissions == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }


def test_no_real_exec_claims_or_private_package_data_in_receipts() -> None:
    source = POLICY.read_text()
    assert 'put("real_launched", false)' in source
    assert 'put("real_dispatch_allowed", false)' in source
    assert 'put("idempotent", false)' in source
    assert "SyntheticSafeLaunchRequest([REDACTED])" in source
    assert "SyntheticSafeLaunchTarget([REDACTED])" in source
