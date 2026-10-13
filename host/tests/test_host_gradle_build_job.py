"""H2.f accepted synthetic Gradle build/lint jobs; no Android device needed."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path
from typing import Any

from fastmcp import Client
from jsonschema import Draft202012Validator

from android_mcp_host.android_build_preflight import TASKS
from android_mcp_host.command_runner import RunResult
from android_mcp_host.durable_jobs import DurableJobStore
from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.server import create_server

REVISION = "a" * 40
OWNER = "build-owner"
ARTIFACT_OWNER = "build-artifact-owner"
REQUEST = "host-build-001"


def fake_apk() -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as zf:
        zf.writestr("AndroidManifest.xml", b"synthetic binary axml")
        zf.writestr("resources.arsc", b"fixture")
    return stream.getvalue()


def project(root: Path) -> tuple[Path, str]:
    android = root / "android"
    (android / "gradle/wrapper").mkdir(parents=True)
    wrapper = android / "gradle/wrapper/gradle-wrapper.jar"
    with zipfile.ZipFile(wrapper, "w") as zf:
        zf.writestr("org/gradle/wrapper/GradleWrapperMain.class", b"synthetic fixture")
    script = android / "gradlew"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o700)
    return root, hashlib.sha256(wrapper.read_bytes()).hexdigest()


class FakePreflight:
    def __init__(self, root: Path, digest: str) -> None:
        self.root = root
        self.digest = digest
        self.result_status = "planned"

    def plan(self, action: str, variant: str) -> dict[str, Any]:
        return {
            "status": self.result_status,
            "project_root": str(self.root),
            "expected_revision": REVISION,
            "observed_revision": REVISION,
            "wrapper_sha256": self.digest,
            "dirty": False,
            "variant": variant,
            "action": action,
            "tasks": list(TASKS[action]) if action in TASKS else [],
            "execution_enabled": False,
        }


def make(
    tmp_path: Path,
    *,
    runner: Any = None,
    timeout_s: float = 3.0,
) -> tuple[Any, FakePreflight, DurableJobStore, PrivateArtifactStore, Path]:
    from android_mcp_host.controlled_build_jobs import ControlledBuildJobs

    root, digest = project(tmp_path / "source")
    preflight = FakePreflight(root, digest)
    jobs = DurableJobStore(tmp_path / "private-jobs", lease_seconds=120.0)
    artifacts = PrivateArtifactStore(tmp_path / "private-artifacts")
    kwargs: dict[str, Any] = {
        "preflight": preflight,
        "jobs": jobs,
        "artifacts": artifacts,
        "root": root,
        "approved_revision": REVISION,
        "wrapper_sha256": digest,
        "owner": OWNER,
        "artifact_owner": ARTIFACT_OWNER,
        "timeout_s": timeout_s,
    }
    if runner is not None:
        kwargs["runner"] = runner
    return ControlledBuildJobs(**kwargs), preflight, jobs, artifacts, root


def test_t_h2f_01_approved_synthetic_gradle_job_and_private_artifact(
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def run(argv: Any, timeout: float, limit: int, cwd: Path) -> RunResult:
        calls.append(list(argv))
        assert cwd.name == "android"
        assert "--offline" in argv and "--no-daemon" in argv
        assert timeout <= 120 and limit <= 65536
        output = cwd / "app/build/outputs/apk/debug/app-debug.apk"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(fake_apk())
        return RunResult(0, "BUILD SUCCESSFUL", "", False)

    builder, _, jobs, store, _ = make(tmp_path, runner=run)
    reply = builder.submit("assemble_debug", REQUEST)
    assert reply["status"] == "ok" and reply["state"] == "succeeded"
    assert reply["job_id"].startswith("job_")
    assert reply["report_handle"].startswith("art_")
    assert reply["apk_handle"].startswith("art_")
    assert reply["result_sha256"] is not None
    assert reply["errors"] == []
    assert len(calls) == 1
    assert calls[0][-1] == ":app:assembleDebug"
    assert jobs.status(OWNER, reply["job_id"])["job"]["attempts"] == 1
    record = store.public_metadata(ARTIFACT_OWNER, reply["apk_handle"])
    assert record["status"] == "ok"
    report = json.loads(store.read(ARTIFACT_OWNER, reply["report_handle"]))
    assert report["action"] == "assemble_debug"
    assert report["state"] == "succeeded"
    assert str(tmp_path) not in json.dumps(reply)
    assert str(tmp_path) not in json.dumps(report)


def test_t_h2f_02_unknown_action_variant_preflight_and_tampered_wrapper(
    tmp_path: Path,
) -> None:
    calls: list[Any] = []

    def forbidden(*args: Any) -> RunResult:
        calls.append(args)
        raise AssertionError("Runner must not execute")

    builder, preflight, jobs, _, root = make(tmp_path, runner=forbidden)
    for action, variant in (
        ("release", "debug"),
        ("assemble_debug", "release"),
        ("--offline", "debug"),
    ):
        result = builder.submit(action, "denied-req", variant=variant)
        assert result["status"] == "blocked"
    preflight.result_status = "unavailable"
    assert builder.submit("assemble_debug", "unavailable-req")["status"] == "blocked"
    preflight.result_status = "planned"
    (root / "android/gradle/wrapper/gradle-wrapper.jar").write_bytes(b"tampered")
    assert builder.submit("assemble_debug", "tamper-req")["status"] == "blocked"
    assert calls == []
    assert jobs.list_status(OWNER) == []


def test_t_h2f_03_logs_credentials_and_ansi_never_reach_report_or_mcp(
    tmp_path: Path,
) -> None:
    secret = "TOKEN=secret1234 PASSWORD=do-not-show \x1b[31mRED\x1b[0m"

    def run(*args: Any) -> RunResult:
        return RunResult(0, secret * 300, secret, True)

    builder, _, jobs, store, _ = make(tmp_path, runner=run)
    response = builder.submit("lint_debug", REQUEST)
    assert response["status"] == "failed"
    assert response["state"] == "failed"
    assert "secret1234" not in json.dumps(response)
    assert "do-not-show" not in json.dumps(response)
    assert jobs.status(OWNER, response["job_id"])["job"]["state"] == "failed"
    assert store.list_metadata(ARTIFACT_OWNER) == []


def test_t_h2f_04_nonzero_exit_missing_output_and_sdk_denial_are_truthful(
    tmp_path: Path,
) -> None:
    def failed(*args: Any) -> RunResult:
        return RunResult(1, "BUILD FAILED", "SDK absent SECRET", False)

    builder, preflight, _, store, _ = make(tmp_path, runner=failed)
    fail = builder.submit("test_jvm", REQUEST)
    assert fail["status"] == "failed" and fail["state"] == "failed"
    assert fail["apk_handle"] is None
    assert fail["errors"][0]["code"] == "BUILD_FAILED"
    assert "SECRET" not in json.dumps(fail)

    def missing(*args: Any) -> RunResult:
        return RunResult(0, "SUCCESS", "", False)

    replacement, _, _, _, _ = make(tmp_path / "other", runner=missing)
    invalid = replacement.submit("assemble_debug", "missing-apk-req")
    assert invalid["status"] == "failed"
    assert invalid["errors"][0]["code"] == "OUTPUT_INVALID"
    preflight.result_status = "unavailable"
    assert builder.submit("assemble_debug", "jdk-missing-req")["status"] == "blocked"
    assert all("SDK absent" not in str(item) for item in store.list_metadata(ARTIFACT_OWNER))


def test_t_h2f_05_idempotency_cancel_timeout_and_no_unsafe_reexecution(
    tmp_path: Path,
) -> None:
    calls = [0]

    def succeed(*args: Any) -> RunResult:
        calls[0] += 1
        return RunResult(0, "", "", False)

    builder, preflight, jobs, _, _ = make(tmp_path, runner=succeed)
    first = builder.submit("lint_debug", REQUEST)
    assert first["state"] == "succeeded"
    again = builder.submit("lint_debug", REQUEST)
    assert again["job_id"] == first["job_id"]
    assert calls == [1]
    conflict = builder.submit("test_jvm", REQUEST)
    assert conflict["status"] == "blocked"
    assert calls == [1]

    def timed(*args: Any) -> RunResult:
        raise subprocess.TimeoutExpired(["gradlew"], 0.01)

    timeout_builder, _, _, _, _ = make(tmp_path / "timeout", runner=timed)
    timeout = timeout_builder.submit("lint_debug", "timeout-request")
    assert timeout["status"] == "uncertain" and timeout["state"] == "uncertain"
    assert timeout_builder.submit("lint_debug", "timeout-request")["state"] == "uncertain"


def test_t_h2f_06_fastmcp_opt_in_real_contract_and_no_physical_adb(
    tmp_path: Path,
) -> None:
    from android_mcp_host.controlled_build_jobs import get_build_job_schema

    calls: list[Any] = []

    def fake(*args: Any) -> RunResult:
        calls.append(args)
        return RunResult(0, "success", "", False)

    builder, _, _, _, _ = make(tmp_path, runner=fake)

    async def verify() -> None:
        async with Client(create_server()) as plain:
            baseline = {tool.name: tool for tool in await plain.list_tools()}
        async with Client(create_server(build_jobs=builder)) as client:
            catalog = {tool.name: tool for tool in await client.list_tools()}
            assert set(catalog) == {*baseline, "host_gradle_build"}
            assert all(catalog[name] == baseline[name] for name in baseline)
            tool = catalog["host_gradle_build"]
            assert tool.output_schema == get_build_job_schema()
            Draft202012Validator.check_schema(tool.output_schema)
            assert tool.annotations is not None
            assert tool.annotations.read_only_hint is False
            metadata = tool.annotations.model_dump(mode="json", by_alias=True)
            assert metadata["destructiveHint"] is True
            assert metadata["openWorldHint"] is True
            assert set(tool.input_schema["required"]) == {"action", "request_id"}
            response = await client.call_tool(
                "host_gradle_build", {"action": "lint_debug", "request_id": REQUEST}
            )
            assert not response.is_error
            result = response.structured_content
            assert isinstance(result, dict)
            Draft202012Validator(tool.output_schema).validate(result)
            assert result["state"] == "succeeded" and result["status"] == "ok"
            assert "project_root" not in json.dumps(result)
            assert str(tmp_path) not in json.dumps(result)

    asyncio.run(verify())
    assert len(calls) == 1
