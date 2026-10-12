"""I1c: publish typed engineering actions, without executing device mutations."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastmcp import Client
from jsonschema import Draft202012Validator

from android_mcp_host.adb import AdbReport, Device
from android_mcp_host.command_runner import RunResult
from android_mcp_host.mcp_boundary import get_output_schema
from android_mcp_host.operations import MAX_RESULT_CHARS, OperationService
from android_mcp_host.server import create_server

DEVICE = "SYNTHETIC-01"
CANONICAL_ACTION = (
    Path(__file__).resolve().parents[2] / "contracts/adb-development-action.v1.schema.json"
)


class FakeAdb:
    def inspect(self) -> AdbReport:
        return AdbReport(True, "/synthetic/adb", "37", None, (Device(DEVICE, "device", {}),))


class FakeRunner:
    def __init__(self, output: str = "synthetic details\n"):
        self.output = output
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], timeout: float, limit: int) -> RunResult:
        self.calls.append(list(argv))
        return RunResult(0, self.output, "", False)


async def _client_checks(output: str = "synthetic details\n") -> None:
    adb = FakeAdb()
    runner = FakeRunner(output)
    server = create_server(adb=adb, operations=OperationService(adb, runner=runner))  # type: ignore[arg-type]
    async with Client(server) as client:
        catalog = {t.name: t for t in await client.list_tools()}
        assert sorted(catalog) == ["adb_develop", "adb_observe", "device_status"]
        tool = catalog["adb_develop"]
        assert tool.output_schema is not None
        published = tool.output_schema
        canonical_output = get_output_schema("adb_develop")
        assert published["$id"] == canonical_output["$id"]
        assert published["additionalProperties"] is False
        assert set(published["required"]) == set(canonical_output["required"])
        Draft202012Validator.check_schema(published)

        # The input schema is derived from canonical action definitions but
        # must NOT promote domain denials to MCP validation errors.
        action = tool.input_schema["properties"]["action"]
        expected = json.loads(CANONICAL_ACTION.read_text(encoding="utf-8"))
        assert action["$id"] == expected["$id"]
        assert len(action["oneOf"]) == 4
        assert {shape["properties"]["type"]["const"] for shape in action["oneOf"]} == {
            "logcat_snapshot",
            "package_details",
            "instrument_test",
            "install_apk",
        }
        Draft202012Validator.check_schema(tool.input_schema)
        valid_examples = [
            {"type": "logcat_snapshot", "lines": 20},
            {"type": "package_details", "package": "com.example.app"},
            {
                "type": "instrument_test",
                "package": "com.example.test",
                "runner": "com.example.Runner",
            },
            {"type": "install_apk", "apk_path": "/tmp/synthetic/test.apk"},
        ]
        for example in valid_examples:
            assert Draft202012Validator(tool.input_schema).is_valid(
                {"device_id": DEVICE, "action": example}
            )

        status = await client.call_tool(
            "adb_develop",
            {
                "device_id": DEVICE,
                "action": {"type": "package_details", "package": "com.example.app"},
            },
        )
        assert not status.is_error
        assert isinstance(status.structured_content, dict)
        Draft202012Validator(published).validate(status.structured_content)
        assert status.structured_content["status"] == "ok"
        assert runner.calls == [
            ["/synthetic/adb", "-s", DEVICE, "shell", "dumpsys", "package", "com.example.app"]
        ]

        # Mutation preview is not an executed device operation.
        planned = await client.call_tool(
            "adb_develop",
            {
                "device_id": DEVICE,
                "action": {
                    "type": "instrument_test",
                    "package": "com.example.test",
                    "runner": "com.example.Runner",
                },
                "dry_run": True,
            },
        )
        assert not planned.is_error
        assert isinstance(planned.structured_content, dict)
        Draft202012Validator(published).validate(planned.structured_content)
        assert planned.structured_content["status"] == "planned"
        assert planned.structured_content["mutating"] is True
        assert len(runner.calls) == 1

        denied = await client.call_tool(
            "adb_develop",
            {
                "device_id": DEVICE,
                "action": {
                    "type": "instrument_test",
                    "package": "com.example.test",
                    "runner": "com.example.Runner",
                },
            },
        )
        assert not denied.is_error
        assert isinstance(denied.structured_content, dict)
        Draft202012Validator(published).validate(denied.structured_content)
        assert denied.structured_content["errors"][0]["code"] == "MUTATION_DISABLED"
        assert len(runner.calls) == 1

        unknown = await client.call_tool(
            "adb_develop",
            {"device_id": DEVICE, "action": {"type": "arbitrary_shell", "command": "id"}},
        )
        assert not unknown.is_error
        assert isinstance(unknown.structured_content, dict)
        Draft202012Validator(published).validate(unknown.structured_content)
        assert unknown.structured_content["errors"][0]["code"] == "UNKNOWN_OPERATION"
        assert len(runner.calls) == 1


def test_develop_catalog_schema_and_domain_semantics():
    asyncio.run(_client_checks())


def test_develop_output_limit_still_returns_structured_partial():
    async def check() -> None:
        adb = FakeAdb()
        runner = FakeRunner("x" * (MAX_RESULT_CHARS + 40))
        server = create_server(adb=adb, operations=OperationService(adb, runner=runner))  # type: ignore[arg-type]
        async with Client(server) as client:
            tool = {t.name: t for t in await client.list_tools()}["adb_develop"]
            assert tool.output_schema is not None
            result = await client.call_tool(
                "adb_develop",
                {"device_id": DEVICE, "action": {"type": "logcat_snapshot", "lines": 20}},
            )
            assert not result.is_error
            assert isinstance(result.structured_content, dict)
            Draft202012Validator(tool.output_schema).validate(result.structured_content)
            assert result.structured_content["status"] == "partial"
            assert result.structured_content["result"]["truncated"] is True
            assert result.structured_content["errors"][0]["code"] == "OUTPUT_LIMIT"
            assert len(runner.calls) == 1

    asyncio.run(check())
