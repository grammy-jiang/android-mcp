"""H3.f mandatory fake-only debug APK deployment and Host MCP contracts."""

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
from test_avd_provisioning import NAME, OWNER
from test_emulator_lifecycle_jobs import REQUEST as LIFECYCLE_REQUEST
from test_emulator_lifecycle_jobs import engine

from android_mcp_host.command_runner import RunResult
from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.server import create_server

ARTIFACT_OWNER = "synthetic-deploy-private"
PACKAGE = "org.example.synthetic.debug"
APK_MIME = "application/vnd.android.package-archive"
REQ = "debug-deploy-request-001"


def fixture_apk(
    root: Path, *, package: str = PACKAGE, abi: str = "arm64-v8a", signed: bool = True
) -> bytes:
    from android_mcp_host.avd_provision_support import root_key
    from android_mcp_host.emulator_debug_support import fixture_mac

    secret = root_key(root / "owned-avds", create=False)
    assert isinstance(secret, bytes)
    manifest = (
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android" '
        f'package="{package}" android:versionCode="2" android:versionName="2.0" />'
    ).encode()
    members = {
        "AndroidManifest.xml": manifest,
        "resources.arsc": b"synthetic resources",
        f"lib/{abi}/libfixture.so": b"synthetic library only",
    }
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as output:
        for name, content in sorted(members.items()):
            output.writestr(name, content)
        if signed:
            digest = fixture_mac(members, secret)
            output.writestr("META-INF/MCP-SYNTHETIC-HMAC.txt", digest.encode("ascii"))
    return stream.getvalue()


def fake_result(argv: Any, seconds: float, limit: int) -> RunResult:
    assert seconds <= 10 and limit <= 8192
    action = argv[argv.index("--action") + 1]
    name = argv[argv.index("--avd") + 1]
    package = argv[argv.index("--package") + 1]
    return RunResult(
        0,
        json.dumps(
            {"synthetic": True, "action": action, "avd": name, "package": package, "success": True}
        ),
        "",
        False,
    )


def setup_deploy(
    tmp_path: Path,
    *,
    runner: Any = fake_result,
    running: bool = True,
) -> tuple[Any, Any, Any, PrivateArtifactStore, str, str, str, str]:
    from android_mcp_host.emulator_debug_deployment import DebugDeployment

    lifecycle, handle, jobs, backend = engine(tmp_path, backend=running)
    lifecycle_job = "job_" + "x" * 32
    if running:
        started = lifecycle.run("start", NAME, handle, request_id=LIFECYCLE_REQUEST)
        assert started["status"] == "ok"
        lifecycle_job = started["job_id"]
    artifacts = PrivateArtifactStore(tmp_path / "private-deploy-artifacts")
    content = fixture_apk(tmp_path)
    record = artifacts.put(ARTIFACT_OWNER, content, mime_type=APK_MIME)
    deploy = DebugDeployment(
        lifecycle.provisioner,
        lifecycle,
        jobs,
        artifacts,
        owner=OWNER,
        artifact_owner=ARTIFACT_OWNER,
        expected_package=PACKAGE,
        fixture_runner=runner,
    )
    return (
        deploy,
        lifecycle,
        jobs,
        artifacts,
        handle,
        lifecycle_job,
        record["handle"],
        hashlib.sha256(content).hexdigest(),
    )


def invoke(
    deploy: Any,
    action: str,
    handle: str,
    lifecycle_job: str,
    artifact: str,
    digest: str,
    *,
    request: str = REQ,
    install_report: str | None = None,
    name: str = NAME,
    package: str = PACKAGE,
) -> dict[str, Any]:
    return deploy.submit(
        action,
        name,
        handle,
        lifecycle_job,
        artifact,
        digest,
        package,
        request_id=request,
        install_report_handle=install_report,
    )


