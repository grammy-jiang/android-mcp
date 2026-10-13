"""H3.a hostile metadata, path, process and localhost MCP acceptance."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from test_avd_inventory import AVD, fake_avd, runner_list

import android_mcp_host.avd_inventory as service
import android_mcp_host.avd_inventory_support as support
from android_mcp_host.command_runner import RunResult


def test_empty_inventory_is_valid_and_exact_target_missing_is_not_found(
    tmp_path: Path,
) -> None:
    root, binary = fake_avd(tmp_path)
    empty = service.AvdInventory(root, binary, runner=runner_list(""))
    assert empty.inspect()["status"] == "ok"
    assert empty.inspect()["avds"] == []
    assert empty.inspect(AVD)["status"] == "not_found"
    defined = service.AvdInventory(root, binary, runner=runner_list(f"{AVD}\n"))
    assert defined.inspect("unknown_valid_avd")["status"] == "not_found"


@pytest.mark.parametrize("root_name", ["relative", "/tmp/../not-trusted", "/" + "x" * 1200])
def test_constructor_rejects_untrusted_paths(root_name: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="operator-pinned"):
        service.AvdInventory(Path(root_name), tmp_path / "emulator")


@pytest.mark.parametrize("deadline", [0, -1, 6, True, "3", float("nan"), float("inf")])
def test_constructor_rejects_invalid_time_limits(deadline: Any, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="deadline"):
        service.AvdInventory(tmp_path / "avds", tmp_path / "emulator", timeout_s=deadline)


def test_schema_loader_does_not_accept_nonobject(monkeypatch: pytest.MonkeyPatch) -> None:
    class Resource:
        def joinpath(self, name: str) -> Resource:
            assert name == "host-avd-inventory.v1.schema.json"
            return self

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return "[]"

    monkeypatch.setattr(service, "files", lambda _: Resource())
    with pytest.raises(ValueError, match="Invalid Host AVD"):
        service.get_avd_output_schema()


def test_symlinked_nonexecutable_and_unowned_executable_never_launch(tmp_path: Path) -> None:
    root, binary = fake_avd(tmp_path)
    assert service.AvdInventory(root, binary, runner=runner_list(AVD)).inspect()["status"] == "ok"
    symlinked = binary.with_name("emulator-link")
    symlinked.symlink_to(binary)
    assert service.AvdInventory(root, symlinked).inspect()["status"] == "unavailable"
    binary.chmod(0o600)
    assert service.AvdInventory(root, binary).inspect()["status"] == "unavailable"
    binary.chmod(0o700)
    binary.write_bytes(b"")
    assert service.AvdInventory(root, binary).inspect()["status"] == "unavailable"


def test_owner_private_avd_directory_required(tmp_path: Path) -> None:
    root, binary = fake_avd(tmp_path)
    root.chmod(0o755)
    try:
        outcome = service.AvdInventory(root, binary, runner=runner_list(AVD)).inspect()
        assert outcome["status"] == "unavailable"
        assert outcome["errors"][0]["code"] == "AVD_ROOT_UNAVAILABLE"
    finally:
        root.chmod(0o700)


def test_list_adversarial_exit_stderr_cap_and_duplicate_casefold(tmp_path: Path) -> None:
    root, binary = fake_avd(tmp_path)
    candidates = (
        RunResult(1, AVD, "", False),
        RunResult(0, AVD, "SENSITIVE-SECRET", False),
        RunResult(0, AVD, "", True),
        RunResult(0, "\n".join(f"name{i}" for i in range(33)), "", False),
        RunResult(0, "Abc\nabc\n", "", False),
        RunResult(0, "evil\n..\n", "", False),
        RunResult(0, "X" * 8200, "", False),
    )
    for response in candidates:
        inventory = service.AvdInventory(root, binary, runner=lambda *args, v=response: v)
        result = inventory.inspect()
        assert result["status"] == "invalid"
        assert result["avds"] == []
        assert "SENSITIVE" not in json.dumps(result)


def test_list_probe_exceptions_are_generic_without_private_details(tmp_path: Path) -> None:
    root, binary = fake_avd(tmp_path)
    for error in (OSError("PRIVATE"), ValueError("SECRET"), RuntimeError("TOKEN")):

        def fail(*args: Any, caught=error) -> RunResult:
            raise caught

        result = service.AvdInventory(root, binary, runner=fail).inspect()
        assert result["status"] == "unavailable"
        assert result["errors"][0]["code"] == "EMULATOR_FAILED"
        assert "PRIVATE" not in json.dumps(result)
        assert "SECRET" not in json.dumps(result)


def test_ps_match_requires_pinned_binary_and_exact_avd_name(tmp_path: Path) -> None:
    root, binary = fake_avd(tmp_path)
    valid = str(binary.parent / "qemu/darwin-aarch64/qemu-system-aarch64-headless")
    assert (
        service._verified_process(RunResult(0, f"{valid} -avd {AVD}", "", False), binary, AVD)
        is True
    )
    assert (
        service._verified_process(RunResult(0, f"{binary} -avd {AVD}", "", False), binary, AVD)
        is True
    )
    for raw in (
        "/usr/bin/python -avd fixture_api36",
        f"{valid} -avd fixture_api360",
        f"{valid} -avd other",
        f"{valid}/../../private/qemu-system-evil -avd {AVD}",
        "emulator -avd fixture_api36",
        f"{valid} --avd {AVD}",
        "unterminated ' quote",
        "",
    ):
        assert not service._verified_process(RunResult(0, raw, "", False), binary, AVD)
    for value in (
        RunResult(1, f"{valid} -avd {AVD}", "", False),
        RunResult(0, f"{valid} -avd {AVD}", "", True),
        RunResult(0, "X" * 4100, "", False),
        RunResult(0, f"{valid} -avd {AVD}", "PRIVATE", False),
    ):
        assert not service._verified_process(value, binary, AVD)


def test_pid_lock_has_no_authority_to_kill_or_inspect_unrelated_process(
    tmp_path: Path,
) -> None:
    root, binary = fake_avd(tmp_path)
    requested: list[list[str]] = []

    def ps(argv: Any, limit: float, size: int) -> RunResult:
        requested.append(list(argv))
        raise OSError("SECRET process vanished")

    reader = service.AvdInventory(root, binary, runner=runner_list(AVD), process_runner=ps)
    assert reader.inspect()["avds"][0]["running_state"] == "stale_or_unverified"
    assert requested == [["/bin/ps", "-p", "12345", "-ww", "-o", "args="]]
    assert "kill" not in json.dumps(requested)


@pytest.mark.parametrize(
    "payload",
    [b"", b"0", b"-2", b"9999999999999", b"1abc", b"1\n2", b"x", b"1" * 40],
)
def test_invalid_stale_lock_pid_never_spawns_process_probe(tmp_path: Path, payload: bytes) -> None:
    root, binary = fake_avd(tmp_path, pid=payload)
    executed = [0]

    def forbidden(*args: Any) -> RunResult:
        executed[0] += 1
        raise AssertionError("Unexpected process probe")

    reader = service.AvdInventory(root, binary, runner=runner_list(AVD), process_runner=forbidden)
    assert reader.inspect()["avds"][0]["running_state"] == "stale_or_unverified"
    assert executed == [0]


def test_private_ini_parser_rejects_unsafe_encoding_duplicates_and_delimiters() -> None:
    invalid = (
        None,
        b"\xff",
        b"key=\x00injection\n",
        b"abc\n",
        b"bad/name=value\n",
        b"foo=one\nfoo=two\n",
        b"x=" + b"a" * 1025 + b"\n",
        b"\x01bad=1\n",
    )
    for value in invalid:
        assert support.parse_ini(value) is None
    assert support.parse_ini(b"# comment\n; extra\nfoo = bar\n") == {"foo": "bar"}


def test_private_file_reader_refuses_symlink_hardlink_empty_and_large(tmp_path: Path) -> None:
    original = tmp_path / "cfg"
    original.write_bytes(b"abc")
    assert support.read_private(original, 3) == b"abc"
    assert support.read_private(original, 2) is None
    alias = tmp_path / "alias"
    alias.symlink_to(original)
    assert support.read_private(alias) is None
    second = tmp_path / "second"
    os.link(original, second)
    assert support.read_private(original) is None
    second.unlink()
    original.write_bytes(b"")
    assert support.read_private(original) is None
    assert support.read_private(tmp_path / "missing") is None
    assert support.read_private(tmp_path) is None


def test_avd_config_api_abi_path_and_image_validation(tmp_path: Path) -> None:
    root, binary = fake_avd(tmp_path)
    parent = root / f"{AVD}.avd"
    ini = root / f"{AVD}.ini"
    config = parent / "config.ini"
    original_ini = ini.read_text()
    original_cfg = config.read_text()
    variants = (
        (original_ini.replace("android-36", "android-3"), original_cfg),
        (original_ini.replace("android-36", "android-41"), original_cfg),
        (original_ini.replace("target=android-36", "target=wrong"), original_cfg),
        (original_ini.replace(f"path={parent}", "path=/etc/passwd"), original_cfg),
        (original_ini, original_cfg.replace("AvdId=fixture_api36", "AvdId=other")),
        (original_ini, original_cfg.replace("abi.type=arm64-v8a", "abi.type=unsafe")),
        (original_ini, original_cfg.replace("system-images/android-36/", "other-images/")),
        (original_ini, original_cfg.replace("target=android-36", "target=android-33")),
        (original_ini, original_cfg.replace("hw.cpu.arch=arm64", "hw.cpu.arch=x86")),
    )
    for root_text, config_text in variants:
        ini.write_text(root_text)
        config.write_text(config_text)
        assert (
            service.AvdInventory(root, binary, runner=runner_list(AVD)).inspect()["status"]
            == "partial"
        )
    ini.write_text(original_ini)
    config.write_text(original_cfg)
    assert service.AvdInventory(root, binary, runner=runner_list(AVD)).inspect()["status"] == "ok"


def test_snapshot_inventory_missing_empty_invalid_version_and_symlink(tmp_path: Path) -> None:
    root, _ = fake_avd(tmp_path)
    path = root / f"{AVD}.avd"
    snapshot_root = path / "snapshots"
    shutil.rmtree(snapshot_root)
    assert support.snapshot_inventory(path) == (0, "none")
    snapshot_root.mkdir(mode=0o700)
    assert support.snapshot_inventory(path) == (0, "none")
    first = snapshot_root / "manual"
    first.mkdir(mode=0o700)
    assert support.snapshot_inventory(path) == (1, "present_unverified")
    version = first / "snapshot.version"
    for bad in (b"0", b"-1", b"101", b"not-a-number", b"9" * 40):
        version.write_bytes(bad)
        assert support.snapshot_inventory(path) is None
    version.write_bytes(b"2\n")
    assert support.snapshot_inventory(path) == (1, "present_unverified")
    version.unlink()
    version.symlink_to(path / "config.ini")
    assert support.snapshot_inventory(path) is None
    version.unlink()
    shutil.rmtree(snapshot_root)
    snapshot_root.symlink_to(tmp_path / "outside", target_is_directory=True)
    assert support.snapshot_inventory(path) is None
    snapshot_root.unlink()
    snapshot_root.mkdir(mode=0o700)
    for n in range(20):
        (snapshot_root / f"extra{n}").mkdir(mode=0o700)
    assert support.snapshot_inventory(path) is None


def test_invalid_metadata_name_and_root_fail_before_disk_reads(tmp_path: Path) -> None:
    root, _ = fake_avd(tmp_path)
    assert support.avd_metadata(root, "../untrusted") == (None, None)
    assert support.avd_metadata(tmp_path / "absent", AVD) == (None, None)
    linked_root = tmp_path / "avds-link"
    linked_root.symlink_to(root, target_is_directory=True)
    assert support.avd_metadata(linked_root, AVD) == (None, None)


def test_metadata_partial_valid_and_bad_entries_without_private_paths(tmp_path: Path) -> None:
    root, binary = fake_avd(tmp_path)
    (root / "broken_api36.avd").mkdir(mode=0o700)
    outcome = service.AvdInventory(
        root, binary, runner=runner_list(AVD + "\nbroken_api36\n")
    ).inspect()
    assert outcome["status"] == "partial"
    assert len(outcome["avds"]) == 1
    assert outcome["errors"][0]["code"] == "METADATA_INVALID"
    assert str(tmp_path) not in json.dumps(outcome)


def test_default_runner_uses_fixed_args_and_local_avd_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, binary = fake_avd(tmp_path, pid=None)
    calls: list[tuple[list[str], dict[str, str]]] = []

    def bounded(argv: Any, seconds: float, budget: int, *, env: dict[str, str]) -> RunResult:
        calls.append((list(argv), env))
        return RunResult(0, AVD + "\n", "", False)

    with monkeypatch.context() as scoped:
        scoped.setattr(service, "bounded_run", bounded)
        result = service.AvdInventory(root, binary).inspect()
    assert result["status"] == "ok"
    assert calls[0][0] == [str(binary), "-list-avds"]
    assert calls[0][1]["ANDROID_AVD_HOME"] == str(root)
    assert calls[0][1]["ANDROID_SDK_ROOT"] == str(binary.parent.parent)
    assert calls[0][1]["PATH"] == "/usr/bin:/bin"


def test_real_localhost_mcp_avd_tool_never_starts_an_emulator(tmp_path: Path) -> None:
    root, binary = fake_avd(tmp_path, pid=None)
    trace = tmp_path / "trace.txt"
    binary.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{trace}"\nprintf "%s\\n" "{AVD}"\n',
        encoding="utf-8",
    )
    binary.chmod(0o700)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    program = (
        "import sys\nfrom pathlib import Path\n"
        "from android_mcp_host.avd_inventory import AvdInventory\n"
        "from android_mcp_host.server import create_server\n"
        "root=Path(sys.argv[1]); binary=Path(sys.argv[2]); port=int(sys.argv[3])\n"
        "create_server(avd_inventory=AvdInventory(root,binary)).run("
        "transport='http',host='127.0.0.1',port=port)\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", program, str(root), str(binary), str(port)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def check() -> None:
        previous: Exception | None = None
        for _ in range(50):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    response = await client.call_tool("host_avd_inventory", {"name": AVD})
                    assert not response.is_error
                    result = response.structured_content
                    assert result["status"] == "ok"
                    assert result["avds"][0]["name"] == AVD
                    assert str(tmp_path) not in json.dumps(result)
                    return
            except (OSError, RuntimeError) as error:
                previous = error
                await asyncio.sleep(0.1)
        raise AssertionError(f"Read-only HTTP AVD check failed: {type(previous).__name__}")

    try:
        asyncio.run(check())
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    assert trace.read_text(encoding="utf-8").splitlines() == ["-list-avds"]


def test_cli_avd_inventory_is_opt_in_and_operator_scope_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from android_mcp_host import cli

    calls: list[dict[str, Any]] = []

    class Stub:
        def run(self, **kwargs: Any) -> None:
            assert kwargs == {"transport": "http", "host": "127.0.0.1", "port": 8765}

    def factory(**kwargs: Any) -> Stub:
        calls.append(kwargs)
        return Stub()

    with monkeypatch.context() as patch:
        patch.setattr(cli, "create_server", factory)
        patch.setattr(cli.platform, "system", lambda: "Darwin")
        assert cli.main(["serve"]) == 0
        assert calls == [{}]
        calls.clear()
        for argv in (
            ["serve", "--avd-root", str(tmp_path / "avds")],
            ["serve", "--avd-emulator", str(tmp_path / "emulator")],
            ["serve", "--avd-inventory", "--avd-root", "relative/avds"],
            ["serve", "--avd-inventory", "--avd-emulator", "./relative-emulator"],
        ):
            with pytest.raises(SystemExit) as result:
                cli.main(argv)
            assert result.value.code == 2
            assert calls == []
        assert cli.main(["serve", "--avd-inventory"]) == 0
        assert isinstance(calls[0]["avd_inventory"], service.AvdInventory)
        calls.clear()
        assert (
            cli.main(
                [
                    "serve",
                    "--avd-inventory",
                    "--avd-root",
                    str(tmp_path / "avds"),
                    "--avd-emulator",
                    str(tmp_path / "pinned-emulator"),
                ]
            )
            == 0
        )
        assert calls[0]["avd_inventory"].inspect()["status"] == "unavailable"
    assert not (tmp_path / "avds").exists()
