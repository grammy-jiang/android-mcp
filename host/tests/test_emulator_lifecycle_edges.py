"""H3.c synthetic-only emulator lifecycle hardening and fail-closed faults."""

from __future__ import annotations

import asyncio
import hashlib
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from test_avd_provisioning import NAME, OWNER, provider
from test_emulator_lifecycle_jobs import REQUEST, engine, fake_emulator

import android_mcp_host.emulator_lifecycle as lifecycle
import android_mcp_host.synthetic_emulator_backend as synthetic
from android_mcp_host import cli
from android_mcp_host.durable_jobs import DurableJobStore


@pytest.mark.parametrize("owner", ["other/owner", "", 123, None])
def test_invalid_lifecycle_scope_denied_before_records(
    tmp_path: Path,
    owner: Any,
) -> None:
    p = provider(tmp_path)
    store = DurableJobStore(tmp_path / "jobs")
    with pytest.raises(ValueError, match="lifecycle owner"):
        lifecycle.EmulatorLifecycle(p, store, owner=owner)


@pytest.mark.parametrize("budget", [0, -1, 5.5, True, "1", float("nan"), float("inf")])
def test_invalid_readiness_deadline_rejected(tmp_path: Path, budget: Any) -> None:
    p = provider(tmp_path)
    store = DurableJobStore(tmp_path / "jobs")
    with pytest.raises(ValueError, match="deadline"):
        lifecycle.EmulatorLifecycle(p, store, owner=OWNER, readiness_timeout_s=budget)


def test_backend_cannot_be_arbitrary_executor_object(tmp_path: Path) -> None:
    p = provider(tmp_path)
    store = DurableJobStore(tmp_path / "jobs")
    with pytest.raises(ValueError, match="Only pinned synthetic"):
        lifecycle.EmulatorLifecycle(p, store, owner=OWNER, backend=object())  # type: ignore[arg-type]


def test_lifecycle_schema_loader_must_return_an_object(monkeypatch: pytest.MonkeyPatch) -> None:
    class Resource:
        def joinpath(self, name: str) -> Resource:
            assert name == "host-emulator-lifecycle.v1.schema.json"
            return self

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return "[]"

    monkeypatch.setattr(lifecycle, "files", lambda _: Resource())
    with pytest.raises(ValueError, match="Invalid packaged"):
        lifecycle.get_emulator_lifecycle_schema()


@pytest.mark.parametrize(
    "kind",
    [
        "invalid-hash",
        "symlink",
        "non-executable",
        "no-marker",
        "empty",
        "incorrect-prefix",
        "too-large",
        "hardlink",
        "wrong-name",
    ],
)
def test_fake_backend_must_be_hash_pinned_and_not_real_qemu(
    tmp_path: Path,
    kind: str,
) -> None:
    binary, digest = fake_emulator(tmp_path)
    if kind == "wrong-name":
        binary = binary.rename(binary.with_name("emulator"))
        with pytest.raises(ValueError):
            synthetic.SyntheticEmulatorBackend(binary, digest)
        return
    target = binary
    if kind == "symlink":
        target = tmp_path / "alias"
        target.symlink_to(binary)
        # an alias with a different basename cannot be configured
        with pytest.raises(ValueError):
            synthetic.SyntheticEmulatorBackend(target, digest)
        return
    if kind == "invalid-hash":
        digest = "0" * 64
    elif kind == "non-executable":
        binary.chmod(0o600)
    elif kind == "no-marker":
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    elif kind == "empty":
        binary.write_bytes(b"")
    elif kind == "incorrect-prefix":
        binary.write_bytes(b"ANDROID-MCP-SYNTHETIC-EMULATOR-ONLY")
    elif kind == "too-large":
        binary.write_bytes(b"#!/bin/sh\n# ANDROID-MCP-SYNTHETIC-EMULATOR-ONLY\n" + b"#" * 17000)
    elif kind == "hardlink":
        os.link(binary, tmp_path / "other")
    backend = synthetic.SyntheticEmulatorBackend(target, digest)
    assert backend._verify_executable() is False
    with pytest.raises(synthetic.SyntheticEmulatorError, match="UNTRUSTED_FIXTURE"):
        backend.launch(NAME, tmp_path, 0.1)


