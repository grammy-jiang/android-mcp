"""N4.a strict nonexecuting Android UI gesture planning boundary."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = "{http://schemas.android.com/apk/res/android}"
APP = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
MODEL = ROOT / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol/NativeUiActionPlan.kt"
ADAPTER = APP / "AndroidUiActionPlanBoundary.kt"
GATEWAY = APP / "LocalMcpGateway.kt"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"


def test_T_N4A_01_four_typed_actions_and_window_anchor() -> None:
    code = MODEL.read_text()
    for part in (
        "TAP, SWIPE, SCROLL, KEY",
        "val windowHandle: String",
        "val nodeEpoch: String",
        "val nodeHandle: String",
        "val currentNodeHandles: Set<String>",
        "focusedWindowHandle",
        "environment.nodeEpoch != intent.nodeEpoch",
        "intent.nodeHandle !in environment.currentNodeHandles",
        "UiActionPlanState.PLAN_ONLY",
    ):
        assert part in code


def test_T_N4A_02_bounds_and_arbitrary_shell_text_denied() -> None:
    code = MODEL.read_text()
    for check in (
        "intent.shellText != null",
        "environment.currentRotation != intent.rotation",
        "x in 0 until env.displayWidth",
        "y in 0 until env.displayHeight",
        "intent.durationMs in 100..2000",
        "intent.steps in 1..10",
        "UiAllowedKey",
        "UiActionPlanState.OUT_OF_BOUNDS",
        "UiActionPlanState.ROTATION_MISMATCH",
    ):
        assert check in code
    assert "Runtime.getRuntime(" not in code


def test_T_N4A_03_service_lock_authentication_and_foreground_fail_closed() -> None:
    code = MODEL.read_text()
    for required in (
        "!environment.fakeCallerAuthenticated",
        "!environment.fakeUserApproval",
        "!environment.fakeAccessibilityAvailable",
        "!environment.screenUnlocked",
        "environment.secureWindow",
        "!environment.foreground",
        "UiActionPlanState.STALE",
        "UiActionPlanState.UNAUTHENTICATED",
        "UiActionPlanState.SERVICE_UNAVAILABLE",
    ):
        assert required in code


def test_T_N4A_04_execution_nonidempotent_and_uncertain_after_fake_dispatch() -> None:
    code = MODEL.read_text()
    assert 'put("idempotent", false)' in code
    assert 'put("executed", false)' in code
    assert "UiActionPlanState.UNCERTAIN" in code
    assert "UiActionPlanState.CANCELLED" in code
    assert "fun realDispatchCount(): Int = 0" in code
    assert "fun markFakeDispatchStarted()" in code


def test_T_N4A_06_production_adapter_and_mcp_never_inject_gestures() -> None:
    code = ADAPTER.read_text()
    assert "UiActionPlanState.SERVICE_UNAVAILABLE" in code
    assert "digest = null" in code
    assert "requiresFreshAuthorization = false" in code
    for forbidden in (
        "dispatchGesture(",
        "performGlobalAction(",
        "sendKeyEvent(",
        "injectInputEvent(",
        "startActivity(",
        "Runtime.getRuntime(",
        "ProcessBuilder(",
        "input tap",
        "Instrumentation(",
    ):
        assert forbidden not in code
    live = GATEWAY.read_text()
    assert live.count("server.addTool(") == 1
    assert 'name = "device_status"' in live
    assert "AndroidUiActionPlanBoundary" not in live
    assert "native_tap" not in live
    permissions = {
        entry.get(ANDROID + "name")
        for entry in ET.parse(MANIFEST).getroot().findall("uses-permission")
    }
    assert permissions == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }
