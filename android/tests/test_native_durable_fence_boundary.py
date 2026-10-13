"""N6.c stable high-water, owner lock and no public mutation executor."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = "{http://schemas.android.com/apk/res/android}"
APP = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
MODEL = ROOT / "android/native-lifecycle/src/main/kotlin/org/androidmcp/lifecycle/NativeFenceState.kt"
BOUNDARY = APP / "AndroidFenceBoundary.kt"
GATEWAY = APP / "LocalMcpGateway.kt"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"


def test_n6c_01_durable_high_water_and_monotonic_signed_fixture() -> None:
    source = MODEL.read_text()
    for fragment in (
        '"native-mcp-fencing"',
        '"fence.v1"',
        "request.fence <= water",
        "water = request.fence",
        "request.fakeHostProofAccepted",
        "request.planDigest in digests",
        "nonceDigest in nonces",
        "SHA-256",
    ):
        assert fragment in source


def test_n6c_02_atomic_private_persistence_before_recognition() -> None:
    code = MODEL.read_text()
    assert "FileChannel.open(" in code
    assert "tryLock()" in code
    assert "OverlappingFileLockException" in code
    assert "output.force(true)" in code
    assert "StandardCopyOption.ATOMIC_MOVE" in code
    assert "LinkOption.NOFOLLOW_LINKS" in code
    assert 'PosixFilePermissions.fromString("rwx------")' in code
    assert 'PosixFilePermissions.fromString("rw-------")' in code
    assert "if (!persist(" in code
    assert "return result(FenceStatus.UNCERTAIN)" in code


def test_n6c_03_reinstall_boot_clock_rollback_and_wrong_host_denied() -> None:
    code = MODEL.read_text()
    for condition in (
        "storedInstall != nativeInstallation",
        "storedBoot != bootEpoch",
        "storedHost != hostIdentity",
        "request.nativeInstallation != nativeInstallation",
        "request.bootEpoch != bootEpoch",
        "request.hostIdentity != hostIdentity",
        "current < latestElapsed",
        "FenceStatus.PAIRING_REQUIRED",
        "FenceStatus.CLOCK_ROLLBACK",
    ):
        assert condition in code


def test_n6c_04_limits_and_error_metadata_never_include_identity() -> None:
    code = MODEL.read_text()
    assert "MAX_REMEMBERED = 32" in code
    assert "MAX_FILE_BYTES = 8192" in code
    assert "MAX_TTL_MS = 30_000L" in code
    assert "override fun toString()" in code
    assert "mutation_executed" in code
    assert "fun realMutationAllowed(): Boolean = false" in code


def test_n6c_05_live_android_bridge_default_denied_not_a_grant() -> None:
    code = BOUNDARY.read_text()
    assert "FenceReceipt(FenceStatus.DENIED, null)" in code
    assert "internal object AndroidFenceBoundary" in code
    for forbidden in (
        "startActivity(",
        "startService(",
        "PackageInstaller(",
        "dispatchGesture(",
        "ContentResolver(",
        "Runtime.getRuntime(",
        "ProcessBuilder(",
    ):
        assert forbidden not in code
    live = GATEWAY.read_text()
    assert live.count("server.addTool(") == 1
    assert 'name = "device_status"' in live
    assert "AndroidFenceBoundary" not in live


def test_n6c_06_permissions_and_schema_unchanged() -> None:
    root = ET.parse(MANIFEST).getroot()
    assert {p.get(ANDROID + "name") for p in root.findall("uses-permission")} == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }
    assert root.findall("queries") == []
