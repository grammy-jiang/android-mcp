"""N3.b inert synthetic frame/artifact boundary, never accesses real Android."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = "{http://schemas.android.com/apk/res/android}"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"
APP = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
GATEWAY = APP / "LocalMcpGateway.kt"
POLICY = APP / "AndroidProjectionConsentReader.kt"
CAPTURE = (
    ROOT / "android/native-lifecycle/src/main/kotlin/org/androidmcp/lifecycle"
    / "NativeSyntheticOneShotCapture.kt"
)
ARTIFACT = (
    ROOT / "android/native-lifecycle/src/main/kotlin/org/androidmcp/lifecycle"
    / "NativeArtifactStore.kt"
)


def test_T_N3B_02_no_physical_or_synthetic_capture_tool_in_public_apk_registry() -> None:
    gateway = GATEWAY.read_text()
    assert gateway.count("server.addTool(") == 1
    assert 'name = "device_status"' in gateway
    for forbidden in (
        "NativeSyntheticOneShotCapture",
        "MediaProjection",
        "capture_screen",
        "screen_capture",
        "native_capture_frame",
        "AndroidCaptureFrame",
    ):
        assert forbidden not in gateway


def test_T_N3B_03_fake_png_validation_and_bounds_are_strict() -> None:
    source = CAPTURE.read_text()
    for required in (
        "MAX_DIMENSION = 4096",
        "MAX_PIXELS = 4_194_304L",
        "MAX_FRAME_BYTES = 8 * 1024 * 1024",
        "MAX_CAPTURE_MS = 3_000L",
        'frame.mimeType != "image/png"',
        "CRC32",
        "PNG_MAGIC",
        "IHDR",
        "IDAT",
        "IEND",
        "length + 12L",
        "NativeArtifactStore(",
        "ttlMs = 60_000",
        "maxEntries = 1",
    ):
        assert required in source
    assert "ImageReader(" not in source
    assert "VirtualDisplay(" not in source
    assert "getMediaProjection(" not in source


def test_T_N3B_05_cleanup_and_replay_never_enable_real_capture() -> None:
    source = CAPTURE.read_text()
    assert "private var spent = false" in source
    assert "if (spent)" in source
    assert "copy.fill(0)" in source
    assert "artifacts?.close()" in source
    assert "fun captureRealIsAllowed(): Boolean = false" in source
    assert "private var closed = false" in source
    assert "capture_executed" in source
    assert "SIMULATED_ONLY" in source
    assert "REPLAY_DENIED" in source
    assert "STALE_DENIED" in source


def test_T_N3B_06_manifest_remains_zero_capture_permission() -> None:
    manifest = ET.parse(MANIFEST).getroot()
    actual = {x.get(ANDROID + "name") for x in manifest.findall("uses-permission")}
    assert actual == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }
    assert "android.permission.FOREGROUND_SERVICE_MEDIA_PROJECTION" not in actual
    app = manifest.find("application")
    assert app is not None
    services = app.findall("service")
    assert len(services) == 1
    assert services[0].get(ANDROID + "foregroundServiceType") == "specialUse"
    assert "createScreenCaptureIntent(" not in POLICY.read_text()


def test_artifact_reuse_is_private_and_atomic_not_network_export() -> None:
    code = ARTIFACT.read_text()
    assert "NativeArtifactStore" in code
    assert "NOFOLLOW_LINKS" in code
    assert "StandardCopyOption.ATOMIC_MOVE" in code
    assert "rwx------" in code
    assert "rw-------" in code
    assert "Socket(" not in code
    assert "ServerSocket(" not in code
