"""N2.c source contract: exact exported Activity plan, no userless launch."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = "{http://schemas.android.com/apk/res/android}"
APP = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
PLAN_ADAPTER = APP / "AndroidIntentPlanReader.kt"
PLANNER = ROOT / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol/NativeIntentPlan.kt"
GATEWAY = APP / "LocalMcpGateway.kt"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"


def test_n2c_adapter_only_resolves_explicit_component_without_starting_activity() -> None:
    source = PLAN_ADAPTER.read_text()
    for expected in (
        "internal object AndroidIntentPlanReader",
        "NativeIntentPlans.preflight(",
        "AndroidVisiblePackagesReader.read(context)",
        "context.packageManager.getActivityInfo(component, 0)",
        "ComponentName(",
        "NativeIntentPlanner.plan(",
        "NativeResolvedActivity(",
        "explicitUserGestureObserved",
        "isCallerActivityForeground",
        "localAllowlistedComponents",
    ):
        assert expected in source
    for forbidden in (
        "startActivity(",
        "startActivities(",
        "startIntentSender(",
        "sendBroadcast(",
        "sendOrderedBroadcast(",
        "startService(",
        "startForegroundService(",
        "intent.data",
        "Intent.ACTION_VIEW",
        "Intent.ACTION_SEND",
        "FLAG_ACTIVITY_NEW_TASK",
        "grantUriPermission(",
        "requestPermissions(",
        "Runtime.getRuntime",
        "ProcessBuilder",
        "ActivityManager",
    ):
        assert forbidden not in source


def test_n2c_planner_fixed_action_bounds_and_strict_denial_before_resolution() -> None:
    source = PLANNER.read_text()
    assert 'private const val ACTION_MAIN = "android.intent.action.MAIN"' in source
    assert 'private const val CATEGORY_LAUNCHER = "android.intent.category.LAUNCHER"' in source
    assert "request.uri != null || request.extras.isNotEmpty()" in source
    assert "request.flags != 0 || request.selector" in source
    assert "request.userScope != \"current\"" in source
    assert "request.activityName.startsWith(request.packageName" in source
    assert "request.packageName + \"/\" + request.activityName" in source
    assert "VisiblePackageLookup.VISIBLE" in source
    assert "NativeIntentPlanState.NOT_EXPORTED" in source
    assert "NativeIntentPlanState.BACKGROUND_RESTRICTED" in source
    assert '"executed", false' in source
    assert "VisibleActivityResolver" in source


def test_n2c_manifest_public_catalog_and_host_ownership_unchanged() -> None:
    gateway = GATEWAY.read_text()
    assert gateway.count("server.addTool(") == 1
    assert 'name = "device_status"' in gateway
    assert "AndroidIntentPlanReader" not in gateway
    assert "NativeIntentPlans" not in gateway
    permissions = {
        item.get(ANDROID + "name")
        for item in ET.parse(MANIFEST).getroot().findall("uses-permission")
    }
    assert permissions == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }
    assert "QUERY_ALL_PACKAGES" not in " ".join(sorted(permissions))
