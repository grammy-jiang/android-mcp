"""T-N4B-01..06 test-first, SDK-free safety assertions for Android AVD input."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts/smoke-native-ui-action-emulator.py"
)
SPEC = importlib.util.spec_from_file_location("n4b_ui_guard", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)

OWN = "org.androidmcp.nativeapp"
API_SERIALS = {
    30: "emulator-5560",
    33: "emulator-5558",
    34: "emulator-5556",
    36: "emulator-5554",
}
ABI = "arm64-v8a"
XML = """<?xml version="1.0" encoding="utf-8"?>
<hierarchy>
 <node package="org.androidmcp.nativeapp"
       class="android.widget.TextView"
       text="Android MCP Native — local preview"
       bounds="[20,20][900,80]"/>
 <node package="org.androidmcp.nativeapp"
       class="android.widget.TextView"
       text="Stopped. Read-only; no Root, UI control or remote listener."
       bounds="[20,90][900,160]"/>
 <node package="org.androidmcp.nativeapp"
       class="android.widget.Button" text="Start local read-only MCP"
       clickable="true" enabled="true"
       bounds="[50,180][600,280]"/>
 <node package="org.androidmcp.nativeapp"
       class="android.widget.Button" text="Open persistent service preview"
       clickable="true" enabled="true"
       bounds="[50,310][600,400]"/>
