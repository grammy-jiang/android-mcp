"""N3.a private MediaProjection consent plan and APK/Manifest hard denials."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = "{http://schemas.android.com/apk/res/android}"
APP = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"
READER = APP / "AndroidProjectionConsentReader.kt"
GATEWAY = APP / "LocalMcpGateway.kt"
MODEL = ROOT / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol/NativeProjectionConsent.kt"


def test_T_N3A_01_reader_cannot_generate_real_projection_or_consent_ui() -> None:
    source = READER.read_text()
    assert "MediaProjectionManager::class.java" in source
    assert "internal object AndroidProjectionConsentReader" in source
    assert "NativeProjectionConsent(" in source
    assert "callerForeground" in source
    for forbidden in (
        "createScreenCaptureIntent(",
        "getMediaProjection(",
        "startActivity(",
        "startActivityForResult(",
        "registerForActivityResult(",
        "requestPermissions(",
        "startForegroundService(",
        "ImageReader",
        "MediaRecorder",
        "MediaCodec",
        "VirtualDisplay",
        "createVirtualDisplay(",
        "su ",
    ):
        assert forbidden not in source


def test_T_N3A_03_api34_fgs_type_checked_without_manifest_expansion() -> None:
    source = READER.read_text()
    assert "if (api >= 34)" in source
    assert "Manifest.permission.FOREGROUND_SERVICE_MEDIA_PROJECTION" in source
    assert "ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION" in source
    assert "context.packageManager.getServiceInfo(" in source
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
    assert "android.permission.FOREGROUND_SERVICE_MEDIA_PROJECTION" not in permissions
    app = manifest.find("application")
    assert app is not None
    services = app.findall("service")
    assert len(services) == 1
    assert services[0].get(ANDROID + "foregroundServiceType") == "specialUse"
    assert "mediaProjection" not in services[0].get(
        ANDROID + "foregroundServiceType", ""
    )


def test_T_N3A_05_remote_unpaired_capture_remains_unregistered() -> None:
    gateway = GATEWAY.read_text()
    assert gateway.count("server.addTool(") == 1
    assert 'name = "device_status"' in gateway
    assert "AndroidProjectionConsentReader" not in gateway
    for forbidden in ("native_screen_capture", "mediaProjection", "capture_screen"):
        assert forbidden not in gateway


def test_T_N3A_06_no_synthetic_token_can_create_real_capture_from_policy() -> None:
    source = MODEL.read_text()
    assert "fun captureAllowed(): Boolean = false" in source
    assert "put(\"can_capture_now\", false)" in source
    assert "SIMULATED_ONLY" in source
    assert "REPLAY_DENIED" in source
    assert "STALE_DENIED" in source
    assert "ProjectionLifecycleEvent" in source
    for forbidden in ("import android.media.projection.MediaProjectionManager", "getMediaProjection(", "ImageReader(", "createVirtualDisplay("):
        assert forbidden not in source