def test_fake_binary_signed_marker_does_not_enable_real_qemu(tmp_path: Path) -> None:
    p, digest = fake_emulator(tmp_path)
    backend = synthetic.SyntheticEmulatorBackend(p, digest)
    assert backend._verify_executable()
    # Our fake executable is a Python script; never accept real system emulator.
    assert (
        synthetic.SyntheticEmulatorBackend(
            p, hashlib.sha256(b"/bin/sh").hexdigest()
        )._verify_executable()
        is False
    )
    assert (tmp_path / "mcp-fixture-emulator").exists()


def test_constructor_refuses_nonabsolute_invalid_binary(tmp_path: Path) -> None:
    for binary, digest in (
        (Path("mcp-fixture-emulator"), "a" * 64),
        (tmp_path / "emulator", "a" * 64),
        (tmp_path / "mcp-fixture-emulator", "BAD"),
    ):
        with pytest.raises(ValueError):
            synthetic.SyntheticEmulatorBackend(binary, digest)


@pytest.mark.parametrize(
    "value",
    [
        {"serial": "emulator-5555"},
        {"serial": "emulator-5548"},
        {"serial": "emulator-5700"},
        {"serial": "emulator-xyz"},
        {"api": True},
        {"qemu": "true"},
        {"boot": 1},
    ],
)
def test_fake_child_malformed_readiness_never_creates_verified_running_record(
    tmp_path: Path,
    value: dict[str, Any],
) -> None:
    control, handle, store, _ = engine(tmp_path, emulator_kwargs=value)
    try:
        response = control.run("start", NAME, handle, request_id=REQUEST)
        assert response["status"] in {"failed", "uncertain"}
        assert response["process_confirmed"] is False
        assert store.status(OWNER, response["job_id"])["job"]["state"] in {"failed", "uncertain"}
    finally:
        control.shutdown()


def test_no_unowned_process_pid_is_ever_accepted_for_stop(tmp_path: Path) -> None:
    control, handle, jobs, _ = engine(tmp_path, backend=False)
    user_supplied_job_id = "job_" + "a" * 32
    assert control.run("stop", NAME, handle, job_id=user_supplied_job_id)["status"] == "blocked"
    assert control.run("status", NAME, handle, job_id=user_supplied_job_id)["status"] == "not_found"
    assert jobs.list_status(OWNER) == []


def test_durable_worker_crash_marks_uncertain_instead_of_blind_retry(tmp_path: Path) -> None:
    control, handle, jobs, backend = engine(tmp_path)
    started = control.run("start", NAME, handle, request_id=REQUEST)
    job_id = started["job_id"]
    assert started["status"] == "ok"
    try:
        session = control._sessions[job_id]
        assert backend is not None
        assert backend.stop(session.process) is True
        observed = control.run("status", NAME, handle, job_id=job_id)
        assert observed["status"] == "uncertain"
        assert observed["process_confirmed"] is False
        assert jobs.status(OWNER, job_id)["job"]["state"] == "uncertain"
        assert control.run("start", NAME, handle, request_id="second-job")["status"] == "blocked"
    finally:
        control.shutdown()


def test_same_request_replay_after_clean_stop_is_terminal_without_rerun(
    tmp_path: Path,
) -> None:
    control, handle, jobs, backend = engine(tmp_path)
    try:
        first = control.run("start", NAME, handle, request_id=REQUEST)
        job_id = first["job_id"]
        stop = control.run("stop", NAME, handle, job_id=job_id)
        assert stop["status"] == "ok"
        replay = control.run("start", NAME, handle, request_id=REQUEST)
        assert replay["status"] == "ok"
        assert replay["lifecycle_state"] == "stopped"
        assert replay["job_id"] == job_id
        assert jobs.status(OWNER, job_id)["job"]["attempts"] == 1
    finally:
        control.shutdown()


def test_long_lived_worker_reconciles_without_reclaim_after_restart(
    tmp_path: Path,
) -> None:
    control, handle, jobs, backend = engine(tmp_path)
    first = control.run("start", NAME, handle, request_id=REQUEST)
    job_id = first["job_id"]
    assert first["status"] == "ok"
    try:
        # A new controller sees the durable running record but does not adopt PID.
        other = lifecycle.EmulatorLifecycle(
            control.provisioner,
            DurableJobStore(tmp_path / "jobs", lease_seconds=90),
            owner=OWNER,
            backend=backend,
        )
        status = other.run("status", NAME, handle, job_id=job_id)
        assert status["lifecycle_state"] == "uncertain"
        assert status["process_confirmed"] is False
        assert other.run("start", NAME, handle, request_id=REQUEST)["status"] == "uncertain"
        assert other.run("start", NAME, handle, request_id="new-request")["status"] == "blocked"
    finally:
        control.shutdown()