</hierarchy>"""


@pytest.mark.parametrize(
    "serial",
    ["", "rf45", "192.168.1.25:5555", "emulator-5554; reboot", "emulator-5554\n", "-s"],
)
def test_T_N4B_02_physical_or_unverified_serial_rejected_before_input(
    serial: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        m,
        "adb",
        lambda *_: commands.append(tuple(str(x) for x in _)) or "1",
        raising=False,
    )
    with pytest.raises((m.UiSafetyError, ValueError)):
        m.validate_target(serial, 36, ABI)
    assert not any("input" in a for a in commands)


@pytest.mark.parametrize("api,serial", API_SERIALS.items())
def test_T_N4B_01_exact_qemu_api_abi_and_boot_preflight_before_action(
    api: int,
    serial: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[str, ...]] = []

    def adb(_serial: str, *parts: str) -> str:
        commands.append(parts)
        assert _serial == serial
        return {
            ("get-state",): "device",
            ("shell", "getprop", "ro.kernel.qemu"): "1",
            ("shell", "getprop", "ro.build.version.sdk"): str(api),
            ("shell", "getprop", "ro.product.cpu.abi"): ABI,
            ("shell", "getprop", "sys.boot_completed"): "1",
        }[parts]

    monkeypatch.setattr(m, "adb", adb, raising=False)
    m.validate_target(serial, api, ABI)
    assert len(commands) >= 5
    assert not any("input" in part for parts in commands for part in parts)


def test_T_N4B_03_only_own_visible_button_bounded_tap_swipe_key_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proof = m.parse_owned_ui(XML, 0, 1080, 1920)
    assert proof.package == OWN
    assert proof.button_center == (325, 230)
    assert proof.state == "stopped"
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(m, "validate_target", lambda *_: None)

    def adb(serial: str, *args: str) -> str:
        assert serial == "emulator-5554"
        commands.append(args)
        return ""

    monkeypatch.setattr(m, "adb", adb, raising=False)
    for operation in ("tap", "swipe"):
        assert (
            m.guarded_input(
                "emulator-5554",
                36,
                ABI,
                proof,
                operation,
                lambda: proof,
            )
            == "sent"
        )
    running = replace(proof, state="running")
    assert (
        m.guarded_input(
            "emulator-5554",
            36,
            ABI,
            running,
            "key",
            lambda: running,
        )
        == "sent"
    )
    assert ("shell", "input", "tap", "325", "230") in commands
    assert any(cmd[:3] == ("shell", "input", "swipe") for cmd in commands)
    assert ("shell", "input", "keyevent", "KEYCODE_DPAD_DOWN") in commands
    assert all(cmd[0] == "shell" and cmd[1] == "input" for cmd in commands)


def test_T_N4B_04_changed_rotation_or_window_forbids_blind_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = m.parse_owned_ui(XML, 0, 1080, 1920)
    shifted = m.parse_owned_ui(XML, 1, 1080, 1920)
    changed = m.parse_owned_ui(
        XML.replace(
            "Stopped. Read-only; no Root, UI control or remote listener.",
            "Starting local-only MCP...",
        ),
        0,
        1080,
        1920,
    )
    monkeypatch.setattr(m, "validate_target", lambda *_: None)
    writes: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        m,
        "adb",
        lambda _serial, *parts: writes.append(parts),
        raising=False,
    )
    for stale in (shifted, changed):
        with pytest.raises(m.UiSafetyError):
            m.guarded_input(
                "emulator-5554",
                36,
                ABI,
                original,
                "tap",
                lambda snapshot=stale: snapshot,
            )
    assert writes == []


def test_T_N4B_05_input_timeout_reported_uncertain_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proof = m.parse_owned_ui(XML, 0, 1080, 1920)
    monkeypatch.setattr(m, "validate_target", lambda *_: None)
    calls = 0

    def timeout(_serial: str, *args: str) -> str:
        nonlocal calls
        calls += 1
        raise RuntimeError("Synthetic ADB disconnection after dispatch")

    monkeypatch.setattr(m, "adb", timeout, raising=False)
    assert (
        m.guarded_input(
            "emulator-5554",
            36,
            ABI,
            proof,
            "tap",
            lambda: proof,
        )
        == "uncertain"
    )
    assert calls == 1


def test_keyboard_interrupt_during_input_is_uncertain_and_never_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proof = m.parse_owned_ui(XML, 0, 1080, 1920)
    monkeypatch.setattr(m, "validate_target", lambda *_: None)
    attempts: list[tuple[str, ...]] = []

    def interrupted(_serial: str, *parts: str) -> str:
        attempts.append(parts)
        raise KeyboardInterrupt

    monkeypatch.setattr(m, "adb", interrupted)
    assert (
        m.guarded_input(
            "emulator-5554",
            36,
            ABI,
            proof,
            "tap",
            lambda: proof,
        )
        == "uncertain"
    )
    assert len(attempts) == 1


def test_T_N4B_06_cleanup_only_owned_application_on_preverified_emulator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(m, "validate_target", lambda *_: None)
    monkeypatch.setattr(
        m,
        "adb",
        lambda _serial, *parts: commands.append((str(_serial), *parts)),
        raising=False,
    )
    m.cleanup_app("emulator-5554", 36, ABI)
    assert commands == [
        ("emulator-5554", "shell", "am", "force-stop", OWN),
        ("emulator-5554", "shell", "rm", "-f", m.UI_PATH),
    ]


def test_reject_unowned_package_and_malformed_button_bounds() -> None:
    for xml in (
        XML.replace(OWN, "org.other.private"),
        XML.replace("[50,180][600,280]", "[12,-100][600,280]"),
        XML.replace("Start local read-only MCP", "Fake Android Settings"),
    ):
        with pytest.raises((m.UiSafetyError, ValueError)):
            m.parse_owned_ui(xml, 0, 1080, 1920)


MATRIX_SCRIPT = SCRIPT.parent / "verify_native_ui_action_matrix.py"
MATRIX_SPEC = importlib.util.spec_from_file_location(
    "n4b_ui_matrix_guard", MATRIX_SCRIPT
)
assert MATRIX_SPEC is not None and MATRIX_SPEC.loader is not None
matrix = importlib.util.module_from_spec(MATRIX_SPEC)
sys.modules[MATRIX_SPEC.name] = matrix
MATRIX_SPEC.loader.exec_module(matrix)


def test_all_qemu_api_abi_targets_preflighted_before_any_ui_input(
    tmp_path: Path,
) -> None:
    apk = tmp_path / "app-debug.apk"
    apk.write_bytes(b"0" * 10001)
    checked: list[tuple[str, tuple[str, ...]]] = []
    executed: list[list[str]] = []

    def reader(serial: str, *args: str) -> str:
        checked.append((serial, args))
        api = next(key for key, value in API_SERIALS.items() if value == serial)
        return {
            ("get-state",): "device",
            ("shell", "getprop", "ro.kernel.qemu"): "1",
            ("shell", "getprop", "ro.build.version.sdk"): str(api),
            ("shell", "getprop", "sys.boot_completed"): "1",
            ("shell", "getprop", "ro.product.cpu.abi"): ABI,
        }[args]

    def runner(argv: list[str], timeout: int, maxbytes: int) -> str:
        executed.append(argv)
        api = int(argv[argv.index("--expected-api") + 1])
        assert len(checked) == 20  # four APIs x four base reads plus one ABI
        assert timeout <= 240
        assert maxbytes <= 16_384
        return m.json.dumps(
            {
                "result": "pass",
                "api": api,
                "abi": ABI,
                "checks": [
                    "strict_qemu_api_abi_boot",
                    "owned_activity_tap",
                    "stale_owned_ui_denied",
                    "bounded_swipe",
                    "navigation_key",
                    "owned_state_remains",
                ],
                "target": "verified_emulator_only",
                "physical_android_used": False,
            }
        )

    result = matrix.run_matrix(API_SERIALS, ABI, apk, reader=reader, runner=runner)
    assert len(result) == 4
    assert len(executed) == 4
    assert all(
        argv[1].endswith("smoke-native-ui-action-emulator.py") for argv in executed
    )
    assert all("--serial" in argv and "--expected-api" in argv for argv in executed)


def test_one_wrong_qemu_abi_denies_whole_matrix_before_any_dispatch(
    tmp_path: Path,
) -> None:
    apk = tmp_path / "app-debug.apk"
    apk.write_bytes(b"0" * 10001)
    executed: list[list[str]] = []

    def reader(serial: str, *args: str) -> str:
        api = next(key for key, value in API_SERIALS.items() if value == serial)
        if args == ("shell", "getprop", "ro.product.cpu.abi"):
            return "x86_64" if api == 34 else ABI
        return {
            ("get-state",): "device",
            ("shell", "getprop", "ro.kernel.qemu"): "1",
            ("shell", "getprop", "ro.build.version.sdk"): str(api),
            ("shell", "getprop", "sys.boot_completed"): "1",
        }[args]

    with pytest.raises(matrix.UiMatrixError):
        matrix.run_matrix(
            API_SERIALS,
            ABI,
            apk,
            reader=reader,
            runner=lambda args, *_: executed.append(args) or "",
        )
    assert executed == []


def test_foreign_clickable_overlay_at_owned_button_or_swipe_region_is_denied() -> None:
    overlay_button = (
        '<node package="com.evil.overlay" class="android.widget.Button" '
        'clickable="true" bounds="[250,175][500,300]"/>'
    )
    overlay_swipe = (
        '<node package="com.evil.overlay" class="android.widget.Button" '
        'clickable="true" bounds="[0,700][30,1400]"/>'
    )
    for overlay in (overlay_button, overlay_swipe):
        with pytest.raises(m.UiSafetyError, match="overlay"):
            m.parse_owned_ui(
                XML.replace("</hierarchy>", overlay + "</hierarchy>"), 0, 1080, 1920
            )
    assert m.parse_owned_ui(XML, 0, 1080, 1920).state == "stopped"


def test_bad_or_ambiguous_foreign_overlay_coordinates_fail_closed() -> None:
    overlay = (
        '<node package="com.evil.overlay" clickable="true" bounds="not-a-bounds"/>'
    )
    with pytest.raises(m.UiSafetyError):
        m.parse_owned_ui(
            XML.replace("</hierarchy>", overlay + "</hierarchy>"), 0, 1080, 1920
        )


def test_ui_action_unknown_operation_never_dispatches() -> None:
    proof = m.parse_owned_ui(XML, 0, 1080, 1920)
    from unittest.mock import patch

    with (
        patch.object(m, "validate_target", return_value=None),
        patch.object(m, "adb") as fake_adb,
    ):
        with pytest.raises(m.UiSafetyError):
            m.guarded_input("emulator-5554", 36, ABI, proof, "shell", lambda: proof)
        fake_adb.assert_not_called()


def test_xml_dtd_or_entity_payload_fails_before_any_ui_action() -> None:
    for attack in (
        '<!DOCTYPE hierarchy [<!ENTITY leak "secret">]>' + XML,
        XML.replace(
            "<hierarchy>",
            "<!ENTITY hidden SYSTEM 'file:///data/private'>\\n<hierarchy>",
        ),
    ):
        with pytest.raises(m.UiSafetyError):
            m.parse_owned_ui(attack, 0, 1080, 1920)


def test_arbitrary_or_symlinked_apk_cannot_be_installed_even_on_emulator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    untrusted = tmp_path / "untrusted.apk"
    untrusted.write_bytes(b"x" * 10001)
    shortcut = tmp_path / "link.apk"
    shortcut.symlink_to(untrusted)
    monkeypatch.setattr(m, "validate_target", lambda *_: None)
    adb_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(m, "adb", lambda _serial, *args: adb_calls.append(args))
    for candidate in (untrusted, shortcut):
        with pytest.raises(m.UiSafetyError, match="owned Native debug APK"):
            m.run("emulator-5554", 36, ABI, candidate)
    assert adb_calls == []
