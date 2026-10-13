"""Actual loopback MCP and child-process H2.f fake Gradle acceptance fixture."""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
from pathlib import Path

from fastmcp import Client
from test_host_gradle_build_job import ARTIFACT_OWNER, OWNER, REVISION, make


def test_real_loopback_http_invokes_only_fixed_offline_local_fake_gradle(
    tmp_path: Path,
) -> None:
    builder, preflight, _, store, root = make(tmp_path)
    assert builder is not None
    trace = tmp_path / "fake-gradle-trace.txt"
    # Executed script is created inside a disposable synthetic project only.
    gradlew = root / "android" / "gradlew"
    gradlew.write_text(
        "#!/bin/sh\n"
        f"printf 'invocation\\n' >> '{trace}'\n"
        f"printf '%s\\n' \"$@\" >> '{trace}'\n"
        "echo 'synthetic lint run successful'\n",
        encoding="utf-8",
    )
    gradlew.chmod(0o700)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    program = (
        "import sys\n"
        "from pathlib import Path\n"
        "from android_mcp_host.server import create_server\n"
        "from android_mcp_host.android_build_preflight import TASKS\n"
        "from android_mcp_host.durable_jobs import DurableJobStore\n"
        "from android_mcp_host.private_artifact_store import PrivateArtifactStore\n"
        "from android_mcp_host.controlled_build_jobs import ControlledBuildJobs\n"
        "class Preflight:\n"
        "  def plan(self,action,variant):\n"
        "    return {'status':'planned','project_root':sys.argv[1],"
        "'expected_revision':sys.argv[2], 'observed_revision':sys.argv[2],"
        "'wrapper_sha256':sys.argv[3],'dirty':False,'variant':variant,"
        "'action':action,'tasks':list(TASKS[action]),'execution_enabled':False}\n"
        "root=Path(sys.argv[1])\n"
        "engine=ControlledBuildJobs(preflight=Preflight(),"
        "jobs=DurableJobStore(Path(sys.argv[4]),lease_seconds=180),"
        "artifacts=PrivateArtifactStore(Path(sys.argv[5])),"
        "root=root,approved_revision=sys.argv[2],wrapper_sha256=sys.argv[3],"
        "owner=sys.argv[6],artifact_owner=sys.argv[7])\n"
        "create_server(build_jobs=engine).run("
        "transport='http',host='127.0.0.1',port=int(sys.argv[8]))\n"
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            program,
            str(root),
            REVISION,
            preflight.digest,
            str(tmp_path / "private-jobs"),
            str(tmp_path / "private-artifacts"),
            OWNER,
            ARTIFACT_OWNER,
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )

    async def check() -> None:
        last: Exception | None = None
        for _ in range(45):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    tools = {item.name for item in await client.list_tools()}
                    assert tools == {
                        "device_status",
                        "adb_observe",
                        "adb_develop",
                        "host_gradle_build",
                    }
                    reply = await client.call_tool(
                        "host_gradle_build",
                        {"action": "lint_debug", "request_id": "http-build-fixture"},
                    )
                    assert not reply.is_error
                    first = reply.structured_content
                    assert first["status"] == "ok"
                    assert first["state"] == "succeeded"
                    assert first["device_mutation_enabled"] is False
                    assert str(tmp_path) not in json.dumps(first)
                    assert trace.exists()
                    again = await client.call_tool(
                        "host_gradle_build",
                        {"action": "lint_debug", "request_id": "http-build-fixture"},
                    )
                    assert again.structured_content["job_id"] == first["job_id"]
                    assert len(trace.read_text().split("invocation")) == 2
                    return
            except (ConnectionError, OSError, RuntimeError) as error:
                last = error
                await asyncio.sleep(0.1)
        raise AssertionError(f"Controlled Host HTTP fake Gradle failed: {type(last).__name__}")

    try:
        asyncio.run(check())
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)

    payload = trace.read_text()
    assert "--offline" in payload and "--no-daemon" in payload
    assert ":app:lintDebug" in payload and "-PenableAndroidApp=true" in payload
    assert "adb" not in payload and "install" not in payload
    assert store.list_metadata(ARTIFACT_OWNER) != []
