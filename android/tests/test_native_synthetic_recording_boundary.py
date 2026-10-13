"""N3.c finite fake recording, no real Android projection or public capture."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = "{http://schemas.android.com/apk/res/android}"
RECORDER = (
    ROOT / "android/native-lifecycle/src/main/kotlin/org/androidmcp/lifecycle"
    / "NativeSyntheticRecording.kt"
)
APP = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
GATEWAY = APP / "LocalMcpGateway.kt"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"


def test_T_N3C_01_finite_dimensions_duration_and_bounded_private_storage() -> None:
    code = RECORDER.read_text()
    for required in (
        "MAX_DURATION_MS = 30_000",
        "MAX_WIDTH = 1920",
        "MAX_HEIGHT = 1080",
        "MAX_FRAME_RATE = 30",
        "MAX_RECORDING_BYTES = 8 * 1024 * 1024",
        "MAX_CHUNK_BYTES = 256 * 1024",
        "MIN_CAPTURE_BYTES = 16",
        "NativeArtifactStore(",
        "PRIVATE_TTL_MS = 60_000L",
        "maxEntries = 1",
        'privateOwner.create(bytes, "video/mp4")',
    ):
        assert required in code


def test_T_N3C_02_fake_permit_never_becomes_an_android_projection_grant() -> None:
    code = RECORDER.read_text()
    assert "permit.processEpoch != processEpoch" in code
    assert "fakeCallerAuthenticated" in code
    assert "fakeUiConsentGranted" in code
    assert "mediaProjectionFgsTypeDeclared" in code
    assert "callerForeground" in code
    assert "if (spent)" in code
    assert "SyntheticRecordingStatus.REPLAY_DENIED" in code
    assert "SyntheticRecordingStatus.STALE_DENIED" in code
    assert "fun realRecordingAllowed(): Boolean = false" in code


def test_T_N3C_03_cancellation_closes_artifacts_and_wipes_buffers() -> None:
    code = RECORDER.read_text()
    assert "SyntheticRecordingStopEvent" in code
    assert "PROJECTIon" not in code  # case-correct enum is PROJECTION_ON_STOP
    assert "PROJECTION_ON_STOP" in code
    assert "PROCESS_DEATH" in code
    assert "FGS_STOP" in code
    assert "clearChunks()" in code
    assert "chunk.fill(0)" in code
    assert "ownerStore?.close()" in code
    assert "bytes.fill(0)" in code


def test_T_N3C_06_live_mcp_and_android_manifest_are_privilege_free() -> None:
    gateway = GATEWAY.read_text()
    assert gateway.count("server.addTool(") == 1
    assert 'name = "device_status"' in gateway
    assert "NativeSyntheticRecording" not in gateway
    assert "video_record" not in gateway
    assert "screen_recording" not in gateway
    manifest = ET.parse(MANIFEST).getroot()
    actual = {
        permission.get(ANDROID + "name") for permission in manifest.findall("uses-permission")
    }
    assert actual == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }
    app = manifest.find("application")
    assert app is not None
    services = app.findall("service")
    assert len(services) == 1
    assert services[0].get(ANDROID + "foregroundServiceType") == "specialUse"


def test_no_real_encoder_media_projection_or_shell_execution_in_fake_fixture() -> None:
    code = RECORDER.read_text()
    for forbidden in (
        "import android.",
        "MediaProjectionManager(",
        "MediaProjection(",
        "MediaRecorder(",
        "MediaCodec(",
        "VirtualDisplay(",
        "ImageReader(",
        "getMediaProjection(",
        "startActivity(",
        "Runtime.getRuntime(",
        "ProcessBuilder(",
        "Socket(",
        "ServerSocket(",
    ):
        assert forbidden not in code
