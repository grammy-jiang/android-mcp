"""N1.c app-owning health safety guards; no live Android device touched."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = "{http://schemas.android.com/apk/res/android}"
APP = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
ADAPTER = APP / "AndroidAppHealthReader.kt"
SERVICE = APP / "NativeMcpForegroundService.kt"
GATEWAY = APP / "LocalMcpGateway.kt"
MODEL = ROOT / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol/NativeAppHealth.kt"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"


def test_health_adapter_uses_only_owner_and_monotonic_process_signals() -> None:
    source = ADAPTER.read_text()
    for required in (
        "NativeServiceLifecycle",
        "lifecycle.snapshot().phase",
        "PortPhase.READY",
        "SystemClock.elapsedRealtime()",
        "Build.VERSION.SDK_INT",
        "notificationPromoted",
        "NativeAppHealthSnapshots.evaluate(",
    ):
        assert required in source
    for forbidden in (
        "getRunningAppProcesses",
        "ActivityManager",
        "getProcessMemoryInfo",
        "getInstalledPackages",
        "Logcat",
        "Settings.Secure",
        "getStackTrace",
        "Build.SERIAL",
        "getSerial(",
    ):
        assert forbidden not in source


def test_not_sticky_service_still_has_no_autostart_receivers() -> None:
    service = SERVICE.read_text()
    assert "START_NOT_STICKY" in service
    assert "START_STICKY" not in service
    app = ET.parse(MANIFEST).getroot().find("application")
    assert app is not None
    assert app.findall("receiver") == []
    services = app.findall("service")
    assert len(services) == 1
    assert services[0].get(ANDROID + "exported") == "false"


def test_health_is_not_new_public_mcp_resource_or_tool() -> None:
    gateway = GATEWAY.read_text()
    assert gateway.count("server.addTool(") == 1
    assert 'name = "device_status"' in gateway
    assert "AndroidAppHealthReader" not in gateway
    assert "NativeAppHealth" not in gateway
    model = MODEL.read_text()
    assert "buildJsonObject" in model
    assert '"stacktrace"' not in model.lower()
    assert "NativeStopCause.PROCESS_DEATH" in model
