"""Typed ADB command policy, including untrusted inputs and filesystem paths."""

import pytest

from android_mcp_host.command_plan import Plan, PlanError, prepare_action


def _ok(action, **kwargs):
    result = prepare_action(action, **kwargs)
    assert isinstance(result, Plan), result
    return result


def _bad(action, code, **kwargs):
    result = prepare_action(action, **kwargs)
    assert isinstance(result, PlanError), result
    assert result.code == code


def test_read_only_fixed_commands():
    plan = _ok({"type": "package_details", "package": "com.example.demo"})
    assert plan.argv_suffix == ("shell", "dumpsys", "package", "com.example.demo")
    assert plan.mutating is False
    logcat = _ok({"type": "logcat_snapshot", "lines": 15})
    assert logcat.argv_suffix == ("logcat", "-d", "-t", "15", "-v", "threadtime")
    assert logcat.timeout_s == 15.0
    assert _ok({"type": "logcat_snapshot"}).argv_suffix[3] == "200"


def test_instrument_component_contains_only_java_identifiers():
    plan = _ok(
        {
            "type": "instrument_test",
            "package": "com.example.tests",
            "runner": "androidx.test.runner.AndroidJUnitRunner",
        }
    )
    assert plan.argv_suffix == (
        "shell",
        "am",
        "instrument",
        "-w",
        "com.example.tests/androidx.test.runner.AndroidJUnitRunner",
    )
    assert plan.mutating is True
    assert plan.timeout_s == 120.0


@pytest.mark.parametrize("raw", [None, "shell", [], {}, {"type": 3}])
def test_rejects_non_action(raw):
    _bad(raw, "INVALID_ACTION")


@pytest.mark.parametrize("kind", ["shell", "root", "reboot", "force_stop", "logcat_live"])
def test_unregistered_commands_cannot_run(kind):
    _bad({"type": kind}, "UNKNOWN_OPERATION")


@pytest.mark.parametrize("value", [1, True, 9, 2001, "200", 15.5, None])
def test_bad_logcat_lines(value):
    _bad({"type": "logcat_snapshot", "lines": value}, "INVALID_ARGUMENTS")


@pytest.mark.parametrize(
    "action",
    [
        {"type": "logcat_snapshot", "shell": "id"},
        {"type": "package_details", "package": "com.example", "command": "reboot"},
        {"type": "package_details"},
        {"type": "instrument_test", "package": "com.example"},
        {"type": "instrument_test", "package": "com.example", "runner": "p.R", "root": True},
        {"type": "install_apk", "apk_path": "/tmp/x.apk", "force": True},
    ],
)
def test_unknown_keys_and_missing_required_args_are_rejected(action):
    _bad(action, "INVALID_ARGUMENTS")


@pytest.mark.parametrize(
    "name",
    [
        "evil;reboot",
        "com.example$(whoami)",
        "com.example other",
        "-s",
        "com..example",
        "com.example\nreboot",
        "com.example/xx",
        "com.example'",
        "0.example",
    ],
)
def test_rejects_remote_shell_metacharacters_in_package(name):
    _bad({"type": "package_details", "package": name}, "INVALID_PACKAGE")


@pytest.mark.parametrize(
    "runner",
    [
        "; reboot",
        "Runner",
        "x y",
        "com.test.Runner$(id)",
        "com.test.Outer$Inner",
        "x/y",
        "a.#b",
    ],
)
def test_rejects_remote_shell_metacharacters_in_runner(runner):
    _bad(
        {"type": "instrument_test", "package": "com.example.tests", "runner": runner},
        "INVALID_COMPONENT",
    )


def test_installer_whitelist_and_flags(tmp_path):
    root = tmp_path / "approved space"
    root.mkdir()
    apk = root / "test.apk"
    apk.write_bytes(b"PK\x03\x04payload")
    plan = _ok({"type": "install_apk", "apk_path": str(apk)}, allowed_apk_roots=(root,))
    assert plan.argv_suffix == ("install", "-r", str(apk))
    assert plan.mutating
    plan = _ok(
        {"type": "install_apk", "apk_path": str(apk), "replace": False, "allow_test": True},
        allowed_apk_roots=(root,),
    )
    assert plan.argv_suffix == ("install", "-t", str(apk))
    _bad({"type": "install_apk", "apk_path": str(apk)}, "APK_NOT_ALLOWED")


def test_installer_rejects_parent_symlink_escape_and_bad_file(tmp_path):
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outer_apk = outside / "outer.apk"
    outer_apk.write_bytes(b"PK\x03\x04payload")
    symlink = trusted / "external.apk"
    symlink.symlink_to(outer_apk)
    _bad(
        {"type": "install_apk", "apk_path": str(symlink)},
        "APK_NOT_ALLOWED",
        allowed_apk_roots=(trusted,),
    )
    parent = trusted / "linked"
    parent.symlink_to(outside, target_is_directory=True)
    _bad(
        {"type": "install_apk", "apk_path": str(parent / "outer.apk")},
        "APK_NOT_ALLOWED",
        allowed_apk_roots=(trusted,),
    )
    ordinary = trusted / "ordinary.apk"
    ordinary.write_text("not a zip")
    _bad(
        {"type": "install_apk", "apk_path": str(ordinary)},
        "INVALID_APK",
        allowed_apk_roots=(trusted,),
    )


@pytest.mark.parametrize("path", [None, "", "relative.apk", "/tmp/file.zip", "bad\x00.apk"])
def test_invalid_apk_paths(path):
    _bad({"type": "install_apk", "apk_path": path}, "INVALID_APK_PATH")


def test_missing_and_empty_apk(tmp_path):
    missing = tmp_path / "missing.apk"
    _bad(
        {"type": "install_apk", "apk_path": str(missing)},
        "INVALID_APK_PATH",
        allowed_apk_roots=(tmp_path,),
    )
    empty = tmp_path / "empty.apk"
    empty.touch()
    _bad(
        {"type": "install_apk", "apk_path": str(empty)},
        "INVALID_APK",
        allowed_apk_roots=(tmp_path,),
    )


@pytest.mark.parametrize("arg", [1, "true", None])
def test_invalid_apk_flags(tmp_path, arg):
    p = tmp_path / "demo.apk"
    p.write_bytes(b"PK\x03\x04not a real install file")
    _bad(
        {"type": "install_apk", "apk_path": str(p), "replace": arg},
        "INVALID_ARGUMENTS",
        allowed_apk_roots=(tmp_path,),
    )


def test_apk_directory_with_extension_is_not_accepted(tmp_path):
    directory = tmp_path / "directory.apk"
    directory.mkdir()
    _bad(
        {"type": "install_apk", "apk_path": str(directory)},
        "INVALID_APK_PATH",
        allowed_apk_roots=(tmp_path,),
    )


def test_packages_and_classes_have_reasonable_size_limits():
    _bad(
        {"type": "package_details", "package": "com." + "x" * 10000},
        "INVALID_PACKAGE",
    )
    _bad(
        {"type": "instrument_test", "package": "com.example", "runner": "com." + "x" * 10000},
        "INVALID_COMPONENT",
    )
