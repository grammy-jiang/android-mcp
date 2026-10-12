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


def test_notification_stop_requires_exact_title_and_unambiguous_action() -> None:
    good = (
        '<hierarchy><node text="Android MCP local service" bounds="[1,2][10,12]"/>'
        '<node text="STOP" content-desc="Stop" class="android.widget.Button" '
        'bounds="[10,20][110,60]"/></hierarchy>'
    )
    assert module.notification_stop_button_center(good) == (60, 40)
    with pytest.raises(ValueError, match="not visible"):
        module.notification_stop_button_center(
            '<hierarchy><node text="STOP" bounds="[10,20][110,60]"/></hierarchy>'
        )
    duplicate = good.replace(
        "</hierarchy>", ('<node text="STOP" bounds="[15,20][110,60]"/></hierarchy>')
    )
    with pytest.raises(ValueError, match="unambiguous"):
        module.notification_stop_button_center(duplicate)


def test_notification_oracle_distinguishes_channel_from_live_record() -> None:
    active = (
        "NotificationRecord(0xabc: pkg=org.androidmcp.nativeapp "
        "user=UserHandle{0} id=23166 tag=null)"
    )
    assert module.has_ongoing_notification_record(active)
    assert not module.has_ongoing_notification_record(
        "NotificationChannel{mId='android_mcp_local_developer', mName='Android MCP'}"
    )
    assert not module.has_ongoing_notification_record(
        "NotificationRecord(0xabc: pkg=other.app user=UserHandle{0} id=23166)"
    )
    assert not module.has_ongoing_notification_record(
        "NotificationRecord(0xabc: pkg=org.androidmcp.nativeapp user=UserHandle{0} id=42)"
    )


def test_stop_proof_denies_disconnected_adb_forward(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module.core, "adb", lambda *args, **kwargs: "")
    with pytest.raises(AssertionError, match="forwarding disappeared"):
        module.assert_forward_present("emulator-5554", 50955)


def test_stop_proof_denies_service_still_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module.core, "verify_emulator", lambda _serial: None)
    monkeypatch.setattr(module.time, "sleep", lambda _delay: None)

    def fake_adb(_serial: str, *args: str, **kwargs: object) -> str:
        if "services" in args:
            return "ServiceRecord NativeMcpForegroundService isForeground=true"
        return ""

    monkeypatch.setattr(module.core, "adb", fake_adb)
    with pytest.raises(AssertionError, match="not removed"):
        module.await_android_service_and_notification_removed("emulator-5554")


def test_stop_proof_denies_notification_still_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module.core, "verify_emulator", lambda _serial: None)
    monkeypatch.setattr(module.time, "sleep", lambda _delay: None)

    def fake_adb(_serial: str, *args: str, **kwargs: object) -> str:
        if "notification" in args:
            return (
                "NotificationRecord(0xabc: pkg=org.androidmcp.nativeapp "
                "user=UserHandle{0} id=23166 tag=null)"
            )
        return ""

    monkeypatch.setattr(module.core, "adb", fake_adb)
    with pytest.raises(AssertionError, match="not removed"):
        module.await_android_service_and_notification_removed("emulator-5554")
