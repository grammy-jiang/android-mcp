"""H2.b: completely inert, operator-pinned Android Gradle build preflight."""

from __future__ import annotations

import asyncio
import hashlib
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
from fastmcp.exceptions import ToolError
from jsonschema import Draft202012Validator

from android_mcp_host import cli
from android_mcp_host.android_build_preflight import (
    AndroidBuildPreflight,
    get_build_preflight_output_schema,
)
from android_mcp_host.command_runner import OutputLimitExceeded, RunResult, bounded_run
from android_mcp_host.server import create_server

COMMIT = "a" * 40
CHECKSUM = "b" * 64
GRADLE_METADATA = (
    "distributionUrl=https\\://services.gradle.org/distributions/gradle-9.6.0-bin.zip\n"
    f"distributionSha256Sum={CHECKSUM}\n"
    "validateDistributionUrl=true\nretries=0\n"
)


def make_project(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "approved-project"
    wrapper = root / "android/gradle/wrapper/gradle-wrapper.jar"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(wrapper, "w") as archive:
        archive.writestr("org/gradle/wrapper/GradleWrapperMain.class", "synthetic test jar")
    for filename, text in {
        "android/gradlew": "#!/bin/sh\nexit 27\n",
        "android/gradle/wrapper/gradle-wrapper.properties": GRADLE_METADATA,
        "android/app/build.gradle.kts": (
            'plugins { id("com.android.application") version "9.4.0" }\n'
            "android { compileSdk = 36\n"
            "compileOptions { sourceCompatibility = JavaVersion.VERSION_17 } }\n"
        ),
        "android/settings.gradle.kts": (
            'rootProject.name = "fixture"\n'
            'if (providers.gradleProperty("enableAndroidApp").orNull == "true") {\n'
            '  include(":app")\n}\n'
        ),
    }.items():
        path = root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        if path.name == "gradlew":
            path.chmod(0o700)
    return root, hashlib.sha256(wrapper.read_bytes()).hexdigest()


class Inventory:
    def __init__(self, versions: dict[str, str] | None = None) -> None:
        self.calls = 0
        self.versions = versions or {
            "jdk17": "17.0.20",
            "gradle": "9.6",
            "sdk_platform": "36",
            "build_tools": "36.0.0",
        }
        self.fail: BaseException | None = None

    def inspect(self) -> dict[str, Any]:
        self.calls += 1
        if self.fail is not None:
            raise self.fail
        return {
            "tools": {
                name: {
                    "version": self.versions.get(name),
                    "runnable": name in self.versions,
                }
                for name in ("jdk17", "gradle", "sdk_platform", "build_tools")
            }
        }


class GitRunner:
    def __init__(self, revision: str = COMMIT, *, dirty: bool = False) -> None:
        self.revision = revision
        self.dirty = dirty
        self.calls: list[list[str]] = []
        self.failure: BaseException | RunResult | None = None
        self.fail_at: int | None = None

    def __call__(self, argv: Sequence[str], timeout: float, limit: int) -> RunResult:
        self.calls.append(list(argv))
        assert argv[0] == "/usr/bin/git"
        assert argv[1:5] == ["-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null"]
        assert 0 < timeout <= 5 and limit == 65536
        assert argv[-3:] == ["rev-parse", "--verify", "HEAD"] or argv[-3:] == [
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ]
        if self.failure is not None and len(self.calls) == self.fail_at:
            if isinstance(self.failure, BaseException):
                raise self.failure
            return self.failure
        if argv[-3:] == ["rev-parse", "--verify", "HEAD"]:
            return RunResult(0, self.revision + "\n", "", False)
        return RunResult(0, " M android/app/build.gradle.kts\n" if self.dirty else "", "", False)


def service(
    root: Path,
    checksum: str,
    *,
    runner: GitRunner | None = None,
    inventory: Inventory | None = None,
) -> AndroidBuildPreflight:
    return AndroidBuildPreflight(
        root,
        expected_revision=COMMIT,
        expected_wrapper_sha256=checksum,
        runner=runner or GitRunner(),
        inventory=inventory or Inventory(),  # type: ignore[arg-type]
    )


def checked(value: dict[str, Any]) -> dict[str, Any]:
    Draft202012Validator(get_build_preflight_output_schema()).validate(value)
    assert value["schema_version"] == 1
    assert value["runtime"] == "host"
    assert value["execution_enabled"] is False
    assert value["sdk_licenses_verified"] is False
    return value


def code(value: dict[str, Any]) -> list[str]:
    return [error["code"] for error in value["errors"]]


def test_t_h2b_01_pinned_wrapper_project_debug_action_is_exact_inert_plan(tmp_path: Path) -> None:
    root, checksum = make_project(tmp_path)
    runner = GitRunner()
    inventory = Inventory()
    result = checked(service(root, checksum, runner=runner, inventory=inventory).plan())
    assert result["status"] == "planned"
    assert result["expected_revision"] == COMMIT and result["observed_revision"] == COMMIT
    assert result["project_root"] == str(root)
    assert result["wrapper_sha256"] == checksum
    assert result["gradle_distribution_sha256"] == CHECKSUM
    assert result["gradle_version"] == "9.6.0" and result["agp_version"] == "9.4.0"
    assert result["jdk_version"] == "17.0.20" and result["sdk_api"] == 36
    assert result["action"] == "assemble_debug" and result["variant"] == "debug"
    assert result["dirty"] is False
    assert result["tasks"] == [":app:assembleDebug"]
    assert result["argv_preview"] == [
        "./gradlew",
        "--offline",
        "--no-daemon",
        "-PenableAndroidApp=true",
        ":app:assembleDebug",
    ]
    assert inventory.calls == 1 and len(runner.calls) == 2
    assert all(argv[0] == "/usr/bin/git" for argv in runner.calls)
    assert "exit 27" not in str(result)


def test_t_h2b_02_missing_wrapper_incompatible_agp_and_sdk_jdk_denied(tmp_path: Path) -> None:
    root, checksum = make_project(tmp_path)
    wrapper = root / "android/gradle/wrapper/gradle-wrapper.jar"
    wrapper.unlink()
    runner = GitRunner()
    missing = checked(service(root, checksum, runner=runner).plan())
    assert missing["status"] == "blocked" and code(missing) == ["PROJECT_FILES_UNVERIFIED"]
    assert runner.calls == []
    root, checksum = make_project(tmp_path)
    app = root / "android/app/build.gradle.kts"
    app.write_text(app.read_text().replace('"9.4.0"', '"10.4.0"'))
    invalid = checked(service(root, checksum, runner=runner).plan())
    assert code(invalid) == ["BUILD_METADATA_UNVERIFIED"]
    assert runner.calls == []
    app.write_text(app.read_text().replace('"10.4.0"', '"9.4.0"'))
    versions = {"jdk17": "21.0.1", "gradle": "9.6", "sdk_platform": "36", "build_tools": "36.0.0"}
    unavailable = checked(service(root, checksum, inventory=Inventory(versions)).plan())
    assert unavailable["status"] == "unavailable"
    assert code(unavailable) == ["TOOLCHAIN_INCOMPATIBLE"]
    versions["jdk17"] = "17.0.20"
    versions["sdk_platform"] = "35"
    unavailable = checked(service(root, checksum, inventory=Inventory(versions)).plan())
    assert code(unavailable) == ["TOOLCHAIN_INCOMPATIBLE"]


def test_t_h2b_03_path_traversal_symlink_and_arbitrary_task_injection_rejected(
    tmp_path: Path,
) -> None:
    root, checksum = make_project(tmp_path)
    runner = GitRunner()
    planner = service(root, checksum, runner=runner)
    for action, variant in (
        ("--init-script=/tmp/evil.gradle", "debug"),
        ("assembleRelease", "debug"),
        (":app:publish", "debug"),
        ("assemble_debug", "../release"),
        ("assemble_debug", "release"),
    ):
        rejected = checked(planner.plan(action, variant))
        assert rejected["status"] == "blocked" and code(rejected) == ["INVALID_ACTION"]
        assert rejected["tasks"] == [] and rejected["argv_preview"] == []
    assert runner.calls == []
    with pytest.raises(ValueError, match="absolute"):
        AndroidBuildPreflight(Path("../android"), expected_revision=COMMIT)
    linked = tmp_path / "other-root"
    linked.symlink_to(root, target_is_directory=True)
    reply = checked(service(linked, checksum, runner=runner).plan())
    assert code(reply) == ["PROJECT_ROOT_UNTRUSTED"]
    assert runner.calls == []
    path = root / "android/app/build.gradle.kts"
    path.unlink()
    path.symlink_to(tmp_path / "outside-file")
    reply = checked(service(root, checksum, runner=runner).plan())
    assert code(reply) == ["PROJECT_FILES_UNVERIFIED"]
    assert runner.calls == []


def test_t_h2b_04_dirty_worktree_reported_without_stash_reset_or_changes(
    tmp_path: Path,
) -> None:
    root, checksum = make_project(tmp_path)
    runner = GitRunner(dirty=True)
    inventory = Inventory()
    before = {
        str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }
    result = checked(service(root, checksum, runner=runner, inventory=inventory).plan())
    after = {
        str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }
    assert result["status"] == "blocked" and result["dirty"] is True
    assert result["observed_revision"] == COMMIT
    assert code(result) == ["DIRTY_WORKTREE"]
    assert result["argv_preview"] == [] and result["tasks"] == []
    assert inventory.calls == 0
    assert before == after
    assert len(runner.calls) == 2
    assert all(
        "reset" not in call and "stash" not in call and "clean" not in call for call in runner.calls
    )


def test_t_h2b_05_git_metadata_timeout_flood_fail_without_orphan_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, checksum = make_project(tmp_path)
    for failure, expected in (
        (subprocess.TimeoutExpired(["git"], 0.1), "METADATA_TIMEOUT"),
        (OutputLimitExceeded("secret path"), "OUTPUT_LIMIT"),
        (RunResult(1, "", "private Gerrit credential", False), "METADATA_UNAVAILABLE"),
        (RunResult(0, "x" * 70000, "", False), "OUTPUT_LIMIT"),
    ):
        runner = GitRunner()
        runner.failure = failure
        runner.fail_at = 1
        response = checked(service(root, checksum, runner=runner).plan())
        assert response["status"] == "unavailable"
        assert code(response) == [expected]
        assert response["tasks"] == [] and response["argv_preview"] == []
        assert "private Gerrit credential" not in json.dumps(response)
        assert len(runner.calls) == 1

    old_popen = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []

    def record(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        process: subprocess.Popen[bytes] = old_popen(*args, **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", record)
    with pytest.raises(subprocess.TimeoutExpired):
        bounded_run([sys.executable, "-c", "import time;time.sleep(8)"], 0.12, 65536)
    assert len(children) == 1 and children[0].poll() is not None
    with pytest.raises(ProcessLookupError):
        os.killpg(children[0].pid, 0)


def test_t_h2b_06_versioned_mcp_schema_optin_plan_only_and_fake_http(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class Stub:
        def run(self, **kwargs: Any) -> None:
            assert kwargs == {"transport": "http", "host": "127.0.0.1", "port": 8765}

    def make(**kwargs: Any) -> Stub:
        calls.append(kwargs)
        return Stub()

    with monkeypatch.context() as scoped:
        scoped.setattr(cli.platform, "system", lambda: "Linux")
        scoped.setattr(cli, "create_server", make)
        assert cli.main(["serve", "--build-preflight"]) == 0
    assert len(calls) == 1 and "build_preflight" in calls[0]

    root, checksum = make_project(tmp_path)
    planner = service(root, checksum)

    async def check_inprocess() -> None:
        async with Client(create_server()) as base:
            original = {t.name: t for t in await base.list_tools()}
        assert set(original) == {"device_status", "adb_observe", "adb_develop"}
        async with Client(create_server(build_preflight=planner)) as client:
            tools = {t.name: t for t in await client.list_tools()}
            assert set(tools) == {*original, "android_build_preflight"}
            for name, old in original.items():
                new = tools[name]
                assert (
                    old.title,
                    old.description,
                    old.annotations,
                    old.input_schema,
                    old.output_schema,
                ) == (
                    new.title,
                    new.description,
                    new.annotations,
                    new.input_schema,
                    new.output_schema,
                )
            tool = tools["android_build_preflight"]
            assert tool.output_schema is not None
            assert tool.output_schema["$id"] == "urn:android-mcp:host-android-build-preflight:v1"
            assert "No Gradle wrapper" in tool.description
            assert tool.annotations is not None
            hints = tool.annotations.model_dump(mode="json", by_alias=True)
            assert hints["readOnlyHint"] is False
            assert hints["destructiveHint"] is False
            assert hints["openWorldHint"] is False
            Draft202012Validator.check_schema(tool.input_schema)
            Draft202012Validator.check_schema(tool.output_schema)
            assert tool.input_schema["properties"]["action"]["enum"] == [
                "assemble_debug",
                "lint_debug",
                "test_jvm",
            ]
            response = await client.call_tool("android_build_preflight", {"action": "lint_debug"})
            assert not response.is_error and isinstance(response.structured_content, dict)
            Draft202012Validator(tool.output_schema).validate(response.structured_content)
            assert response.structured_content["tasks"] == [":app:lintDebug"]
            assert response.structured_content["execution_enabled"] is False
            with pytest.raises(ToolError, match="Input should be"):
                await client.call_tool("android_build_preflight", {"action": "publish"})

    asyncio.run(check_inprocess())

    # Exercise actual localhost HTTP MCP server using an injected synthetic
    # read-only metadata runner, not any installed Gradle/JDK or physical device.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    script = (
        "from pathlib import Path\n"
        "from android_mcp_host.android_build_preflight import AndroidBuildPreflight\n"
        "from android_mcp_host.command_runner import RunResult\n"
        "from android_mcp_host.server import create_server\n"
        "import sys\n"
        "class Inventory:\n"
        " def inspect(self):\n"
        "  return {'tools': {key: {'runnable':True,'version':value} for key,value in "
        "{'jdk17':'17.0.20','sdk_platform':'36','gradle':'9.6','build_tools':'36.0.0'}.items()}}\n"
        "def metadata(argv,seconds,limit):\n"
        " if argv[-3:] == ['rev-parse','--verify','HEAD']:\n"
        "  return RunResult(0,sys.argv[2]+'\\n','',False)\n"
        " if argv[-3:] == ['status','--porcelain=v1','--untracked-files=all']:\n"
        "  return RunResult(0,'','',False)\n"
        " raise ValueError('unexpected command')\n"
        "p=AndroidBuildPreflight(Path(sys.argv[1]),expected_revision=sys.argv[2],"
        "expected_wrapper_sha256=sys.argv[3],inventory=Inventory(),runner=metadata)\n"
        "create_server(build_preflight=p).run(transport='http',host='127.0.0.1',"
        "port=int(sys.argv[4]))\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(root), COMMIT, checksum, str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def http_check() -> None:
        last: Exception | None = None
        for _ in range(55):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    tools = {t.name: t for t in await client.list_tools()}
                    reply = await client.call_tool(
                        "android_build_preflight", {"action": "assemble_debug"}
                    )
                    assert not reply.is_error
                    assert isinstance(reply.structured_content, dict)
                    Draft202012Validator(tools["android_build_preflight"].output_schema).validate(
                        reply.structured_content
                    )
                    assert reply.structured_content["status"] == "planned"
                    assert reply.structured_content["expected_revision"] == COMMIT
                    assert reply.structured_content["execution_enabled"] is False
                    return
            except Exception as exc:
                last = exc
                await asyncio.sleep(0.1)
        raise AssertionError(f"Synthetic H2.b localhost HTTP failed: {last!r}")

    try:
        asyncio.run(http_check())
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    assert process.poll() is not None
