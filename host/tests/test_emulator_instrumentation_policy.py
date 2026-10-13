"""H3.e synthetic-only validation and malformed private report denials."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path
from typing import Any

import pytest
from test_avd_provisioning import NAME, OWNER, provider
from test_emulator_instrumentation_jobs import (
    APK_MIME,
    COMPONENT,
    INSTRUMENT_OWNER,
    RUN_REQUEST,
    setup_fixture,
    success,
    synthetic_test_apk,
)

from android_mcp_host.emulator_instrumentation_jobs import (
    InstrumentationJobs,
    get_instrumentation_schema,
)
from android_mcp_host.emulator_instrumentation_support import (
    parse_fixture_result,
    valid_component,
    valid_digest,
)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "org.example",
        "../unsafe",
        "org.example/",
        "org.example/../../unsafe",
        "org.example/Name --evil",
        "com.a/.NotAbsolute",
        "a/b",
        "/x",
        "x" * 500,
        "com.example.Fixture/com.example.Fixture.Runner -e class",
    ],
)
def test_component_allowlist_rejects_potential_shell_or_adb_flags(value: str) -> None:
    assert not valid_component(value)
    assert valid_component(COMPONENT)


@pytest.mark.parametrize("value", ["a" * 63, "A" * 64, "z" * 64, "", None, 123])
def test_sha256_digest_is_fixed_lowercase_hex(value: Any) -> None:
    assert not valid_digest(value)
    assert valid_digest("a" * 64)


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "not-json",
        "{}",
        "[]",
        '{"passed":1,"failed":0,"total":1}',
        '{"passed":1,"failed":0,"total":1,"synthetic":false}',
        '{"passed":true,"failed":0,"total":1,"synthetic":true}',
        '{"passed":1,"failed":0,"total":0,"synthetic":true}',
        '{"passed":1,"failed":0,"total":257,"synthetic":true}',
        '{"passed":2,"failed":0,"total":1,"synthetic":true}',
        '{"passed":0,"failed":-1,"total":1,"synthetic":true}',
        '{"passed":0,"failed":0,"total":1,"synthetic":true}',
        '{"passed":1,"failed":0,"total":1,"synthetic":true,"secret":"do-not-log"}',
        "X" * 9000,
    ],
)
def test_synthetic_test_result_parser_is_finite_and_exact(payload: str) -> None:
    assert parse_fixture_result(payload) is None


def test_valid_test_result_parser_only_yields_counts() -> None:
    output = '{"passed":9,"failed":2,"total":11,"synthetic":true}'
    assert parse_fixture_result(output) == {"passed": 9, "failed": 2, "total": 11}


def test_instrumentation_schema_must_be_object(monkeypatch: pytest.MonkeyPatch) -> None:
    from android_mcp_host import emulator_instrumentation_jobs as module

    class Resource:
        def joinpath(self, name: str) -> Resource:
            assert name == "host-emulator-instrumentation.v1.schema.json"
            return self

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return "[]"

    monkeypatch.setattr(module, "files", lambda _: Resource())
    with pytest.raises(ValueError, match="Invalid packaged"):
        get_instrumentation_schema()


@pytest.mark.parametrize("value", [-1, 0, 10.5, "3", True, float("nan"), float("inf")])
def test_execution_timeout_must_be_bounded_finite_number(
    tmp_path: Path,
    value: Any,
) -> None:
    work, live, jobs, artifacts, handle, lid, apk, sha = setup_fixture(
        tmp_path,
        running=False,
    )
    with pytest.raises(ValueError, match="deadline"):
        InstrumentationJobs(
            live.provisioner,
            live,
            jobs,
            artifacts,
            owner=OWNER,
            artifact_owner=INSTRUMENT_OWNER,
            timeout_s=value,
        )
    live.shutdown()


def test_cross_owner_or_mismatched_lifecycle_controller_is_denied(tmp_path: Path) -> None:
    task, live, jobs, artifacts, handle, lid, apk, sha = setup_fixture(tmp_path, running=False)
    for owner, artifact_owner in (("foreign-owner", INSTRUMENT_OWNER), (OWNER, "invalid/owner")):
        with pytest.raises(ValueError):
            InstrumentationJobs(
                live.provisioner,
                live,
                jobs,
                artifacts,
                owner=owner,
                artifact_owner=artifact_owner,
            )
    foreign = provider(tmp_path / "another-owned")
    with pytest.raises(ValueError):
        InstrumentationJobs(
            foreign,
            live,
            jobs,
            artifacts,
            owner=OWNER,
            artifact_owner=INSTRUMENT_OWNER,
        )
    live.shutdown()


def test_foreign_mime_corrupt_zip_and_tampered_digest_denied(tmp_path: Path) -> None:
    task, live, jobs, artifacts, handle, lid, apk, sha = setup_fixture(tmp_path, running=False)
    try:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as zipped:
            zipped.writestr("../escape", b"invalid private APK member")
        hostile = stream.getvalue()
        other = artifacts.put(INSTRUMENT_OWNER, hostile, mime_type=APK_MIME)
        corrupt = task.submit(
            "plan",
            NAME,
            handle,
            lid,
            other["handle"],
            hashlib.sha256(hostile).hexdigest(),
            COMPONENT,
        )
        assert corrupt["status"] == "blocked"
        assert corrupt["errors"][0]["code"] == "BAD_ARTIFACT"
        mime = artifacts.put(
            INSTRUMENT_OWNER, synthetic_test_apk(), mime_type="application/octet-stream"
        )
        denied = task.submit("plan", NAME, handle, lid, mime["handle"], sha, COMPONENT)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "BAD_ARTIFACT"
    finally:
        live.shutdown()


def test_synthetic_only_executor_must_have_positive_verified_lifecycle(tmp_path: Path) -> None:
    task, live, jobs, artifacts, handle, lid, apk, sha = setup_fixture(
        tmp_path,
        runner=success,
    )
    try:
        live.shutdown()
        denied = task.submit("run", NAME, handle, lid, apk, sha, COMPONENT, request_id=RUN_REQUEST)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "UNVERIFIED_EMULATOR"
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


def test_run_disabled_in_production_even_with_valid_private_apk(tmp_path: Path) -> None:
    task, live, jobs, artifacts, handle, lid, apk, sha = setup_fixture(
        tmp_path,
        running=False,
    )
    try:
        assert task.submit("plan", NAME, handle, lid, apk, sha, COMPONENT)["status"] == "planned"
        denied = task.submit("run", NAME, handle, lid, apk, sha, COMPONENT, request_id=RUN_REQUEST)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "EXECUTION_DISABLED"
        assert jobs.list_status(OWNER) == []
    finally:
        live.shutdown()


def test_completely_invalid_action_request_never_has_side_effect(tmp_path: Path) -> None:
    task, live, jobs, artifacts, handle, lid, apk, sha = setup_fixture(
        tmp_path,
        running=False,
    )
    try:
        for action, request in (
            ("install", RUN_REQUEST),
            ("run", "bad/id"),
            ("run", ""),
            ("run", "x" * 255),
        ):
            denied = task.submit(action, NAME, handle, lid, apk, sha, COMPONENT, request_id=request)
            assert denied["status"] == "blocked"
        assert jobs.list_status(OWNER) == []
    finally:
        live.shutdown()