def test_approval_identity_change_blocks_existing_worker(tmp_path: Path) -> None:
    controller, handle, jobs, _ = engine(tmp_path)
    try:
        launched = controller.run("start", NAME, handle, request_id=REQUEST)
        assert launched["status"] == "ok"
        marker = tmp_path / "owned-avds" / (NAME + ".avd") / ".mcp-owner.json"
        marker.write_text('{"not":"an original signed owner marker"}')
        assert (
            controller.run("status", NAME, handle, job_id=launched["job_id"])["status"] == "blocked"
        )
        assert (
            controller.run("stop", NAME, handle, job_id=launched["job_id"])["status"] == "blocked"
        )
    finally:
        controller.shutdown()


def test_cli_opt_in_requires_owned_scope_and_no_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class Stub:
        def run(self, **kwargs: Any) -> None:
            assert kwargs == {"transport": "http", "host": "127.0.0.1", "port": 8765}

    with monkeypatch.context() as patch:
        patch.setattr(cli, "create_server", lambda **kwargs: calls.append(kwargs) or Stub())
        patch.setattr(cli.platform, "system", lambda: "Linux")
        assert cli.main(["serve"]) == 0
        assert calls == [{}]
        calls.clear()
        for flags in (
            ["serve", "--emulator-lifecycle-plan"],
            ["serve", "--emulator-lifecycle-plan", "--avd-provision"],
            ["serve", "--emulator-lifecycle-plan", "--durable-job-status"],
        ):
            with pytest.raises(SystemExit) as error:
                cli.main(flags)
            assert error.value.code == 2
            assert not calls
        assert not (tmp_path / "jobs").exists()


def test_http_inert_lifecycle_opt_in_can_never_start_real_emulator(tmp_path: Path) -> None:
    target = provider(tmp_path)
    handle = target.provision("create", NAME)["avd"]["handle"]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    code = (
        "import sys\nfrom pathlib import Path\n"
        "from android_mcp_host.server import create_server\n"
        "from android_mcp_host.avd_provisioning import AvdProvisioner\n"
        "from android_mcp_host.emulator_lifecycle import EmulatorLifecycle\n"
        "from android_mcp_host.durable_jobs import DurableJobStore\n"
        "owned=AvdProvisioner(Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3],"
        "api=36,abi='arm64-v8a',source_properties_sha256=sys.argv[4],"
        "system_image_sha256=sys.argv[5],license_sha256=sys.argv[6])\n"
        "controller=EmulatorLifecycle(owned,DurableJobStore(Path(sys.argv[7])),owner=sys.argv[3])\n"
        "create_server(emulator_lifecycle=controller).run("
        "transport='http',host='127.0.0.1',port=int(sys.argv[8]))\n"
    )
    from test_avd_provisioning import LICENSE, SOURCE, SYSTEM

    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            code,
            str(tmp_path / "owned-avds"),
            str(tmp_path / "synthetic-sdk"),
            OWNER,
            hashlib.sha256(SOURCE).hexdigest(),
            hashlib.sha256(SYSTEM).hexdigest(),
            hashlib.sha256(LICENSE).hexdigest(),
            str(tmp_path / "jobs"),
            str(port),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def verify() -> None:
        last: Exception | None = None
        for _ in range(50):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    tools = {tool.name for tool in await client.list_tools()}
                    assert tools == {
                        "device_status",
                        "adb_observe",
                        "adb_develop",
                        "host_emulator_lifecycle",
                    }
                    ready = await client.call_tool(
                        "host_emulator_lifecycle",
                        {"action": "plan", "name": NAME, "handle": handle},
                    )
                    assert ready.structured_content["status"] == "planned"
                    for action in ("start", "stop"):
                        args = {
                            "action": action,
                            "name": NAME,
                            "handle": handle,
                            "request_id": REQUEST,
                            "job_id": "job_" + "z" * 32,
                        }
                        denied = await client.call_tool("host_emulator_lifecycle", args)
                        assert denied.structured_content["status"] == "blocked"
                        assert denied.structured_content["real_emulator_execution_enabled"] is False
                    return
            except (OSError, RuntimeError) as error:
                last = error
                await asyncio.sleep(0.1)
        raise AssertionError(f"Local lifecycle test unavailable: {type(last).__name__}")

    try:
        asyncio.run(verify())
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    assert (tmp_path / "jobs").exists() is not False
