"""N6.b pairing challenge fake-only, no live host authentication shortcut."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
MODEL = ROOT / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol/NativePairingChallenge.kt"
BOUNDARY = APP / "AndroidPairingChallengeBoundary.kt"
GATEWAY = APP / "LocalMcpGateway.kt"
ANDROID = "{http://schemas.android.com/apk/res/android}"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"


def test_n6b_01_real_ecdsa_verification_bound_to_host_native_boot_digest() -> None:
    code = MODEL.read_text()
    assert "Signature.getInstance(\"SHA256withECDSA\")" in code
    assert "KeyFactory.getInstance(\"EC\")" in code
    assert '\"N6B2\"' in code
    assert "instanceId, bootEpoch, hostIdentity" in code
    assert "planDigest, nonce, now.toString()" in code
    assert "allowedOrigin" in code
    assert "FAKE_RECOGNIZED" in code


def test_n6b_02_replay_ttl_packet_limits_and_clock_rollback_denial() -> None:
    code = MODEL.read_text()
    for part in (
        "MAX_PENDING = 100",
        "MAX_PACKET = 1024",
        "TTL_MS = 15_000L",
        "pending.remove(nonce)",
        "clock() ?:",
        "now < pendingProof.issued",
        "now > pendingProof.expiry",
        "pending.clear()",
        "stopped = true",
    ):
        assert part in code


def test_n6b_03_origin_host_id_exact_and_no_model_boolean_approval() -> None:
    source = MODEL.read_text()
    assert 'allowedOrigin == "http://127.0.0.1:38765"' in source
    assert "proof.declaredOrigin != allowedOrigin" in source
    assert "proof.declaredHostId != hostIdentity" in source
    assert "proof.packet != pendingProof.packet" in source or "pendingProof.packet != proof.packet" in source
    for forbidden in ("fakeSignatureAccepted: Boolean", "approved: Boolean", "startActivity(", "ProcessBuilder("):
        assert forbidden not in source


def test_n6b_04_production_inert_no_host_route_or_secret_export() -> None:
    assert "PairingProofState.UNAVAILABLE" in BOUNDARY.read_text()
    code = MODEL.read_text()
    assert "fun productionPairingEnabled(): Boolean = false" in code
    assert "private_key" not in code
    assert "PKCS8EncodedKeySpec" not in code
    gateway = GATEWAY.read_text()
    assert gateway.count("server.addTool(") == 1
    assert 'name = "device_status"' in gateway
    assert "NativePairingChallenge" not in gateway
    assert "AndroidPairingChallengeBoundary" not in gateway


def test_n6b_05_manifest_remains_unprivileged_and_unpaired() -> None:
    manifest = ET.parse(MANIFEST).getroot()
    actual = {e.get(ANDROID + "name") for e in manifest.findall("uses-permission")}
    assert actual == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }
    assert manifest.findall("queries") == []
