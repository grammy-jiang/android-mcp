"""Pure Python, no ADB, negative matrix tests for Native N3."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/verify_native_api_matrix.py"
SPEC = importlib.util.spec_from_file_location("native_api_matrix_harness", SCRIPT)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)
ASSIGNMENTS = {
    30: "emulator-5560",
    33: "emulator-5558",
    34: "emulator-5556",
    36: "emulator-5554",
}


@pytest.mark.parametrize(
    "target",
    [
        "",
        "8971a7bf",
        "192.168.50.134:5555",
        "emulator-5554; reboot",
        "emulator-1",
        "-s",
        "emulator-5554\n",
    ],
)
def test_reject_non_emulator_serials(target: str) -> None:
    a = dict(ASSIGNMENTS)
    a[30] = target
    with pytest.raises(m.MatrixSafetyError):
        m.validate_assignments(a)


def test_all_four_required_and_unique() -> None:
    m.validate_assignments(ASSIGNMENTS)
    with pytest.raises(m.MatrixSafetyError):
        m.validate_assignments({30: "emulator-5560"})
    a = dict(ASSIGNMENTS)
    a[33] = "emulator-5560"
    with pytest.raises(m.MatrixSafetyError):
        m.validate_assignments(a)


@pytest.mark.parametrize(
    "failure",
    [
        (33, "get-state", "offline"),
        (34, "ro.kernel.qemu", "0"),
        (36, "ro.build.version.sdk", "33"),
        (30, "sys.boot_completed", ""),
    ],
)
def test_every_target_is_verified_before_mutation(
    failure: tuple[int, str, str],
) -> None:
    fail_api, fail_arg, fail_result = failure
    seen = []

    def fake_read(serial: str, *args: str) -> str:
        seen.append((serial, args))
        current_api = next(api for api, value in ASSIGNMENTS.items() if value == serial)
        key = args[-1] if args else ""
        if current_api == fail_api and (
            key == fail_arg or fail_arg == "get-state" and args == ("get-state",)
        ):
            return fail_result
        if args == ("get-state",):
            return "device"
        return {
            "ro.kernel.qemu": "1",
            "ro.build.version.sdk": str(current_api),
            "sys.boot_completed": "1",
        }[key]

    with pytest.raises(m.MatrixSafetyError):
        m.verify_all_before_any_mutation(ASSIGNMENTS, fake_read)
    assert seen


def test_runner_checks_every_emulator_before_any_smoke(tmp_path: Path) -> None:
    apk = tmp_path / "app-debug.apk"
    apk.write_bytes(b"0" * 10001)
    events: list[str] = []

    def fake_adb(serial: str, *args: str) -> str:
        events.append("read:" + serial)
        if args == ("get-state",):
            return "device"
        if args[-1] == "ro.kernel.qemu":
            return "1"
        if args[-1] == "ro.build.version.sdk":
            return str(next(api for api, ser in ASSIGNMENTS.items() if ser == serial))
        return "1"

    def fake_run(command: list[str], timeout: int, limit: int) -> str:
        events.append("smoke:" + command[1])
        assert "--serial" in command and "--apk" in command
        assert timeout == 420 and limit == m.MAX_SMOKE_OUTPUT_BYTES
        return '{"result": "pass"}'

    result = m.run_matrix(ASSIGNMENTS, apk, fake_adb, fake_run)
    assert len(result) == 4
    assert sum(event.startswith("read:") for event in events) == 16
    assert events.index(next(x for x in events if x.startswith("smoke:"))) == 16
    assert sum(x.startswith("smoke:") for x in events) == 6


def test_supported_smoke_suites_by_version(tmp_path: Path) -> None:
    apk = tmp_path / "x.apk"
    assert [Path(s[1]).name for s in m.commands_for(30, "emulator-5560", apk)] == [
        "smoke-native-legacy-emulator.py"
    ]
    assert [Path(s[1]).name for s in m.commands_for(34, "emulator-5556", apk)] == [
        "smoke-native-emulator.py",
        "smoke-native-foreground-emulator.py",
    ]


def test_wrong_apk_rejected_before_adb(tmp_path: Path) -> None:
    apk = tmp_path / "incomplete.apk"
    apk.write_bytes(b"tiny")
    with pytest.raises(m.MatrixSafetyError, match="nonempty"):
        m.run_matrix(
            ASSIGNMENTS,
            apk,
            lambda *_: (_ for _ in ()).throw(AssertionError("ADB MUST NOT RUN")),
        )
