"""Security regression: invalid model strings never echo unbounded diagnostics."""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator

from android_mcp_host.mcp_boundary import get_output_schema
from android_mcp_host.operations import OperationService
from android_mcp_host.probes import ProbeService
from android_mcp_host.server import create_server

SENTINEL = "SYNTHETIC_CANARY_NOT_A_CREDENTIAL"
SUSPECT_DEVICE = "-s" + SENTINEL * 2000 + "\x1b[31m"
SUSPECT_OPERATION = "arbitrary_" + SENTINEL * 2500 + "\x1b[31m"


class NeverDiscover:
    def inspect(self):
        raise AssertionError("Invalid input must be rejected before ADB discovery")


@pytest.mark.parametrize(
    "service,payload,field,code",
    [
        (
            ProbeService(NeverDiscover()),  # type: ignore[arg-type]
            {"device_id": SUSPECT_DEVICE, "probes": ["selinux"]},
            "device_id",
            "INVALID_DEVICE_ID",
        ),
        (
            OperationService(NeverDiscover()),  # type: ignore[arg-type]
            {"device_id": SUSPECT_DEVICE, "action": {"type": "logcat_snapshot"}},
            "device_id",
            "INVALID_DEVICE_ID",
        ),
        (
            OperationService(NeverDiscover()),  # type: ignore[arg-type]
            {"device_id": "SYNTHETIC-01", "action": {"type": SUSPECT_OPERATION}},
            "operation",
            "UNKNOWN_OPERATION",
        ),
    ],
)
def test_invalid_model_strings_are_not_reflected_in_domain_denials(
    service: object, payload: dict[str, object], field: str, code: str
) -> None:
    if isinstance(service, ProbeService):
        response = service.observe(payload["device_id"], payload["probes"])  # type: ignore[arg-type]
        schema = get_output_schema("adb_observe")
    else:
        assert isinstance(service, OperationService)
        response = service.execute(payload["device_id"], payload["action"])  # type: ignore[arg-type]
        schema = get_output_schema("adb_develop")
    assert response["status"] == "error"
    assert response["errors"][0]["code"] == code
    assert response[field] == ""
    assert SENTINEL not in repr(response)
    Draft202012Validator(schema).validate(response)


def test_mcp_denial_does_not_reflect_invalid_operation_even_in_structured_content():
    async def scenario() -> None:
        adb = NeverDiscover()
        server = create_server(
            adb=adb,  # type: ignore[arg-type]
            operations=OperationService(adb),  # type: ignore[arg-type]
        )
        async with Client(server) as client:
            denial = await client.call_tool(
                "adb_develop",
                {"device_id": "SYNTHETIC-01", "action": {"type": SUSPECT_OPERATION}},
            )
            assert denial.is_error is False
            assert denial.structured_content is not None
            assert denial.structured_content["operation"] == ""
            assert denial.structured_content["errors"][0]["code"] == "UNKNOWN_OPERATION"
            assert SENTINEL not in str(denial.structured_content)

    asyncio.run(scenario())
