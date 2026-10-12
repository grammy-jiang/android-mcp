"""Complete HTTP MCP -> subprocess -> fake ADB smoke without Android hardware.

Run the actual Host CLI in a separate process and invoke MCP over loopback.
This checks the wire path and the subprocess boundary together on macOS/Linux.
"""

import asyncio
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

from fastmcp import Client

FAKE_ADB = r"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
trace = os.environ.get("ANDROID_MCP_FAKE_ADB_TRACE")
if trace:
    with Path(trace).open("a", encoding="utf-8") as out:
        out.write(json.dumps(args) + "\n")

if args == ["version"]:
    print("Android Debug Bridge version 1.0.41")
    print("Version 37.0.1-test")
elif args == ["devices", "-l"]:
    print("List of devices attached")
    print("TEST-DEVICE-01 device product:fixture model:TestTablet transport_id:1")
elif args == ["-s", "TEST-DEVICE-01", "shell", "getenforce"]:
    print("Enforcing")
elif args == ["-s", "TEST-DEVICE-01", "logcat", "-d", "-t", "20", "-v", "threadtime"]:
    print("10-12 12:00:00.000 1000 1000 I Test: simulated")
else:
    print("Forbidden or unrecognised fake ADB command", file=sys.stderr)
    raise SystemExit(41)
"""


def test_real_http_mcp_uses_only_allowlisted_subprocesses(tmp_path: Path):
    adb = tmp_path / "adb"
    trace = tmp_path / "adb-requests.jsonl"
    adb.write_text(FAKE_ADB, encoding="utf-8")
    adb.chmod(0o700)
    env = os.environ.copy()
    env["PATH"] = str(tmp_path) + os.pathsep + env.get("PATH", "")
    env["ANDROID_MCP_FAKE_ADB_TRACE"] = str(trace)

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    process = subprocess.Popen(
        [sys.executable, "-m", "android_mcp_host", "serve", "--port", str(port)],
        env=env,
        cwd=Path(__file__).resolve().parents[1],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def run_checks():
        last: Exception | None = None
        for _ in range(40):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    names = [tool.name for tool in await client.list_tools()]
                    assert names == ["device_status", "adb_observe", "adb_develop"]

                    status = await client.call_tool("device_status", {})
                    assert not status.is_error
                    assert status.data["devices"][0]["device_id"] == "TEST-DEVICE-01"

                    seen = await client.call_tool(
                        "adb_observe",
                        {"device_id": "TEST-DEVICE-01", "probes": ["selinux"]},
                    )
                    assert not seen.is_error
                    assert seen.data["status"] == "ok"
                    assert seen.data["results"][0]["fields"]["enforcement"] == "Enforcing"

                    log = await client.call_tool(
                        "adb_develop",
                        {
                            "device_id": "TEST-DEVICE-01",
                            "action": {"type": "logcat_snapshot", "lines": 20},
                        },
                    )
                    assert not log.is_error
                    assert log.data["status"] == "ok"
                    assert "simulated" in log.data["result"]["stdout"]

                    before_invalid = trace.read_text(encoding="utf-8").count("\n")
                    invalid = await client.call_tool(
                        "adb_observe",
                        {"device_id": "-s", "probes": ["selinux"]},
                    )
                    assert not invalid.is_error
                    assert invalid.data["errors"][0]["code"] == "INVALID_DEVICE_ID"
                    assert trace.read_text(encoding="utf-8").count("\n") == before_invalid

                    rejected = await client.call_tool(
                        "adb_develop",
                        {
                            "device_id": "TEST-DEVICE-01",
                            "action": {
                                "type": "instrument_test",
                                "package": "com.example.test",
                                "runner": "com.example.TestRunner",
                            },
                        },
                    )
                    assert not rejected.is_error
                    assert rejected.data["errors"][0]["code"] == "MUTATION_DISABLED"
                    return
            except Exception as error:
                last = error
                await asyncio.sleep(0.1)
        raise AssertionError(f"Host HTTP MCP did not complete fake ADB smoke: {last!r}")

    try:
        asyncio.run(run_checks())
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)

    commands = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    assert ["-s", "TEST-DEVICE-01", "shell", "getenforce"] in commands
    assert ["-s", "TEST-DEVICE-01", "logcat", "-d", "-t", "20", "-v", "threadtime"] in commands
    assert all("install" not in cmd and "instrument" not in cmd for cmd in commands)
    assert all("shell" not in cmd or cmd[-1] == "getenforce" for cmd in commands)
