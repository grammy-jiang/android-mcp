"""H4.b malicious XML, approval and exact-target regressions (fake-only)."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_adb_ui_hierarchy import REQUEST, WIN, builder, inspect, ui_fixture
from test_avd_provisioning import NAME, OWNER

import android_mcp_host.synthetic_ui_hierarchy as module
import android_mcp_host.ui_hierarchy_support as xml
from android_mcp_host.command_runner import bounded_run
from android_mcp_host.synthetic_ui_hierarchy import UiApproval, UiHierarchyService, UiTreeFrame


def valid_node(
    identifier: str = "node_a",
    *,
    cls: str = "android.widget.TextView",
    attrs: str = "",
    contents: str = "",
) -> str:
    return (
        f'<node node-id="{identifier}" class="{cls}" '
        f'focused="false" password="false" {attrs}>{contents}</node>'
    )


def wrap(node: str, *, rotation: str = "0") -> bytes:
    return f'<hierarchy rotation="{rotation}">{node}</hierarchy>'.encode()


@pytest.mark.parametrize(
    "bad",
    [
        wrap(valid_node(), rotation="9"),
        wrap(valid_node(), rotation=""),
        b"<unknown rotation='0'/>",
        b'<hierarchy rotation="0">Sensitive outside nodes</hierarchy>',
        wrap(valid_node(attrs='focused="maybe"')),
        wrap(valid_node(attrs='password="guess"')),
        wrap(valid_node(identifier="bad/name")),
        wrap(valid_node(identifier="node_a", cls="evil/class")),
        wrap(valid_node(attrs='resource-id="bad?query"')),
        wrap(valid_node(attrs='resource-id="a' * 200 + '"')),
        wrap(valid_node(contents="untrusted text")),
        wrap(valid_node() + "outside"),
        wrap(
            valid_node(
                contents='<node node-id="node_x" '
                'class="android.widget.TextView" focused="false" password="false">'
                "hello</node>"
            )
        ),
    ],
)
def test_rejects_malformed_node_state_or_unstructured_text(bad: bytes) -> None:
    with pytest.raises(xml.InvalidUiTree):
        xml.parse_ui_xml(bad)


def test_max_node_depth_nodes_and_output_bytes_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    deep = valid_node("node_0")
    for n in range(1, 14):
        deep = valid_node(f"node_{n}", contents=deep)
    with pytest.raises(xml.InvalidUiTree):
        xml.parse_ui_xml(wrap(deep))
    many = "".join(valid_node(f"node_{n}") for n in range(97))
    with pytest.raises(xml.InvalidUiTree):
        xml.parse_ui_xml(wrap(many))
    with monkeypatch.context() as patch:
        patch.setattr(xml, "MAX_OUTPUT_BYTES", 10)
        with pytest.raises(xml.InvalidUiTree):
            xml.parse_ui_xml(ui_fixture())
    with pytest.raises(xml.InvalidUiTree):
        xml.parse_ui_xml(ui_fixture() * 100)
    with pytest.raises(xml.InvalidUiTree):
        xml.parse_ui_xml(bytearray(ui_fixture()))  # type: ignore[arg-type]


def test_invalid_helper_parameter_types_are_rejected() -> None:
    with pytest.raises(xml.InvalidUiTree):
        xml._text(object())
    with pytest.raises(xml.InvalidUiTree):
        xml._resource(object())
    for value in ("bad?thing", "r" * 140):
        with pytest.raises(xml.InvalidUiTree):
            xml._resource(value)
    assert xml._resource("") == ""
    assert xml._text("") == ""
    assert xml._text("ordinary button") == "ordinary button"


@pytest.mark.parametrize(
    "value",
    [
        "access token: example-value",
        "Authorization=Basic AB2341",
        "password: confidential",
        "session_id=qwerer",
        "OTP 012345",
        "user@example.org",
        "notification: message",
        "normal " * 30,
        "hello\nunsafe",
        "zero\x00byte",
    ],
)
def test_sensitive_content_is_redacted_without_echo(value: str) -> None:
    assert xml._text(value) == xml.REDACTED


def test_security_sensitive_parent_and_edit_text_hide_descendants() -> None:
    raw = wrap(
        '<node node-id="node_parent" class="android.widget.EditText" '
        'focused="false" password="false" text="inferred-secret">'
        '<node node-id="node_child" class="android.widget.TextView" '
        'focused="false" password="false" text="son-should-not-leak"/></node>'
    )
    result = xml.parse_ui_xml(raw)
    assert result["nodes"][0]["text"] == xml.REDACTED
    assert result["nodes"][1]["text"] == xml.REDACTED
    assert result["focused_node_id"] is None


@pytest.mark.parametrize(
    "fields",
    [
        {"owner": "a-foreign-owner"},
        {"avd_handle": "mcpavd_" + "x" * 32},
        {"lifecycle_job_id": "job_" + "z" * 32},
        {"purpose": "different-purpose"},
        {"valid_until_epoch": 0},
        {"valid_until_epoch": math.nan},
        {"valid_until_epoch": math.inf},
        {"valid_until_epoch": True},
        {"valid_until_epoch": "not-a-number"},
    ],
)
def test_t_h4b_02_expired_or_untrusted_approval_never_invokes_reader(
    tmp_path: Path, fields: dict[str, Any]
) -> None:
    worker, live, jobs, handle, lid = builder(tmp_path)
    try:
        grant: dict[str, Any] = {
            "owner": OWNER,
            "avd_handle": handle,
            "lifecycle_job_id": lid,
            "purpose": "synthetic-ui-inspection",
            "valid_until_epoch": time.time() + 120,
        }
        grant.update(fields)
        worker._approval = UiApproval(**grant)
        worker._fixture = lambda *args: pytest.fail("unapproved synthetic UI read")
        denied = inspect(worker, handle, lid)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "CONSENT_REQUIRED"
        assert denied["nodes"] == []
    finally:
        live.shutdown()


def test_constructor_rejects_untrusted_owner(tmp_path: Path) -> None:
    worker, live, jobs, handle, lid = builder(tmp_path)
    try:
        with pytest.raises(ValueError):
            UiHierarchyService(live.provisioner, live, jobs, owner="somebody-else")
        with pytest.raises(ValueError):
            UiHierarchyService(live.provisioner, live, jobs, owner="../../unsafe")
    finally:
        live.shutdown()


def test_grant_expiry_and_broken_clock_are_fail_closed(tmp_path: Path) -> None:
    worker, live, jobs, handle, lid = builder(tmp_path)
    try:
        worker._approval = UiApproval(OWNER, handle, lid, "synthetic-ui-inspection", 1000.0)
        worker._clock = lambda: 999.0
        assert inspect(worker, handle, lid)["status"] == "ok"
        worker._clock = lambda: 1000.0
        assert inspect(worker, handle, lid)["errors"][0]["code"] == "CONSENT_REQUIRED"
        worker._clock = lambda: (_ for _ in ()).throw(ValueError("private date"))
        assert inspect(worker, handle, lid)["errors"][0]["code"] == "CONSENT_REQUIRED"
    finally:
        live.shutdown()


def test_tool_input_and_no_synthetic_execution_blocked(tmp_path: Path) -> None:
    worker, live, jobs, handle, lid = builder(tmp_path)
    try:
        args = (
            worker.submit("tap", NAME, handle, lid, request_id=REQUEST),
            worker.submit("inspect", NAME, handle, "bad", request_id=REQUEST),
            worker.submit("inspect", NAME, handle, lid, request_id=None),
            worker.submit("inspect", NAME, handle, lid, request_id=";evil-input"),
            worker.submit("plan", "physical-emulator", handle, lid),
            worker.submit("inspect", NAME, "USB-DEMO-SERIAL", lid, request_id=REQUEST),
        )
        assert all(result["status"] == "blocked" for result in args)
        assert args[0]["errors"][0]["code"] == "INVALID_ACTION"
        assert args[1]["errors"][0]["code"] == "INVALID_INPUT"
        assert args[4]["errors"][0]["code"] == "NOT_OWNED"
        worker._fixture = None
        assert inspect(worker, handle, lid)["errors"][0]["code"] == "EXECUTION_DISABLED"
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "override",
    [
        {"avd_name": "mismatched"},
        {"avd_handle": "mcpavd_" + "x" * 32},
        {"lifecycle_job_id": "job_" + "z" * 32},
        {"window_id": "untrusted/window"},
        {"window_id": None},
        {"synthetic": False},
        {"secure_window": "false"},
        {"locked_window": 0},
        {"ui_capability_enabled": 1},
    ],
)
def test_untrusted_fixture_metadata_spoofing_is_rejected(
    tmp_path: Path, override: dict[str, Any]
) -> None:
    worker, live, jobs, handle, lid = builder(tmp_path)

    def fake(*args: Any) -> UiTreeFrame:
        frame = UiTreeFrame(
            ui_fixture(),
            NAME,
            handle,
            lid,
            WIN,
            False,
            False,
            True,
            True,
            "normal",
            "normal",
        )
        return replace(frame, **override)

    worker._fixture = fake
    try:
        result = inspect(worker, handle, lid)
        assert result["status"] == "unavailable"
        assert result["errors"][0]["code"] == "BAD_FRAME"
        assert result["nodes"] == []
        assert result["window_id"] is None
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    ("changed", "expected"),
    [
        ({"secure_window": True}, "WINDOW_PROTECTED"),
        ({"locked_window": True}, "WINDOW_PROTECTED"),
        ({"ui_capability_enabled": False}, "CAPABILITY_UNAVAILABLE"),
        ({"mode_before": "locked"}, "MODE_CHANGED"),
        ({"mode_after": "secure"}, "MODE_CHANGED"),
        ({"xml_bytes": b"<hierarchy />"}, "INVALID_XML"),
        ({"xml_bytes": b"x" * 32769}, "INVALID_XML"),
    ],
)
def test_protected_ui_or_invalid_capture_cannot_return_any_nodes(
    tmp_path: Path, changed: dict[str, Any], expected: str
) -> None:
    worker, live, jobs, handle, lid = builder(tmp_path)

    def fake(*args: Any) -> UiTreeFrame:
        frame = UiTreeFrame(
            ui_fixture(), NAME, handle, lid, WIN, False, False, True, True, "normal", "normal"
        )
        return replace(frame, **changed)

    worker._fixture = fake
    try:
        result = inspect(worker, handle, lid)
        assert result["errors"][0]["code"] == expected
        assert result["nodes"] == []
        assert result["node_count"] == 0
        assert "Hello world" not in json.dumps(result)
    finally:
        live.shutdown()


def test_mismatched_runtime_and_missing_running_emulator_deny_read(tmp_path: Path) -> None:
    worker, live, jobs, handle, lid = builder(tmp_path)
    live.shutdown()
    denied = inspect(worker, handle, lid)
    assert denied["status"] == "blocked"
    assert denied["errors"][0]["code"] == "UNVERIFIED_TARGET"
    assert denied["nodes"] == []


def test_synthetic_emulator_stopped_during_ui_read_cannot_expose_stale_data(
    tmp_path: Path,
) -> None:
    worker, live, jobs, handle, lid = builder(tmp_path)

    def interrupted(*args: Any) -> UiTreeFrame:
        live.shutdown()
        return UiTreeFrame(
            ui_fixture(),
            NAME,
            handle,
            lid,
            WIN,
            False,
            False,
            True,
            True,
            "normal",
            "normal",
        )

    worker._fixture = interrupted
    denied = inspect(worker, handle, lid)
    assert denied["status"] == "uncertain"
    assert denied["errors"][0]["code"] == "UNVERIFIED_TARGET"
    assert denied["nodes"] == []


def test_concurrent_lock_unavailable_or_error_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker, live, jobs, handle, lid = builder(tmp_path)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(module, "claim_fixture_lock", lambda *args: None)
            assert inspect(worker, handle, lid)["errors"][0]["code"] == "BUSY"
        with monkeypatch.context() as patch:

            def unavailable(*args: Any) -> None:
                raise OSError("PRIVATE-HOST-PATH")

            patch.setattr(module, "claim_fixture_lock", unavailable)
            result = inspect(worker, handle, lid)
            assert result["errors"][0]["code"] == "BUSY"
            assert "PRIVATE-HOST-PATH" not in json.dumps(result)
    finally:
        live.shutdown()


def test_hung_synthetic_uiautomator_process_is_killed_and_returns_timeout(
    tmp_path: Path,
) -> None:
    script = tmp_path / "fake-ui-hung.py"
    pidfile = tmp_path / "fake-ui-pid"
    script.write_text(
        "import os,sys,time\n"
        "from pathlib import Path\n"
        "Path(sys.argv[1]).write_text(str(os.getpid()))\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    worker, live, jobs, handle, lid = builder(tmp_path)

    def hung(name: str, handle: str, lid: str, seconds: float, limit: int) -> UiTreeFrame:
        assert seconds == 3.0 and limit == 32768
        bounded_run([sys.executable, str(script), str(pidfile)], 0.5, 1024)
        pytest.fail("Hung synthetic runner unexpectedly completed")

    worker._fixture = hung
    try:
        failed = inspect(worker, handle, lid)
        assert failed["status"] == "uncertain"
        assert failed["errors"][0]["code"] == "TIMEOUT"
        assert failed["nodes"] == []
        assert pidfile.exists()
        pid = int(pidfile.read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        live.shutdown()


def test_schema_loader_fails_for_invalid_packaged_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InvalidResource:
        def joinpath(self, name: str) -> InvalidResource:
            assert name == "host-ui-hierarchy.v1.schema.json"
            return self

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return "[]"

    with monkeypatch.context() as patch:
        patch.setattr(module, "files", lambda _: InvalidResource())
        with pytest.raises(ValueError):
            module.get_ui_hierarchy_schema()


def test_negative_security_flags_are_false_in_all_denial_responses(tmp_path: Path) -> None:
    worker, live, jobs, handle, lid = builder(tmp_path, consent=False)
    try:
        for output in (
            worker.submit("plan", NAME, handle, lid),
            inspect(worker, handle, lid),
            worker.submit("bad-action", NAME, handle, lid),
        ):
            assert output["real_ui_access_enabled"] is False
            assert output["accessibility_bypass_enabled"] is False
            assert output["physical_device_writes_enabled"] is False
            assert output["raw_xml_returned"] is False
            assert output["nodes"] == []
    finally:
        live.shutdown()


@pytest.mark.parametrize("attribute", ["focused", "password"])
def test_invalid_boolean_flags_rejected_after_successful_xml_parse(attribute: str) -> None:
    data = wrap(valid_node())
    before = f'{attribute}="false"'.encode("ascii")
    after = f'{attribute}="invalid"'.encode("ascii")
    assert before in data
    invalid = data.replace(before, after)
    with pytest.raises(xml.InvalidUiTree):
        xml.parse_ui_xml(invalid)


def test_approval_expiring_during_read_cannot_release_ui_data(tmp_path: Path) -> None:
    worker, live, jobs, handle, lid = builder(tmp_path)
    clock = [1000.0]
    worker._clock = lambda: clock[0]
    worker._approval = UiApproval(OWNER, handle, lid, "synthetic-ui-inspection", 1010.0)

    def expire(name: str, handle: str, lid: str, seconds: float, limit: int) -> UiTreeFrame:
        clock[0] = 1011.0
        return UiTreeFrame(
            ui_fixture(), name, handle, lid, WIN, False, False, True, True, "normal", "normal"
        )

    worker._fixture = expire
    try:
        denied = inspect(worker, handle, lid)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "CONSENT_REQUIRED"
        assert denied["nodes"] == []
    finally:
        live.shutdown()


def test_untyped_action_and_failing_fake_process_return_typed_denial(tmp_path: Path) -> None:
    worker, live, jobs, handle, lid = builder(tmp_path)
    try:
        invalid = worker.submit({}, NAME, handle, lid, request_id=REQUEST)  # type: ignore[arg-type]
        assert invalid["status"] == "blocked"
        assert invalid["errors"][0]["code"] == "INVALID_ACTION"
        worker._fixture = lambda *args: (_ for _ in ()).throw(
            subprocess.CalledProcessError(1, "fixture-ui")
        )
        denied = inspect(worker, handle, lid)
        assert denied["status"] == "unavailable"
        assert denied["errors"][0]["code"] == "RUNNER_FAILED"
    finally:
        live.shutdown()
