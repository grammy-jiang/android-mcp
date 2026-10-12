"""H0.b: fixed Host CLI inventory, adversarial subprocesses, and MCP wire gates.

All executable fixtures live in pytest tmp_path. No connected Android device,
SDK installer, license flow, or actual mutating command is invoked.
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator

from android_mcp_host.command_runner import OutputLimitExceeded, RunResult, bounded_run
from android_mcp_host.server import create_server

IDS = ("adb", "fastboot", "java", "gradle", "sdk")
VERSIONS = {
    "adb": "37.0.1",
    "fastboot": "37.0.1",
    "java": "17.0.20",
    "gradle": "9.6",
}
SYNTHETIC_OUTPUT = {
    "adb": RunResult(0, "Android Debug Bridge version 1.0.41\nVersion 37.0.1\n", "", False),
    "fastboot": RunResult(0, "fastboot version 37.0.1\n", "", False),
    "java": RunResult(0, "", 'openjdk version "17.0.20" 2026-10-01\n', False),
    "gradle": RunResult(0, "\nGradle 9.6\n", "", False),
}


def _bin(tmp_path: Path, name: str, executable: bool = True) -> Path:
    location = tmp_path / "trusted" / name
    location.parent.mkdir(exist_ok=True)
    location.write_text("#!/usr/bin/env python3\nprint('fixture')\n", encoding="utf-8")
    location.chmod(0o700 if executable else 0o600)
    return location


def _sdk(tmp_path: Path, api: int = 36) -> Path:
    root = tmp_path / "sdk"
    platform = root / "platforms" / f"android-{api}"
    platform.mkdir(parents=True)
    (platform / "android.jar").write_bytes(b"fixture Android SDK platform")
    return root


class FakeRunner:
    def __init__(self, replies: dict[str, RunResult | BaseException]) -> None:
        self.replies = replies
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str], timeout_s: float, byte_limit: int) -> RunResult:
        self.calls.append(list(argv))
        assert timeout_s <= 5
        assert byte_limit == 65536
        response = self.replies[Path(argv[0]).name]
        if isinstance(response, BaseException):
            raise response
        return response


def _inventory(paths: dict[str, Path], sdk_root: Path, runner: Callable[..., RunResult]) -> Any:
    # Import inside the test so a red integration assertion can be demonstrated
    # even before the production module is first introduced.
    from android_mcp_host.toolchain_inventory import ToolchainInventory

    return ToolchainInventory(paths=paths, sdk_root=sdk_root, runner=runner)


def _tool(result: dict[str, Any], name: str) -> dict[str, Any]:
    assert result["schema_version"] == 1 and result["runtime"] == "host"
    assert set(result["tools"]) == set(IDS)
    return result["tools"][name]


def test_t_h0b_01_synthetic_mac_installed_toolchain_reports_exact_versions(
    tmp_path: Path,
) -> None:
    paths = {name: _bin(tmp_path, name) for name in VERSIONS}
    runner = FakeRunner(SYNTHETIC_OUTPUT)
    result = _inventory(paths, _sdk(tmp_path), runner).inspect()
    assert result["status"] == "ok"
    for name, version in VERSIONS.items():
        assert _tool(result, name) == {
            "available": True,
            "runnable": True,
            "version": version,
            "reason": "OK",
        }
    assert _tool(result, "sdk") == {
        "available": True,
        "runnable": True,
        "version": "36",
        "reason": "OK",
    }
    assert runner.calls == [
        [str(paths["adb"]), "version"],
        [str(paths["fastboot"]), "--version"],
        [str(paths["java"]), "-version"],
        [str(paths["gradle"]), "--version"],
    ]


def test_t_h0b_02_synthetic_pi_is_partial_without_java_sdk_gradle(
    tmp_path: Path,
) -> None:
    paths = {"adb": _bin(tmp_path, "adb"), "fastboot": _bin(tmp_path, "fastboot")}
    runner = FakeRunner(
        {
            "adb": RunResult(0, "Version 34.0.5\n", "", False),
            "fastboot": RunResult(0, "fastboot version 34.0.5\n", "", False),
        }
    )
    result = _inventory(paths, tmp_path / "absent-sdk", runner).inspect()
    assert result["status"] == "partial"
    assert _tool(result, "adb")["version"] == "34.0.5"
    assert _tool(result, "fastboot")["version"] == "34.0.5"
    for name in ("java", "gradle", "sdk"):
        assert _tool(result, name) == {
            "available": False,
            "runnable": False,
            "version": None,
            "reason": "NOT_INSTALLED",
        }
    assert len(runner.calls) == 2


def test_t_h0b_03_missing_nonexecutable_permission_and_malformed_are_distinct(
    tmp_path: Path,
) -> None:
    paths = {
        "adb": tmp_path / "no-adb",
        "fastboot": _bin(tmp_path, "fastboot", executable=False),
        "java": _bin(tmp_path, "java"),
        "gradle": _bin(tmp_path, "gradle"),
    }
    runner = FakeRunner(
        {
            "java": PermissionError("fictional secret path"),
            "gradle": RunResult(0, "Gradle ??\n", "", False),
        }
    )
    result = _inventory(paths, tmp_path / "absent-sdk", runner).inspect()
    assert _tool(result, "adb")["reason"] == "NOT_INSTALLED"
    assert _tool(result, "fastboot")["reason"] == "NOT_EXECUTABLE"
    assert _tool(result, "java")["reason"] == "PERMISSION_DENIED"
    assert _tool(result, "gradle")["reason"] == "MALFORMED_VERSION"
    assert {s["runnable"] for s in result["tools"].values()} == {False}
    assert result["status"] == "unavailable"
    assert runner.calls == [[str(paths["java"]), "-version"], [str(paths["gradle"]), "--version"]]
    assert "fictional secret" not in str(result)


def test_t_h0b_04_hostile_path_cannot_shadow_fixed_binary_or_add_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trusted = _bin(tmp_path, "adb")
    hostile = tmp_path / "hostile"
    hostile.mkdir()
    (hostile / "adb").write_text("#!/bin/sh\necho ATTACK\n", encoding="utf-8")
    (hostile / "adb").chmod(0o700)
    monkeypatch.setenv("PATH", str(hostile) + os.pathsep + os.environ.get("PATH", ""))
    runner = FakeRunner({"adb": SYNTHETIC_OUTPUT["adb"]})
    inventory = _inventory({"adb": trusted}, tmp_path / "absent-sdk", runner)
    assert _tool(inventory.inspect(), "adb")["version"] == "37.0.1"
    assert runner.calls == [[str(trusted), "version"]]
    assert not any(str(hostile) in str(call) for call in runner.calls)
    # Caller has no executable override; even hostile process environment
    # must not appear in a returned response.
    assert str(hostile) not in str(inventory.inspect())


def test_t_h0b_05_timeout_exit_output_limit_and_child_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = {name: _bin(tmp_path, name) for name in VERSIONS}
    runner = FakeRunner(
        {
            "adb": subprocess.TimeoutExpired([str(paths["adb"]), "version"], 0.1),
            "fastboot": OutputLimitExceeded("secret-filled, over limit"),
            "java": RunResult(18, "", "credential=value", False),
            "gradle": RunResult(0, "z" * 70000, "", True),
        }
    )
    result = _inventory(paths, tmp_path / "absent-sdk", runner).inspect()
    assert [_tool(result, name)["reason"] for name in VERSIONS] == [
        "TIMEOUT",
        "OUTPUT_LIMIT",
        "NONZERO_EXIT",
        "OUTPUT_LIMIT",
    ]
    assert "credential=value" not in str(result)
    assert "secret-filled" not in str(result)
    assert result["status"] == "unavailable"

    # Demonstrate actual 64 KiB subprocess kill/reap, not just an exception fake.
    real_popen = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []

    def track(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        child: subprocess.Popen[bytes] = real_popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", track)
    flooded = bounded_run(
        [sys.executable, "-c", "import os,time;os.write(1,b'x'*100000);time.sleep(8)"],
        2.0,
        65536,
    )
    assert flooded.truncated and flooded.returncode != 0
    assert len(flooded.stdout.encode()) + len(flooded.stderr.encode()) <= 65536
    assert len(children) == 1 and children[0].poll() is not None
    with pytest.raises(ProcessLookupError):
        os.killpg(children[0].pid, 0)


def test_t_h0b_06_opt_in_tool_real_mcp_schema_annotations_http_and_legacy_stability(
    tmp_path: Path,
) -> None:
    # The explicit opt-in preserves H0.a's default three-tool golden snapshot.
    # This injected fake deliberately avoids importing the new adapter, so the
    # test first fails on the absent *public registration contract*, not import.
    class StubInventory:
        def inspect(self) -> dict[str, object]:
            return {
                "schema_version": 1,
                "runtime": "host",
                "status": "partial",
                "tools": {
                    name: {
                        "available": name == "adb",
                        "runnable": name == "adb",
                        "version": "37.0.1" if name == "adb" else None,
                        "reason": "OK" if name == "adb" else "NOT_INSTALLED",
                    }
                    for name in IDS
                },
            }

    async def check() -> None:
        async with Client(create_server()) as baseline:
            original = {t.name: t for t in await baseline.list_tools()}
        assert set(original) == {"device_status", "adb_observe", "adb_develop"}
        async with Client(create_server(toolchain_inventory=StubInventory())) as client:  # type: ignore[call-arg]
            catalog = {t.name: t for t in await client.list_tools()}
            assert set(catalog) == {*original, "host_toolchain_inventory"}
            for name, before in original.items():
                after = catalog[name]
                assert (
                    before.title,
                    before.description,
                    before.annotations,
                    before.input_schema,
                    before.output_schema,
                ) == (
                    after.title,
                    after.description,
                    after.annotations,
                    after.input_schema,
                    after.output_schema,
                )
            tool = catalog["host_toolchain_inventory"]
            assert tool.input_schema.get("required", []) == []
            assert not tool.input_schema.get("properties")
            assert tool.output_schema is not None
            assert tool.output_schema["$id"] == "urn:android-mcp:host-toolchain-inventory:v1"
            assert tool.annotations is not None
            hints = tool.annotations.model_dump(mode="json", by_alias=True)
            assert hints["readOnlyHint"] is False  # version probes may affect Host caches
            assert hints["destructiveHint"] is False
            assert hints["openWorldHint"] is False
            Draft202012Validator.check_schema(tool.output_schema)
            result = await client.call_tool("host_toolchain_inventory", {})
            assert not result.is_error
            assert isinstance(result.structured_content, dict)
            Draft202012Validator(tool.output_schema).validate(result.structured_content)
            assert result.structured_content["tools"]["adb"]["version"] == "37.0.1"

    asyncio.run(check())

    # Real localhost MCP tool invocation against a synthetic fixed absolute
    # executable, including process startup and cleanup. No real ADB/SDK.
    adb = _bin(tmp_path, "adb")
    adb.write_text("#!/usr/bin/env python3\nprint('Version 37.0.1')\n", encoding="utf-8")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from android_mcp_host.server import create_server\n"
        "from android_mcp_host.toolchain_inventory import ToolchainInventory\n"
        "create_server(toolchain_inventory=ToolchainInventory("
        "paths={'adb':Path(sys.argv[1])},sdk_root=Path(sys.argv[2]))).run("
        "transport='http',host='127.0.0.1',port=int(sys.argv[3]))\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(adb), str(tmp_path / "no-sdk"), str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def check_http() -> None:
        last: Exception | None = None
        for _ in range(50):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    catalog = {t.name: t for t in await client.list_tools()}
                    assert "host_toolchain_inventory" in catalog
                    response = await client.call_tool("host_toolchain_inventory", {})
                    assert not response.is_error
                    assert isinstance(response.structured_content, dict)
                    assert response.structured_content["tools"]["adb"]["version"] == "37.0.1"
                    Draft202012Validator(
                        catalog["host_toolchain_inventory"].output_schema
                    ).validate(response.structured_content)
                    return
            except Exception as error:
                last = error
                await asyncio.sleep(0.1)
        raise AssertionError(f"Synthetic localhost Host MCP inventory failed: {last!r}")

    try:
        asyncio.run(check_http())
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    assert process.poll() is not None
