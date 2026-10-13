"""N7.b no physical install; owned-emulator user-consent work is blocked honestly."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from check_native_installer_consent_readiness import inspect_consent_readiness
from verify_native_api_matrix import MatrixSafetyError

POLICY = (
    ROOT
    / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol/NativeInstallerConsentSafety.kt"
)
BOUNDARY = (
    ROOT
    / "android/app/src/main/java/org/androidmcp/nativeapp/AndroidInstallerConsentBoundary.kt"
)
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"
GATEWAY = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp/LocalMcpGateway.kt"
READINESS = ROOT / "scripts/check_native_installer_consent_readiness.py"
ANDROID = "{http://schemas.android.com/apk/res/android}"
APIS = {
    30: "emulator-5560",
    33: "emulator-5558",
    34: "emulator-5556",
    36: "emulator-5554",
}


def fake_reader(*args: str) -> str:
    serial, *rest = args
    assert serial in APIS.values()
    expected = next(api for api, value in APIS.items() if value == serial)
    if rest == ["get-state"]:
        return "device"
    if rest == ["shell", "getprop", "ro.kernel.qemu"]:
        return "1"
    if rest == ["shell", "getprop", "ro.build.version.sdk"]:
        return str(expected)
    if rest == ["shell", "getprop", "sys.boot_completed"]:
        return "1"
    raise AssertionError(f"Unsafe/unexpected ADB read request: {rest!r}")


def test_n7b_01_real_consent_is_blocked_not_falsely_counted_as_opened() -> None:
    receipt = inspect_consent_readiness(APIS, fake_reader)
    assert receipt["result"] == "blocked"
    assert receipt["real_consent_ui_opened"] is False
    assert receipt["installation_attempted"] is False
    assert "NativeInstallerConsentStatus.BLOCKED" in POLICY.read_text()
    assert (
        "FakeInstallerConsentReceipt(NativeInstallerConsentStatus.BLOCKED)"
        in BOUNDARY.read_text()
    )


def test_n7b_02_refusal_cancel_behaviors_are_inert_fixtures_only() -> None:
    policy = POLICY.read_text()
    for marker in (
        "NativeInstallerConsentStatus.REFUSED",
        "NativeInstallerConsentStatus.CANCELLED",
        "NativeInstallerConsentStatus.ABANDONED",
        "val installed = false",
        "val consentUiOpened = false",
        "val sessionOpened = false",
    ):
        assert marker in policy
    assert "val installed = true" not in policy


def test_n7b_03_invalid_physical_or_mismatched_serial_fails_before_mutation() -> None:
    with pytest.raises(MatrixSafetyError):
        inspect_consent_readiness({**APIS, 36: "R3CT505P6EK"}, fake_reader)
    with pytest.raises(MatrixSafetyError):
        inspect_consent_readiness({**APIS, 36: APIS[34]}, fake_reader)

    def bad_qemu(serial: str, *args: str) -> str:
        if args == ("shell", "getprop", "ro.kernel.qemu"):
            return "0"
        return fake_reader(serial, *args)

    with pytest.raises(MatrixSafetyError):
        inspect_consent_readiness(APIS, bad_qemu)


def test_n7b_04_death_stop_and_foreground_revocation_fail_closed() -> None:
    policy = POLICY.read_text()
    assert "request.ownActivityForeground" in policy
    assert "request.visibleOwnerGesture" in policy
    assert "NativeInstallerConsentStatus.STOPPED" in policy
    assert "NativeInstallerConsentStatus.ABANDONED" in policy
    assert "fun activeSessions(): Int = 0" in policy
    assert "fun realInstallerEnabled(): Boolean = false" in policy


def test_n7b_05_four_api_real_only_readiness_status_is_blocked() -> None:
    out = inspect_consent_readiness(APIS, fake_reader)
    assert out["api_levels_verified"] == [30, 33, 34, 36]
    assert out["result"] == "blocked"
    assert out["package_installed"] is False
    assert out["physical_device_touched"] is False
    text = READINESS.read_text()
    for forbidden in (
        '"install"',
        '"push"',
        '"am"',
        '"start"',
        '"grant"',
        '"shell", "pm"',
    ):
        assert forbidden not in text


def test_n7b_06_no_real_packageinstaller_permission_or_public_mutation_tool() -> None:
    root = ET.parse(MANIFEST).getroot()
    permissions = {
        node.get(ANDROID + "name") for node in root.findall("uses-permission")
    }
    assert permissions == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }
    gateway = GATEWAY.read_text()
    assert gateway.count("server.addTool(") == 1
    assert 'name = "device_status"' in gateway
    assert "AndroidInstallerConsentBoundary" not in gateway
    assert "fun realConsentUiEnabled(): Boolean = false" in BOUNDARY.read_text()
    assert "fun activeSessions(): Int = 0" in BOUNDARY.read_text()


def test_synthetic_ready_probe_is_side_effect_free() -> None:
    calls: list[tuple[str, ...]] = []

    def audit(*args: str) -> str:
        calls.append(args)
        return fake_reader(*args)

    result = inspect_consent_readiness(APIS, audit)
    assert result["result"] == "blocked"
    assert len(calls) == 16
    assert all(
        c[1:]
        in (
            ("get-state",),
            ("shell", "getprop", "ro.kernel.qemu"),
            ("shell", "getprop", "ro.build.version.sdk"),
            ("shell", "getprop", "sys.boot_completed"),
        )
        for c in calls
    )
    assert not any("install" in " ".join(c) for c in calls)
