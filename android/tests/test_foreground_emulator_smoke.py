"""SDK-free safety and identity tests for Native foreground emulator smoke."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts/smoke-native-foreground-emulator.py"
)
spec = importlib.util.spec_from_file_location(
    "native_foreground_emulator_smoke", SCRIPT
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize(
    "serial", ["", "8971a7bf", "-s", "tcp:5555", "emulator-5554; reboot"]
)
def test_denies_real_android_targets(serial: str) -> None:
    with pytest.raises(ValueError):
        module.core.require_emulator_serial(serial)


def test_notification_permission_is_specific() -> None:
    assert module.NOTIFICATION_PERMISSION == "android.permission.POST_NOTIFICATIONS"


def test_test_targets_explicitly_named_preview_controls() -> None:
    assert module.START_SERVICE_SCREEN == "Open persistent service preview"
    assert module.START_SERVICE_BUTTON == "Start background local MCP"
    assert module.STOP_SERVICE_BUTTON == "Stop background local MCP"


def test_generic_ui_selector_fails_on_ambiguous_background_start() -> None:
    text = '<hierarchy><node text="START BACKGROUND LOCAL MCP" bounds="[1,2][8,9]"/></hierarchy>'
    assert module.core.get_button_center(text, module.START_SERVICE_BUTTON) == (4, 5)
    with pytest.raises(ValueError):
        module.core.get_button_center(text, "Unknown control")


def test_service_screen_detection_is_deterministic() -> None:
    service_xml = (
        '<hierarchy><node text="START BACKGROUND LOCAL MCP" bounds="[10,20][110,60]"/>'
        '<node text="STOP BACKGROUND LOCAL MCP" bounds="[10,80][110,120]"/></hierarchy>'
    )
    launcher_xml = '<hierarchy><node text="OPEN PERSISTENT SERVICE PREVIEW" bounds="[10,20][110,60]"/></hierarchy>'
    assert module.identify_service_screen(service_xml) == "service"
    assert module.identify_service_screen(launcher_xml) == "launcher"
    assert module.identify_service_screen("<hierarchy/>") == "unknown"


def test_service_dump_requires_named_android_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module.core, "adb", lambda *args, **kwargs: "OtherService only")
    with pytest.raises(AssertionError, match="instance is missing"):
        module.check_service_running("emulator-5554")


def test_service_dump_reports_running_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        module.core,
        "adb",
        lambda *args, **kwargs: (
            "ServiceRecord NativeMcpForegroundService "
            "isForeground=true foregroundId=23166 "
            "foregroundNoti=Notification(channel=android_mcp_local_developer)"
        ),
    )
    module.check_service_running("emulator-5554")


def test_unpromoted_service_is_not_reported_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        module.core,
        "adb",
        lambda *args, **kwargs: (
            "ServiceRecord NativeMcpForegroundService isForeground=false"
        ),
    )
    with pytest.raises(AssertionError, match="not actually promoted"):
        module.check_service_running("emulator-5554")
