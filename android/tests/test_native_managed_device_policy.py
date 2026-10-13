"""N8.a managed-device feasibility has zero provisioning or admin side effects."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY = (
    ROOT
    / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol/NativeManagedDevicePolicy.kt"
)
BOUNDARY = (
    ROOT
    / "android/app/src/main/java/org/androidmcp/nativeapp/AndroidManagedDeviceBoundary.kt"
)
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"
GATEWAY = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp/LocalMcpGateway.kt"
ANDROID = "{http://schemas.android.com/apk/res/android}"


def test_n8a_01_non_deviceowner_is_unsupported() -> None:
    policy = POLICY.read_text()
    source = BOUNDARY.read_text()
    assert "env.ownDeviceOwnerVerified != true" in policy
    assert "ManagedPolicyState.UNSUPPORTED" in policy
    assert "context.packageName" in source
    assert "isDeviceOwnerApp" in source
    assert "declaredAdminReceiver = false" in source


def test_n8a_02_fake_verified_owner_returns_plan_only_and_capability_names() -> None:
    policy = POLICY.read_text()
    for value in ("policy_audit", "lock_task", "app_restrictions"):
        assert value in policy
    assert "ManagedPolicyState.PLAN_ONLY" in policy
    assert 'put("plan_only", planOnly)' in policy
    assert 'put("mutation_allowed", false)' in policy
    assert "fakeUserConfirmed" in policy


def test_n8a_03_model_admin_claim_cannot_self_provision_or_elevate() -> None:
    code = POLICY.read_text()
    assert "modelRoleClaim" in code
    assert "env.modelRoleClaim" not in code
    assert "SELF_PROVISION" in code
    assert "if (operation == ManagedPolicyOperation.INSPECT_MANAGED_FEATURES)" in code
    assert "ManagedPolicyState.DENIED" in code
    assert "fun realPolicyMutationAllowed(): Boolean = false" in code
    for source in (code, BOUNDARY.read_text()):
        for marker in ("setActiveAdmin(", "setDeviceOwner(", "ACTION_ADD_DEVICE_ADMIN"):
            assert marker not in source


def test_n8a_04_android_api_matrix_oem_uncertainty_fail_closed() -> None:
    code = POLICY.read_text()
    assert "setOf(30, 33, 34, 36)" in code
    assert "env.apiLevel !in SUPPORTED_APIS" in code
    assert "ManagedPolicyState.UNAVAILABLE" in code
    assert "Build.VERSION.SDK_INT" in BOUNDARY.read_text()
    assert "catch (_: RuntimeException)" in BOUNDARY.read_text()


def test_n8a_05_wipe_lock_account_policy_install_never_have_side_effects() -> None:
    code = POLICY.read_text()
    assert "WIPE_DEVICE, LOCK_DEVICE" in code
    assert "CHANGE_ACCOUNT, SILENT_INSTALL, SELF_PROVISION" in code
    assert "val sideEffectsPerformed: Boolean = false" in code
    assert 'put("side_effects_performed", false)' in code
    assert "ManagedPolicyReceipt(ManagedPolicyState.DENIED)" in code
    boundary = BOUNDARY.read_text()
    for forbidden in (
        "wipeData(",
        "lockNow(",
        "setLockTaskPackages(",
        "installPackage(",
        "setPermissionGrantState(",
        "setApplicationHidden(",
        "setUserRestriction(",
    ):
        assert forbidden not in boundary


def test_n8a_06_manifest_remains_without_admin_receiver_or_new_permission() -> None:
    manifest = ET.parse(MANIFEST).getroot()
    permissions = {e.get(ANDROID + "name") for e in manifest.findall("uses-permission")}
    assert permissions == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }
    assert manifest.findall(".//receiver") == []
    assert "android.permission.BIND_DEVICE_ADMIN" not in MANIFEST.read_text()
    assert "android.app.device_admin" not in MANIFEST.read_text()
    gateway = GATEWAY.read_text()
    assert gateway.count("server.addTool(") == 1
    assert 'name = "device_status"' in gateway
    assert "AndroidManagedDeviceBoundary" not in gateway
    assert "NativeManagedDevicePolicy" not in gateway
    assert "fun realPolicyMutationAllowed(): Boolean = false" in BOUNDARY.read_text()


def test_android_adapter_uses_only_own_deviceowner_query_not_admin_mutations() -> None:
    source = BOUNDARY.read_text()
    assert "getSystemService(DevicePolicyManager::class.java)" in source
    assert "?.isDeviceOwnerApp(context.packageName)" in source
    for dangerous in (
        "DeviceAdminReceiver",
        "ACTION_ADD_DEVICE_ADMIN",
        "setDeviceOwner",
        "wipeData(",
        "lockNow(",
        "setLockTaskFeatures(",
        "setApplicationHidden(",
    ):
        # The adapter comments may mention an absent receiver; look for calls.
        if dangerous == "DeviceAdminReceiver":
            assert "class DeviceAdminReceiver" not in source
        else:
            assert dangerous not in source