def test_t_h3f_01_pinned_synthetic_install_receipt_is_exact(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(argv: Any, seconds: float, limit: int) -> RunResult:
        calls.append(list(argv))
        return fake_result(argv, seconds, limit)

    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(
        tmp_path,
        runner=runner,
    )
    try:
        plan = invoke(deploy, "plan", handle, lid, apk, sha)
        assert plan["status"] == "planned"
        assert plan["real_deployment_enabled"] is False
        installed = invoke(deploy, "install", handle, lid, apk, sha)
        assert installed["status"] == "simulated"
        assert installed["install_state"] == "synthetic_installed"
        assert installed["package_id"] == PACKAGE
        assert installed["signature_provenance"] == "synthetic_hmac_fixture_only"
        assert installed["report_handle"].startswith("art_")
        assert installed["job_id"].startswith("job_")
        assert installed["target"] == "disposable_emulator_only"
        assert installed["physical_device_writes_enabled"] is False
        assert calls == [
            [
                "fixture-debug-deploy",
                "--action",
                "install",
                "--avd",
                NAME,
                "--lifecycle-job",
                lid,
                "--package",
                PACKAGE,
                "--apk-sha256",
                sha,
            ]
        ]
        report = json.loads(artifacts.read(ARTIFACT_OWNER, installed["report_handle"]))
        assert report["apk_sha256"] == sha
        assert report["package_id"] == PACKAGE
        assert report["avd_handle"] == handle
        assert report["state"] == "synthetic_installed"
        assert jobs.status(OWNER, installed["job_id"])["job"]["state"] == "succeeded"
        assert str(tmp_path) not in json.dumps(installed)
    finally:
        live.shutdown()


def test_t_h3f_02_physical_serial_and_wrong_avd_denied_before_runner(tmp_path: Path) -> None:
    calls: list[Any] = []

    def never(*args: Any) -> RunResult:
        calls.append(args)
        raise AssertionError("physical device fallback must not run")

    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(tmp_path, runner=never)
    try:
        for name, avd, job in (
            ("RF8N00012345678", handle, lid),
            ("emulator-5554", handle, lid),
            (NAME, "mcpavd_" + "z" * 32, lid),
            (NAME, handle, "job_" + "z" * 32),
        ):
            denied = invoke(deploy, "install", avd, job, apk, sha, name=name)
            assert denied["status"] == "blocked"
        assert calls == []
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


def test_t_h3f_03_unsigned_wrong_package_abi_and_flags_denied(tmp_path: Path) -> None:
    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(tmp_path)
    try:
        for attributes in (
            {"signed": False},
            {"package": "org.example.foreign.app"},
            {"abi": "x86_64"},
        ):
            content = fixture_apk(tmp_path, **attributes)
            forged = artifacts.put(ARTIFACT_OWNER, content, mime_type=APK_MIME)
            denied = invoke(
                deploy,
                "install",
                handle,
                lid,
                forged["handle"],
                hashlib.sha256(content).hexdigest(),
                request="bad-fixture",
            )
            assert denied["status"] == "blocked"
        assert invoke(deploy, "install --unsafe", handle, lid, apk, sha)["status"] == "blocked"
        assert invoke(deploy, "install", handle, lid, apk, "a" * 64)["status"] == "blocked"
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


def test_t_h3f_04_launch_uninstall_and_cleanup_exact_test_package(tmp_path: Path) -> None:
    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(tmp_path)
    try:
        installed = invoke(deploy, "install", handle, lid, apk, sha)
        token = installed["report_handle"]
        launched = invoke(
            deploy,
            "launch",
            handle,
            lid,
            apk,
            sha,
            install_report=token,
            request="launch-owned-debug",
        )
        assert launched["status"] == "simulated"
        assert launched["install_state"] == "synthetic_launched"
        assert (
            invoke(
                deploy,
                "uninstall",
                handle,
                lid,
                apk,
                sha,
                install_report=token,
                request="uninstall-owned-debug",
            )["install_state"]
            == "synthetic_removed"
        )
        denied = invoke(
            deploy,
            "launch",
            handle,
            lid,
            apk,
            sha,
            install_report=token,
            request="launch-after-removal",
        )
        assert denied["status"] == "blocked"
        second = invoke(deploy, "install", handle, lid, apk, sha, request="install-second")
        assert second["status"] == "simulated"
        cleaned = invoke(
            deploy,
            "cleanup",
            handle,
            lid,
            apk,
            sha,
            install_report=second["report_handle"],
            request="cleanup-owned-debug",
        )
        assert cleaned["status"] == "simulated"
        assert cleaned["install_state"] == "synthetic_removed"
        assert all(
            item["status"] != "ok" or item["real_deployment_enabled"] is False
            for item in (installed, launched, cleaned)
        )
    finally:
        live.shutdown()


def test_t_h3f_05_timeout_restart_and_duplicate_are_not_unsafe_retries(
    tmp_path: Path,
) -> None:
    calls = [0]

    def timeout(*args: Any) -> RunResult:
        calls[0] += 1
        raise subprocess.TimeoutExpired(["fixture-debug-deploy"], 0.01)

    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(tmp_path, runner=timeout)
    try:
        original = invoke(deploy, "install", handle, lid, apk, sha)
        assert original["status"] == "uncertain"
        assert jobs.status(OWNER, original["job_id"])["job"]["state"] == "uncertain"
        assert invoke(deploy, "install", handle, lid, apk, sha)["status"] == "uncertain"
        assert (
            invoke(deploy, "install", handle, lid, apk, sha, request="different-request")["status"]
            == "blocked"
        )
        assert calls == [1]
    finally:
        live.shutdown()


def test_t_h3f_06_default_off_mcp_contract_explicit_emulator_only(tmp_path: Path) -> None:
    from android_mcp_host.emulator_debug_deployment import get_debug_deploy_schema

    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(
        tmp_path,
        runner=None,
        running=False,
    )

    async def verify() -> None:
        async with Client(create_server()) as baseline:
            original = {tool.name: tool for tool in await baseline.list_tools()}
        async with Client(create_server(debug_deployment=deploy)) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert set(tools) == {*original, "host_emulator_debug_deploy"}
            assert all(tools[name] == original[name] for name in original)
            tool = tools["host_emulator_debug_deploy"]
            Draft202012Validator.check_schema(tool.output_schema)
            assert tool.output_schema == get_debug_deploy_schema()
            assert tool.annotations is not None
            assert tool.annotations.model_dump(mode="json", by_alias=True)["destructiveHint"]
            result = await client.call_tool(
                "host_emulator_debug_deploy",
                {
                    "action": "plan",
                    "avd_name": NAME,
                    "avd_handle": handle,
                    "lifecycle_job_id": lid,
                    "apk_handle": apk,
                    "apk_sha256": sha,
                    "package_id": PACKAGE,
                },
            )
            assert not result.is_error
            assert result.structured_content["status"] == "planned"
            assert result.structured_content["real_deployment_enabled"] is False
            assert result.structured_content["physical_device_writes_enabled"] is False
            Draft202012Validator(tool.output_schema).validate(result.structured_content)
            blocked = await client.call_tool(
                "host_emulator_debug_deploy",
                {
                    "action": "install",
                    "avd_name": NAME,
                    "avd_handle": handle,
                    "lifecycle_job_id": lid,
                    "apk_handle": apk,
                    "apk_sha256": sha,
                    "package_id": PACKAGE,
                    "request_id": REQ,
                },
            )
            assert blocked.structured_content["status"] == "blocked"

    try:
        asyncio.run(verify())
    finally:
        live.shutdown()
    assert jobs.list_status(OWNER) == []
