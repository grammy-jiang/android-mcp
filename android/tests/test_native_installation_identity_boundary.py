"""N6.a public identity backed by app Keystore but unpaired by default."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = "{http://schemas.android.com/apk/res/android}"
APP = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
KEYS = APP / "AndroidInstallationKeystoreProvider.kt"
BOUNDARY = APP / "AndroidInstallationIdentityBoundary.kt"
MODEL = ROOT / "android/native-lifecycle/src/main/kotlin/org/androidmcp/lifecycle/NativeInstallationIdentity.kt"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"
GATEWAY = APP / "LocalMcpGateway.kt"


def test_n6a_01_public_identity_has_no_hardware_id_or_signer_secret() -> None:
    source = MODEL.read_text()
    for expected in (
        "verification_key_sha256",
        "verification_key_spki_base64",
        "installation_id",
        "MessageDigest.getInstance(\"SHA-256\")",
        "KeyFactory.getInstance(\"EC\")",
        "SHA256withECDSA",
        "processEpoch",
    ):
        assert expected in source
    for forbidden in ("getSerial(", "getImei(", "ANDROID_ID", "WifiInfo", "MacAddress"):
        assert forbidden not in source


def test_n6a_02_private_no_backup_owner_lock_and_atomic_integrity() -> None:
    source = MODEL.read_text()
    assert '"native-mcp-install-identity"' in source
    assert '"installation.v1"' in source
    assert "FileChannel.open(" in source
    assert "tryLock()" in source
    assert "OverlappingFileLockException" in source
    assert "LinkOption.NOFOLLOW_LINKS" in source
    assert "StandardCopyOption.ATOMIC_MOVE" in source
    assert "output.force(true)" in source
    assert "NATIVE_ID_SIGNATURE_INVALID" in source
    assert "NATIVE_ID_KEY_MISMATCH" in source
    assert '"rw-------"' in source
    assert '"rwx------"' in source


def test_n6a_03_android_keystore_private_key_cannot_be_exported_as_bytes() -> None:
    source = KEYS.read_text()
    assert 'KeyStore.getInstance("AndroidKeyStore")' in source
    assert 'KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore"' in source
    assert "KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY" in source
    assert 'ECGenParameterSpec("secp256r1")' in source
    assert "PrivateKey" in source
    assert "Signature.getInstance(\"SHA256withECDSA\")" in source
    for forbidden in (
        ".private.encoded",
        "privateKey.encoded",
        "getEncoded()",
        "PKCS8EncodedKeySpec",
        "FileOutputStream(",
        "openOutputStream(",
        "android.util.Log",
        "Log.",
    ):
        assert forbidden not in source


def test_n6a_04_reboot_replay_and_data_clear_must_not_grant_pairing() -> None:
    source = MODEL.read_text()
    assert "pendingChallenge = null" in source
    assert "challengeIssuedAt" in source
    assert "challengeExpiresAt" in source
    assert "keys.deleteKey(KEY_ALIAS)" in source
    assert "keys.sign(KEY_ALIAS" in source
    assert "verifySignature(" in source
    assert "CHALLENGE_TTL_MS = 30_000L" in source


def test_n6a_05_default_android_mcp_registry_and_permissions_unchanged() -> None:
    boundary = BOUNDARY.read_text()
    assert '"pairing_enabled":false' in boundary
    assert '"mutation_enabled":false' in boundary
    gateway = GATEWAY.read_text()
    assert gateway.count("server.addTool(") == 1
    assert 'name = "device_status"' in gateway
    assert "AndroidInstallationKeystoreProvider" not in gateway
    assert "AndroidInstallationIdentityBoundary" not in gateway
    manifest = ET.parse(MANIFEST).getroot()
    assert {p.get(ANDROID + "name") for p in manifest.findall("uses-permission")} == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }
