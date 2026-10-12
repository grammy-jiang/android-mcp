"""H2.a fixed workstation SDK/NDK/JDK facts; never install or accept a license."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator

from android_mcp_host import cli
from android_mcp_host.command_runner import RunResult, bounded_run
from android_mcp_host.sdk_ndk_inventory import SdkNdkInventory, get_sdk_ndk_output_schema
from android_mcp_host.server import create_server

EXPECTED_IDS = {
    "jdk17",
    "sdk_platform",
    "build_tools",
    "gradle",
    "emulator",
    "ndk",
    "cmake",
    "apkanalyzer_sdk",
    "apkanalyzer_homebrew",
}
VERSIONS = {
    "java": 'openjdk version "17.0.20" 2026-01-01\n',
    "gradle": "Gradle 9.6\n",
    "emulator": "Android emulator version 36.2.5\n",
    "clang": "Android clang version 17.0.2\n",
    "cmake": "cmake version 3.22.1\n",
    "apkanalyzer": "apkanalyzer 36.0.0\n",
}


def _fixture_file(
    root: Path, relative: str, text: str = "fixture\n", *, executable: bool = True
) -> Path:
    p = root / relative
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    p.chmod(0o700 if executable else 0o600)
    return p


def _complete_sdk(tmp_path: Path) -> tuple[Path, dict[str, Path]]:
    sdk = tmp_path / "trusted-sdk"
    jar = sdk / "platforms/android-36/android.jar"
    jar.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(jar, "w") as archive:
        archive.writestr("android/Manifest.txt", "synthetic")
    for name in ("aapt2", "apksigner", "zipalign", "d8"):
        _fixture_file(sdk, f"build-tools/36.0.0/{name}")
    _fixture_file(
        sdk,
        "build-tools/36.0.0/source.properties",
        "Pkg.Revision = 36.0.0\n",
        executable=False,
    )
    _fixture_file(sdk, "emulator/emulator")
    _fixture_file(sdk, "cmdline-tools/latest/bin/apkanalyzer")
    _fixture_file(sdk, "ndk/27.2.12479018/source.properties", "Pkg.Revision = 27.2.12479018\n")
    _fixture_file(sdk, "ndk/27.2.12479018/toolchains/llvm/prebuilt/darwin-arm64/bin/clang")
    _fixture_file(sdk, "cmake/3.22.1/bin/cmake")
    binaries = {
        "jdk17": _fixture_file(tmp_path, "fixed-java/java"),
        "gradle": _fixture_file(tmp_path, "fixed-gradle/gradle"),
        "apkanalyzer_homebrew": _fixture_file(tmp_path, "fixed-homebrew/apkanalyzer"),
    }
    return sdk, binaries


class FakeRunner:
    def __init__(self, replies: dict[str, RunResult | BaseException] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.replies = replies or {}

    def __call__(self, argv: Sequence[str], timeout_s: float, byte_limit: int) -> RunResult:
        self.calls.append(list(argv))
        assert 0 < timeout_s <= 5 and byte_limit == 65536
        path = Path(argv[0])
        result = self.replies.get(str(path))
        if isinstance(result, BaseException):
            raise result
        if isinstance(result, RunResult):
            return result
        return RunResult(0, VERSIONS[path.name], "", False)


def _inventory(
    sdk: Path,
    binaries: dict[str, Path] | None = None,
    runner: FakeRunner | None = None,
    *,
    system: str = "Darwin",
    architecture: str = "arm64",
) -> SdkNdkInventory:
    return SdkNdkInventory(
        sdk_root=sdk,
        fixed_binaries={} if binaries is None else binaries,
        runner=runner or FakeRunner(),
        system=system,
        architecture=architecture,
    )


def _checked(reply: dict[str, Any]) -> dict[str, Any]:
    Draft202012Validator(get_sdk_ndk_output_schema()).validate(reply)
    assert reply["schema_version"] == 1 and reply["runtime"] == "host"
    assert reply["build_authorized"] is False
    assert reply["sdk_licenses_verified"] is False
    assert set(reply["tools"]) == EXPECTED_IDS
    return reply


def test_t_h2a_01_complete_mac_jdk17_sdk36_gradle96_emulator_ndk_cmake(
    tmp_path: Path,
) -> None:
    sdk, binaries = _complete_sdk(tmp_path)
    runner = FakeRunner()
    reply = _checked(_inventory(sdk, binaries, runner).inspect())
    assert reply["status"] == "ok"
    assert reply["build_prerequisites_present"] is True
    assert {name: entry["version"] for name, entry in reply["tools"].items()} == {
        "jdk17": "17.0.20",
        "sdk_platform": "36",
        "build_tools": "36.0.0",
        "gradle": "9.6",
        "emulator": "36.2.5",
        "ndk": "27.2.12479018",
        "cmake": "3.22.1",
        "apkanalyzer_sdk": "36.0.0",
        "apkanalyzer_homebrew": "36.0.0",
    }
    assert all(item["runnable"] and item["state"] == "runnable" for item in reply["tools"].values())
    assert len(runner.calls) == 7
    assert [argv[1:] for argv in runner.calls] == [
        ["-version"],
        ["--version"],
        ["--version"],
        ["--version"],
        ["-version"],
        ["--version"],
        ["--version"],
    ]


def test_t_h2a_02_missing_sdk_jdk_or_incomplete_build_tools_cannot_be_ready(
    tmp_path: Path,
) -> None:
    absent = _checked(_inventory(tmp_path / "missing-sdk").inspect())
    assert absent["status"] == "unavailable"
    assert absent["build_prerequisites_present"] is False
    assert all(not entry["runnable"] for entry in absent["tools"].values())

    sdk, binaries = _complete_sdk(tmp_path)
    binaries.pop("jdk17")
    (sdk / "build-tools/36.0.0/aapt2").unlink()
    (sdk / "ndk/27.2.12479018/toolchains/llvm/prebuilt/darwin-arm64/bin/clang").unlink()
    result = _checked(_inventory(sdk, binaries).inspect())
    assert result["status"] == "partial" and result["build_prerequisites_present"] is False
    for key in ("jdk17", "build_tools", "ndk"):
        assert result["tools"][key]["runnable"] is False
    assert result["tools"]["sdk_platform"]["version"] == "36"
    assert result["tools"]["emulator"]["runnable"] is True


def test_t_h2a_03_hostile_env_symlink_and_wrong_java_are_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sdk, binaries = _complete_sdk(tmp_path)
    hostile = _fixture_file(tmp_path, "untrusted/bin/java", "#!/bin/sh\necho pwn\n")
    monkeypatch.setenv("JAVA_HOME", str(hostile.parent))
    monkeypatch.setenv("ANDROID_HOME", str(hostile.parent))
    monkeypatch.setenv("PATH", str(hostile.parent) + os.pathsep + os.environ.get("PATH", ""))

    java = binaries["jdk17"]
    fake = FakeRunner({str(java): RunResult(0, 'openjdk version "21.0.5"\n', "", False)})
    result = _checked(_inventory(sdk, binaries, fake).inspect())
    assert result["build_prerequisites_present"] is False
    assert result["tools"]["jdk17"]["reason"] == "VERSION_MISMATCH"
    assert [str(java), "-version"] in fake.calls
    assert all(str(hostile) not in str(command) for command in fake.calls)

    # The SDK root itself must not be a symlink to an arbitrary elsewhere tree.
    linked = tmp_path / "sdk-pointer"
    linked.symlink_to(sdk, target_is_directory=True)
    denied = _checked(_inventory(linked, binaries).inspect())
    assert denied["build_prerequisites_present"] is False
    assert denied["tools"]["sdk_platform"]["reason"] == "SDK_ROOT_SYMLINK"
    assert denied["tools"]["sdk_platform"]["runnable"] is False

    # A malicious replacement of a specific build-tools executable fails closed.
    path = sdk / "build-tools/36.0.0/aapt2"
    path.unlink()
    path.symlink_to(hostile)
    denied = _checked(_inventory(sdk, binaries).inspect())
    assert denied["tools"]["build_tools"]["state"] == "path_rejected"
    assert denied["tools"]["build_tools"]["reason"] == "UNTRUSTED_SYMLINK"


def test_t_h2a_04_sdk_apkanalyzer_is_independent_of_broken_homebrew_binary(
    tmp_path: Path,
) -> None:
    sdk, binaries = _complete_sdk(tmp_path)
    homebrew = binaries["apkanalyzer_homebrew"]
    runner = FakeRunner({str(homebrew): RunResult(4, "", "Java classpath SECRET_PAYLOAD", False)})
    result = _checked(_inventory(sdk, binaries, runner).inspect())
    assert result["status"] == "partial"
    assert result["tools"]["apkanalyzer_homebrew"]["state"] == "installed_unusable"
    assert result["tools"]["apkanalyzer_homebrew"]["reason"] == "NONZERO_EXIT"
    assert result["tools"]["apkanalyzer_sdk"]["runnable"] is True
    assert result["tools"]["apkanalyzer_sdk"]["version"] == "36.0.0"
    assert result["build_prerequisites_present"] is True
    assert "SECRET_PAYLOAD" not in json.dumps(result)


def test_t_h2a_05_failures_timeout_output_cap_and_child_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk, binaries = _complete_sdk(tmp_path)
    runner = FakeRunner(
        {
            str(binaries["jdk17"]): subprocess.TimeoutExpired(["java"], 0.1),
            str(binaries["gradle"]): RunResult(7, "", "PRIVATE_PASSWORD", False),
            str(sdk / "emulator/emulator"): RunResult(0, "x" * 70000, "", False),
            str(sdk / "cmake/3.22.1/bin/cmake"): RunResult(0, "nonsense\n", "", False),
        }
    )
    response = _checked(_inventory(sdk, binaries, runner).inspect())
    assert response["build_prerequisites_present"] is False
    assert response["tools"]["jdk17"]["reason"] == "TIMEOUT"
    assert response["tools"]["gradle"]["reason"] == "NONZERO_EXIT"
    assert response["tools"]["emulator"]["reason"] == "OUTPUT_LIMIT"
    assert response["tools"]["cmake"]["reason"] == "MALFORMED_VERSION"
    assert "PRIVATE_PASSWORD" not in str(response)
    assert all(
        action not in str(runner.calls)
        for action in ("install", "sdkmanager", "licenses", "accept")
    )

    real_popen = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []

    def track(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        proc = real_popen(*args, **kwargs)
        children.append(proc)
        return proc

    monkeypatch.setattr(subprocess, "Popen", track)
    with pytest.raises(subprocess.TimeoutExpired):
        bounded_run([sys.executable, "-c", "import time;time.sleep(8)"], 0.1, 65536)
    assert len(children) == 1 and children[0].poll() is not None
    with pytest.raises(ProcessLookupError):
        os.killpg(children[0].pid, 0)


def test_t_h2a_06_opt_in_real_fastmcp_schema_legacy_and_fake_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    class StubServer:
        def run(self, **kwargs: Any) -> None:
            assert kwargs == {"transport": "http", "host": "127.0.0.1", "port": 8765}

    def create(**kwargs: Any) -> StubServer:
        calls.append(kwargs)
        return StubServer()

    with monkeypatch.context() as mock:
        mock.setattr(cli, "create_server", create)
        mock.setattr(cli.platform, "system", lambda: "Linux")
        assert cli.main(["serve", "--sdk-ndk-inventory"]) == 0
    assert len(calls) == 1 and "sdk_ndk_inventory" in calls[0]

    sdk, binaries = _complete_sdk(tmp_path)
    inventory = _inventory(sdk, binaries)

    async def inprocess() -> None:
        async with Client(create_server()) as original:
            old = {tool.name: tool for tool in await original.list_tools()}
        assert set(old) == {"device_status", "adb_observe", "adb_develop"}
        async with Client(create_server(sdk_ndk_inventory=inventory)) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert set(tools) == {*old, "host_sdk_ndk_inventory"}
            for name, original in old.items():
                tool = tools[name]
                assert (
                    original.title,
                    original.description,
                    original.annotations,
                    original.input_schema,
                    original.output_schema,
                ) == (
                    tool.title,
                    tool.description,
                    tool.annotations,
                    tool.input_schema,
                    tool.output_schema,
                )
            tool = tools["host_sdk_ndk_inventory"]
            assert tool.output_schema is not None
            assert tool.output_schema["$id"] == "urn:android-mcp:host-sdk-ndk-inventory:v1"
            assert tool.annotations is not None
            hints = tool.annotations.model_dump(mode="json", by_alias=True)
            assert hints["readOnlyHint"] is False
            assert hints["destructiveHint"] is False
            assert hints["openWorldHint"] is False
            assert tool.input_schema.get("required", []) == []
            Draft202012Validator.check_schema(tool.input_schema)
            Draft202012Validator.check_schema(tool.output_schema)
            reply = await client.call_tool("host_sdk_ndk_inventory", {})
            assert not reply.is_error and isinstance(reply.structured_content, dict)
            Draft202012Validator(tool.output_schema).validate(reply.structured_content)
            assert reply.structured_content["build_authorized"] is False
            assert reply.structured_content["sdk_licenses_verified"] is False

    asyncio.run(inprocess())

    # True localhost HTTP against a separate process with a synthetic SDK and
    # two fake bounded local executables; not any installed SDK on the machine.
    for name in ("java", "gradle"):
        path = binaries["jdk17"] if name == "java" else binaries["gradle"]
        output = VERSIONS[name].rstrip("\n")
        path.write_text("#!/bin/sh\nprintf '%s\\n' '" + output + "'\n", encoding="utf-8")
        path.chmod(0o700)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from android_mcp_host.sdk_ndk_inventory import SdkNdkInventory\n"
        "from android_mcp_host.server import create_server\n"
        "sdk=SdkNdkInventory(sdk_root=Path(sys.argv[1]),fixed_binaries={"
        "'jdk17':Path(sys.argv[2]),'gradle':Path(sys.argv[3])},"
        "system='Darwin',architecture='arm64')\n"
        "create_server(sdk_ndk_inventory=sdk).run("
        "transport='http',host='127.0.0.1',port=int(sys.argv[4]))\n"
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            script,
            str(sdk),
            str(binaries["jdk17"]),
            str(binaries["gradle"]),
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def http_test() -> None:
        last: Exception | None = None
        for _ in range(60):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    tools = {tool.name: tool for tool in await client.list_tools()}
                    response = await client.call_tool("host_sdk_ndk_inventory", {})
                    assert not response.is_error and isinstance(response.structured_content, dict)
                    Draft202012Validator(tools["host_sdk_ndk_inventory"].output_schema).validate(
                        response.structured_content
                    )
                    assert response.structured_content["build_prerequisites_present"] is True
                    assert response.structured_content["build_authorized"] is False
                    return
            except Exception as error:
                last = error
                await asyncio.sleep(0.1)
        raise AssertionError(f"Synthetic localhost SDK/NDK inventory failed: {last!r}")

    try:
        asyncio.run(http_test())
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    assert process.poll() is not None
