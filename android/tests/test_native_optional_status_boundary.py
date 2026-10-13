"""N4.f permission-safe own-app status and synthetic subscription guardrails."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = "{http://schemas.android.com/apk/res/android}"
APP = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
ADAPTER = APP / "AndroidOptionalStatusReader.kt"
GATEWAY = APP / "LocalMcpGateway.kt"
MODEL = ROOT / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol/NativeOptionalStatus.kt"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"


def test_t_n4f_01_only_app_coarse_battery_display_and_exact_grant_metadata() -> None:
    source = ADAPTER.read_text()
    assert "AndroidSystemSnapshotReader.read(context)" in source
    assert "NativeOptionalStatusSession().snapshot(" in source
    assert "Build.VERSION.SDK_INT" in source
    assert "Manifest.permission.POST_NOTIFICATIONS" in source
    assert "context.checkSelfPermission" in source
    assert "networkPermissionGranted = false" in source


def test_t_n4f_02_no_sensitive_android_sensor_or_notification_api_used() -> None:
    source = ADAPTER.read_text()
    for forbidden in (
        "LocationManager",
        "FusedLocation",
        "AudioRecord",
        "MediaRecorder",
        "getContacts",
        "ContactsContract",
        "NotificationListenerService",
        "NotificationManager.getActiveNotifications",
        "SensorManager",
        "registerListener(",
        "requestLocationUpdates(",
        "ConnectivityManager",
        "WifiManager",
        "getScanResults(",
        "getConnectionInfo(",
    ):
        assert forbidden not in source


def test_t_n4f_03_no_background_loop_or_permission_silent_enablement() -> None:
    source = MODEL.read_text()
    assert "fun realSensorSubscriptionAllowed(): Boolean = false" in source
    assert "if (!input.foreground)" in source
    assert "OptionalReadiness.DISABLED" in source
    assert "MAX_EVENTS = 16" in source
    assert "MIN_INTERVAL_MS = 1_000L" in source
    assert "stopped = true" in source
    assert "fakeSamples.clear()" in source


def test_t_n4f_04_explicit_unknown_and_revoked_grant_states() -> None:
    model = MODEL.read_text()
    assert "input.networkPermissionGranted == true" in model
    assert "OptionalReadiness.PERMISSION_DENIED" in model
    assert "OptionalReadiness.UNSUPPORTED" in model
    assert "OptionalReadiness.UNAVAILABLE" in model
    assert "input.apiLevel !in 30..100" in model
    assert "batteryPercent?.takeIf { it in 0..100 }" in model


def test_t_n4f_06_no_public_surveillance_tool_or_manifest_permission() -> None:
    gateway = GATEWAY.read_text()
    assert gateway.count("server.addTool(") == 1
    assert 'name = "device_status"' in gateway
    assert "AndroidOptionalStatusReader" not in gateway
    assert "native_optional_sensors" not in gateway
    manifest = ET.parse(MANIFEST).getroot()
    permissions = {
        item.get(ANDROID + "name") for item in manifest.findall("uses-permission")
    }
    assert permissions == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }
    for forbidden in (
        "android.permission.ACCESS_FINE_LOCATION",
        "android.permission.RECORD_AUDIO",
        "android.permission.READ_CONTACTS",
        "android.permission.ACCESS_NETWORK_STATE",
        "android.permission.BODY_SENSORS",
        "android.permission.BIND_NOTIFICATION_LISTENER_SERVICE",
    ):
        assert forbidden not in permissions
