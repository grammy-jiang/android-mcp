"""N0.c SDK-free regression coverage for disposable orientation E2E preflight."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts/smoke-native-orientation-emulator.py"
)
SPEC = importlib.util.spec_from_file_location("native_orientation_safety", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


@pytest.mark.parametrize(
    "serial",
    ["", "8971a7bf", "emulator-5; rm -rf /", "192.0.2.2:5555", "-s"],
)
def test_no_physical_device_can_pass_emulator_serial_preflight(
    serial: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        m.core, "verify_emulator", lambda *_: pytest.fail("unexpected emulator read")
    )
    with pytest.raises(ValueError):
        m.validate_target(serial, 36)


def test_api_mismatch_is_denied_before_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(m.core, "verify_emulator", lambda *_: None)
    commands: list[tuple[str, ...]] = []

    def read(_serial: str, *args: str) -> str:
        commands.append(args)
        return "33"

    monkeypatch.setattr(m.core, "adb", read)
    with pytest.raises(ValueError, match="Expected API"):
        m.validate_target("emulator-5554", 36)
    assert commands == [("shell", "getprop", "ro.build.version.sdk")]


def test_emulator_not_booted_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(m.core, "verify_emulator", lambda *_: None)

    def read(_serial: str, *args: str) -> str:
        return "36" if args[-1] == "ro.build.version.sdk" else "0"

    monkeypatch.setattr(m.core, "adb", read)
    with pytest.raises(ValueError, match="not boot complete"):
        m.validate_target("emulator-5554", 36)


@pytest.mark.parametrize(
    "dump",
    [
        "",
        "mCurrentOrientation=999",
        "mCurrentOrientation=0 mCurrentOrientation=1",
        "mCurrentOrientation=-1",
    ],
)
def test_unproven_display_rotation_is_not_accepted(
    dump: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(m.core, "adb", lambda *_: dump)
    with pytest.raises(AssertionError, match="prove one actual"):
        m.actual_orientation("emulator-5554")


def test_unknown_rotation_setting_fails_before_any_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(m.core, "adb", lambda *_: "bad-setting")
    with pytest.raises(ValueError, match="Unrecognized"):
        m.original_rotation_settings("emulator-5554")


def test_invalid_rotation_is_denied_before_adb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(m.core, "adb", lambda *_: pytest.fail("no ADB permitted"))
    for value in (-1, 4, 999):
        with pytest.raises(ValueError, match="unrecognized"):
            m.set_rotation("emulator-5554", value)


def test_rotation_restored_on_failed_emulator_acceptance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """After verified QEMU and successful APK install, any E2E failure cleans up."""
    apk = tmp_path / "local-test.apk"
    apk.write_bytes(b"0" * 10001)
    events: list[str] = []
    monkeypatch.setattr(m, "validate_target", lambda *_: events.append("preflight"))
    monkeypatch.setattr(m, "original_rotation_settings", lambda *_: ("1", "0"))
    monkeypatch.setattr(m, "actual_orientation", lambda *_: 0)
    monkeypatch.setattr(m.core, "free_local_port", lambda: 54321)
    monkeypatch.setattr(m.core, "click_start", lambda *_: None)

    def adb(_serial: str, *args: str, **_kwargs: object) -> str:
        events.append("adb:" + " ".join(args))
        if "install" in args:
            return "Success"
        return ""

    async def available(_endpoint: str) -> None:
        events.append("ready")

    def fail_rotation(_serial: str, _target: int) -> None:
        events.append("rotation-failed")
        raise RuntimeError("synthetic orientation failure")

    monkeypatch.setattr(m.core, "adb", adb)
    monkeypatch.setattr(m.core, "await_running", available)
    monkeypatch.setattr(m, "set_rotation", fail_rotation)
    monkeypatch.setattr(m, "restore_rotation", lambda *_: events.append("restored"))
    with pytest.raises(RuntimeError, match="synthetic orientation"):
        m.run("emulator-5554", 36, apk)

    assert events[0] == "preflight"
    assert "ready" in events
    assert events.index("rotation-failed") < events.index("restored")
    assert any("force-stop" in item for item in events)
    assert any("forward --remove" in item for item in events)
