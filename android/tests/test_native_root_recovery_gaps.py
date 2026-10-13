"""N8.b: ordinary Native Android never executes privileged Root/ROM recovery."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = (
    ROOT
    / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol/NativeRootRecoveryGap.kt"
)
BOUNDARY = (
    ROOT
    / "android/app/src/main/java/org/androidmcp/nativeapp/AndroidRootRecoveryBoundary.kt"
)
GATEWAY = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp/LocalMcpGateway.kt"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"
ANDROID = "{http://schemas.android.com/apk/res/android}"


def test_n8b_01_root_bootloader_rom_unsupported_with_manual_host_gap_map() -> None:
    code = SRC.read_text()
    assert "RootRecoverySurface.ROOT, RootRecoverySurface.BOOTLOADER" in code
    assert "RootRecoverySurface.ROM_FLASH" in code
    assert "RootRecoveryState.UNSUPPORTED" in code
    assert "manualHostFallbackRequired = true" in code
    assert "val operationExecuted: Boolean = false" in code


def test_n8b_02_no_public_raw_adb_shell_fastboot_or_partition_tool() -> None:
    gateway = GATEWAY.read_text()
    assert gateway.count("server.addTool(") == 1
    assert 'name = "device_status"' in gateway
    assert "NativeRootRecoveryGap" not in gateway
    assert "AndroidRootRecoveryBoundary" not in gateway
    boundary = BOUNDARY.read_text()
    assert "fun nativePrivilegeAllowed(): Boolean = false" in boundary
    assert "RootRecoveryReceipt(RootRecoveryState.UNSUPPORTED)" in boundary


def test_n8b_03_unbootable_native_reports_unavailable_not_remote_recovered() -> None:
    code = SRC.read_text()
    assert "!environment.nativeBootable || !environment.nativeServiceOnline" in code
    assert "RootRecoveryState.UNAVAILABLE" in code
    assert 'put("operation_executed", false)' in code
    assert "Host read-only" not in code  # no executable Host calls


def test_n8b_04_missing_or_forged_host_and_adb_fastboot_rights_block() -> None:
    code = SRC.read_text()
    for marker in (
        "HOST_ID.matches(environment.hostId)",
        "!environment.hostIdentityVerified",
        "!environment.adbAuthorized",
        "!environment.fastbootAuthorized",
        "!environment.physicalOwnerPresent",
        "!environment.ownerConfirmed",
        "RootRecoveryState.BLOCKED",
    ):
        assert marker in code
    assert "if (environment.modelApproved)" not in code


def test_n8b_05_model_lock_bypass_erase_flash_shell_claims_denied() -> None:
    code = SRC.read_text()
    for token in (
        "RootRecoverySurface.RAW_SHELL",
        "RootRecoverySurface.UNLOCK_BOOTLOADER",
        "RootRecoverySurface.ERASE_USER_DATA",
        "RootRecoverySurface.LOCKSCREEN_BYPASS",
        "request.requestedCommand != null || request.bypassSecurity",
        "RootRecoveryState.DENIED",
    ):
        assert token in code


def test_n8b_06_manual_owner_confirmed_plan_without_any_executed_operation() -> None:
    code = SRC.read_text()
    for marker in (
        "Confirm physical device ownership",
        "Use a separately authenticated Host",
        "Consult official manufacturer recovery guidance",
        "requiresPhysicalOwnerConfirmation = true",
        "realRootOrFlashAllowed(): Boolean = false",
        'put("automatic_retry", false)',
    ):
        assert marker in code
    assert "requestedCommand =" not in BOUNDARY.read_text()
    for forbidden in (
        "ProcessBuilder(",
        "Runtime.getRuntime(",
        "executeShellCommand(",
        "startActivity(",
        "reboot(",
        "wipeData(",
        "flashPartition(",
    ):
        assert forbidden not in BOUNDARY.read_text()


def test_manifest_has_no_root_admin_or_boot_privilege_and_no_shell_dispatch() -> None:
    manifest = ET.parse(MANIFEST).getroot()
    permissions = {e.get(ANDROID + "name") for e in manifest.findall("uses-permission")}
    assert permissions == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }
    assert manifest.findall(".//receiver") == []
    assert 'android:sharedUserId="android.uid.system"' not in MANIFEST.read_text()
    assert "fun realRootOrFlashAllowed(): Boolean = false" in SRC.read_text()
