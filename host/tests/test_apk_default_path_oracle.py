"""No APK-root configuration must not expose host file existence through MCP."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator

from android_mcp_host.command_plan import PlanError, prepare_action
from android_mcp_host.mcp_boundary import get_output_schema
from android_mcp_host.operations import OperationService
from android_mcp_host.server import create_server


class NeverDiscover:
    def inspect(self):
        raise AssertionError("No APK roots: do not probe ADB or target filesystem")


def _code(path: Path) -> str:
    plan = prepare_action({"type": "install_apk", "apk_path": str(path)})
    assert isinstance(plan, PlanError)
    return plan.code


def test_default_configuration_does_not_reveal_apk_path_existence(tmp_path: Path) -> None:
    existing = tmp_path / "existing.apk"
    existing.write_bytes(b"PK\x03\x04synthetic-archive")
    missing = tmp_path / "nonexistent.apk"
    symlink = tmp_path / "linked.apk"
    symlink.symlink_to(existing)
    # With no approved roots, denial cannot reveal whether a path exists.
    assert _code(existing) == _code(missing) == _code(symlink) == "APK_NOT_ALLOWED"


def test_default_configuration_never_resolves_apk_paths(tmp_path: Path, monkeypatch) -> None:
    def blocked(*_args, **_kwargs):
        raise AssertionError("The default denial must not inspect local file paths")

    monkeypatch.setattr(Path, "resolve", blocked)
    monkeypatch.setattr(Path, "is_symlink", blocked)
    plan = prepare_action({"type": "install_apk", "apk_path": str(tmp_path / "anything.apk")})
    assert isinstance(plan, PlanError)
    assert plan.code == "APK_NOT_ALLOWED"


def test_default_denial_remains_structured_and_never_launches_adb(tmp_path: Path) -> None:
    existing = tmp_path / "file.apk"
    existing.write_bytes(b"PK\x03\x04synthetic")
    missing = tmp_path / "missing.apk"

    async def scenario() -> None:
        adb = NeverDiscover()
        async with Client(
            create_server(adb=adb, operations=OperationService(adb))  # type: ignore[arg-type]
        ) as client:
            schema = get_output_schema("adb_develop")
            for path in (existing, missing):
                result = await client.call_tool(
                    "adb_develop",
                    {
                        "device_id": "SYNTHETIC-01",
                        "action": {"type": "install_apk", "apk_path": str(path)},
                    },
                )
                assert not result.is_error
                assert result.structured_content is not None
                Draft202012Validator(schema).validate(result.structured_content)
                assert result.structured_content["status"] == "error"
                assert result.structured_content["errors"][0]["code"] == "APK_NOT_ALLOWED"
                assert result.structured_content["command"] == []

    asyncio.run(scenario())


@pytest.mark.parametrize("bad_path", [None, "", "relative.apk", "/tmp/not-an-apk.zip"])
def test_lexically_invalid_paths_remain_invalid_without_filesystem_access(bad_path):
    plan = prepare_action({"type": "install_apk", "apk_path": bad_path})
    assert isinstance(plan, PlanError)
    assert plan.code == "INVALID_APK_PATH"
