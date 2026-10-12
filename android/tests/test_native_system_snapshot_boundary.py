"""N1.b source and manifest guards for user-consent-safe system snapshots."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
ADAPTER = APP / "AndroidSystemSnapshotReader.kt"
GATEWAY = APP / "LocalMcpGateway.kt"
MODEL = ROOT / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol/NativeSystemSnapshot.kt"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"
ANDROID = "{http://schemas.android.com/apk/res/android}"


def test_battery_storage_display_use_app_apis_and_monotonic_time() -> None:
    source = ADAPTER.read_text()
    for required in (
        "BatteryManager.BATTERY_PROPERTY_CAPACITY",
        "StatFs(context.filesDir.absolutePath)",
        "stat.availableBytes",
        "stat.totalBytes",
        "context.resources.displayMetrics",
        "SystemClock.elapsedRealtime()",
        "NativeSystemSnapshots.normalize",
    ):
        assert required in source
    assert "registerReceiver" not in source
    assert "requestPermissions" not in source
    assert "getExternalStorage" not in source


def test_network_permission_is_checked_before_connectivity_manager() -> None:
    source = ADAPTER.read_text()
    assert "Manifest.permission.ACCESS_NETWORK_STATE" in source
    assert "context.checkSelfPermission" in source
    assert "if (granted != true) return NativeNetworkReadiness.PERMISSION_DENIED" in source
    assert source.index("if (granted != true)") < source.index(
        "context.getSystemService(ConnectivityManager::class.java)"
    )
    for forbidden in (
        "getConnectionInfo(",
        "getScanResults(",
        "getLinkProperties(",
        "WifiManager",
        "LocationManager",
        "SSID",
        "BSSID",
        "NetworkInterface",
    ):
        assert forbidden not in source


def test_no_extra_manifest_permissions_or_public_tool() -> None:
    manifest = ET.parse(MANIFEST).getroot()
    permissions = {item.get(ANDROID + "name") for item in manifest.findall("uses-permission")}
    assert permissions == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }
    assert "android.permission.ACCESS_NETWORK_STATE" not in permissions
    gateway = GATEWAY.read_text()
    assert gateway.count("server.addTool(") == 1
    assert 'name = "device_status"' in gateway
    assert "NativeSystemSnapshot" not in gateway
    assert "AndroidSystemSnapshotReader" not in gateway
    model = MODEL.read_text()
    assert "MAX_STORAGE_BYTES" in model
    assert "MAX_DISPLAY_DIMENSION" in model
