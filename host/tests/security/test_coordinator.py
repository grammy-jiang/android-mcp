"""H3 coordinator tests use fake Native control and ADB; no device changes."""

from __future__ import annotations

import hashlib
import subprocess
import threading
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from android_mcp_host.command_plan import Plan
from android_mcp_host.command_runner import RunResult
from android_mcp_host.security.approvals import ApprovalVerifier, encode_signed_envelope_for_tests
from android_mcp_host.security.audit import AuditJournal
from android_mcp_host.security.coordinator import SecureMutationCoordinator
from android_mcp_host.security.identity import fingerprint


class FakeNative:
    def __init__(self):
        self.acquired = []
        self.released = []
        self.healthy = True
        self.allow = True

    def acquire(self, device_id, fence, plan_digest, ttl_s):
        self.acquired.append((device_id, fence, plan_digest, ttl_s))
        return object() if self.allow else None

    def is_current(self, handle):
        return self.healthy

    def release(self, handle):
        self.released.append(handle)


class FakeInbox:
    def __init__(self, signer):
        self.signer = signer
        self.calls = []
        self.fail = False
        self.return_none = False

    def fetch(self, device, digest):
        self.calls.append((device, digest))
        if self.fail:
            raise OSError("secret")
        if self.return_none:
            return None
        return encode_signed_envelope_for_tests(
            {
                "version": 1,
                "nonce": "a" * 32,
                "device_id": device,
                "operator": "physical-operator",
                "plan_digest": digest,
                "not_before": 900,
                "expires_at": 1100,
            },
            self.signer,
        )


PLAN = Plan(
    "instrument_test",
    ("shell", "am", "instrument", "-w", "com.sample.tests/Runner"),
    True,
    2.0,
    "com.sample.tests/Runner",
)


def _setup(secure_dir, store, *, inbox=True, native=True, allowed_roots=()):
    signer = Ed25519PrivateKey.generate()
    public = signer.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    grant = ApprovalVerifier({"physical-operator": public}, store, clock=lambda: 1000)
    bridge = FakeNative()
    mailbox = FakeInbox(signer)
    journal = AuditJournal(store, clock=lambda: 1000)
    stagedir = secure_dir / "staging"
    stagedir.mkdir(mode=0o700, exist_ok=True)
    service = SecureMutationCoordinator(
        store=store,
        approvals=grant,
        journal=journal,
        grant_inbox=mailbox if inbox else None,
        native_lease=bridge if native else None,
        allowed_apk_roots=allowed_roots,
        staging_dir=stagedir,
    )
    return service, bridge, mailbox, journal


def _perform(service, plan=PLAN, runner=None):
    if runner is None:

        def runner(*_):
            return RunResult(0, "OK (1 test)\nINSTRUMENTATION_CODE: -1", "", False)

    return service.perform(
        device_id="ABC-1", plan=plan, binary="/mock/adb", runner=runner, output_byte_limit=8192
    )


def test_default_refuses_without_native_bridge_or_grant_inbox(secure_dir, store):
    calls = []
    for native, inbox in ((True, False), (False, True), (False, False)):
        service, *_ = _setup(secure_dir, store, native=native, inbox=inbox)
        outcome = _perform(service, runner=lambda *_: calls.append(1))
        assert outcome.status == "blocked"
        assert outcome.code == "MUTATION_DISABLED"
    assert calls == []


def test_valid_exact_approval_runs_once_and_audits(secure_dir, store):
    service, native, inbox, journal = _setup(secure_dir, store)
    calls = []

    def runner(argv, timeout, cap):
        calls.append((argv, timeout, cap))
        return RunResult(0, "OK (1 test)\nINSTRUMENTATION_CODE: -1", "", False)

    result = _perform(service, runner=runner)
    assert result.status == "completed"
    assert len(calls) == 1
    assert calls[0][0] == ["/mock/adb", "-s", "ABC-1", *PLAN.argv_suffix]
    assert [entry[0] for entry in inbox.calls] == ["ABC-1"]
    assert len(native.released) == 1
    assert journal.verify_chain()
    manual_lease = store.acquire("ABC-1")
    assert manual_lease is not None
    assert store.release(manual_lease)
    second = _perform(service, runner=runner)
    assert second.code == "APPROVAL_DENIED"  # grant replay, no second ADB call
    assert len(calls) == 1


def test_denied_grant_cannot_execute(secure_dir, store):
    service, _, inbox, journal = _setup(secure_dir, store)
    inbox.return_none = True
    result = _perform(service, runner=lambda *_: pytest.fail("ran without approval"))
    assert result.status == "blocked" and result.code == "OPERATOR_APPROVAL_REQUIRED"
    assert journal.verify_chain()


def test_native_lease_must_be_obtained_and_current(secure_dir, store):
    service, bridge, *_ = _setup(secure_dir, store)
    bridge.allow = False
    denied = _perform(service, runner=lambda *_: pytest.fail("missing lease"))
    assert denied.code == "NATIVE_LEASE_UNAVAILABLE"
    bridge.allow = True
    bridge.healthy = False
    denied = _perform(service, runner=lambda *_: pytest.fail("stale lease"))
    assert denied.code == "LEASE_EXPIRED"
    assert len(bridge.released) == 1


def test_inbox_failure_is_fail_closed(secure_dir, store):
    service, _, inbox, *_ = _setup(secure_dir, store)
    inbox.fail = True
    denied = _perform(service, runner=lambda *_: pytest.fail("inbox inaccessible"))
    assert denied.status == "blocked"


def test_unsupported_action_or_invalid_runtime_config_cannot_run(secure_dir, store):
    service, *_ = _setup(secure_dir, store)
    read_only = Plan("logcat_snapshot", ("logcat", "-d"), False, 1, "logcat")
    assert _perform(service, read_only).code == "MUTATION_REQUIRED"
    assert (
        service.perform(
            device_id="ABC-1", plan=PLAN, binary="", runner=lambda *_: None, output_byte_limit=1024
        ).code
        == "INVALID_EXECUTION_CONFIG"
    )
    assert (
        service.perform(
            device_id="ABC-1",
            plan=PLAN,
            binary="adb",
            runner=lambda *_: None,
            output_byte_limit=100,
        ).code
        == "INVALID_EXECUTION_CONFIG"
    )


def test_runner_exception_never_reports_success(secure_dir, store):
    service, *_ = _setup(secure_dir, store)
    result = _perform(
        service, runner=lambda *_: (_ for _ in ()).throw(subprocess.TimeoutExpired("adb", 2))
    )
    assert result.status == "error"
    assert result.code == "ADB_EXECUTION_FAILED"


def test_artifact_staging_and_digest_bound_before_install(secure_dir, store):
    root = secure_dir / "approved"
    root.mkdir(mode=0o700)
    apk = root / "demo.apk"
    apk.write_bytes(b"PK\x03\x04" + b"approved" * 100)
    plan = Plan("install_apk", ("install", "-r", str(apk)), True, 2, apk.name)
    svc, native, inbox, journal = _setup(secure_dir, store, allowed_roots=(root,))
    observations = []

    def runner(argv, timeout, cap):
        observations.append((argv[-1], Path(argv[-1]).read_bytes()))
        assert argv[-1] != str(apk)
        assert argv[-1].endswith(".apk")
        return RunResult(0, "Success\n", "", False)

    result = _perform(svc, plan=plan, runner=runner)
    assert result.status == "completed"
    assert observations[0][1] == apk.read_bytes()
    assert not Path(observations[0][0]).exists()
    assert inbox.calls[0][1] == fingerprint(
        device_id="ABC-1",
        kind="install_apk",
        argv_suffix=plan.argv_suffix,
        artifact_sha256=hashlib.sha256(apk.read_bytes()).hexdigest(),
    )
    assert journal.verify_chain()


def test_bad_apk_is_never_executed(secure_dir, store):
    root = secure_dir / "approved"
    root.mkdir(mode=0o700)
    bad = root / "bad.apk"
    bad.write_bytes(b"NOT A ZIP")
    plan = Plan("install_apk", ("install", str(bad)), True, 2, bad.name)
    svc, *_ = _setup(secure_dir, store, allowed_roots=(root,))
    result = _perform(svc, plan, runner=lambda *_: pytest.fail("bad APK executed"))
    assert result.status == "blocked" and result.code == "ARTIFACT_REJECTED"


def test_host_lease_rejects_competing_mutation(secure_dir, store):
    ready = threading.Event()
    finish = threading.Event()
    svc, *_ = _setup(secure_dir, store)
    completed = []

    def held_runner(argv, timeout, cap):
        ready.set()
        assert finish.wait(5)
        return RunResult(0, "OK (1 test)\nINSTRUMENTATION_CODE: -1", "", False)

    thread = threading.Thread(target=lambda: completed.append(_perform(svc, runner=held_runner)))
    thread.start()
    assert ready.wait(3)
    try:
        denied = _perform(svc, runner=lambda *_: pytest.fail("lease collision"))
        assert denied.status == "blocked" and denied.code == "DEVICE_BUSY"
    finally:
        finish.set()
        thread.join(5)
    assert completed and completed[0].status == "completed"


def test_apk_digest_change_before_execution_denies(secure_dir, store, monkeypatch):
    import android_mcp_host.security.coordinator as module

    root = secure_dir / "allowed"
    root.mkdir(mode=0o700)
    apk = root / "demo.apk"
    apk.write_bytes(b"PK\x03\x04" + b"source" * 100)
    plan = Plan("install_apk", ("install", str(apk)), True, 2, apk.name)
    svc, bridge, inbox, journal = _setup(secure_dir, store, allowed_roots=(root,))
    monkeypatch.setattr(module, "verify_staged", lambda staged: False)
    r = _perform(svc, plan, runner=lambda *_: pytest.fail("tampered APK executed"))
    assert r.code == "ARTIFACT_CHANGED"
    assert journal.verify_chain()
    assert len(bridge.released) == 1


def test_never_claims_success_only_from_return_code(secure_dir, store):
    svc, *_ = _setup(secure_dir, store)
    result = _perform(svc, runner=lambda *_: RunResult(0, "no instrumentation markers", "", False))
    assert result.status == "partial"
    assert result.code == "TEST_RESULT_UNCONFIRMED"


def test_end_audit_failure_downgrades_success(secure_dir, store, monkeypatch):
    import android_mcp_host.security.coordinator as module

    svc, bridge, _, journal = _setup(secure_dir, store)
    real = journal.append

    def break_end(event):
        if event.event == "end":
            raise module.AuditError("sink gone")
        return real(event)

    monkeypatch.setattr(journal, "append", break_end)
    outcome = _perform(svc)
    assert outcome.status == "partial"
    assert outcome.code == "AUDIT_INCOMPLETE"
    assert len(bridge.released) == 1


def test_begin_audit_failure_blocks_before_adb(secure_dir, store, monkeypatch):
    import android_mcp_host.security.coordinator as module

    svc, bridge, _, journal = _setup(secure_dir, store)
    monkeypatch.setattr(
        journal, "append", lambda *_: (_ for _ in ()).throw(module.AuditError("down"))
    )
    result = _perform(svc, runner=lambda *_: pytest.fail("ADB must not run without audit"))
    assert result.status == "blocked"
    assert result.code == "SECURITY_SERVICE_UNAVAILABLE"
    assert len(bridge.released) == 1


def test_native_release_error_downgrades_result(secure_dir, store):
    svc, bridge, *_ = _setup(secure_dir, store)
    bridge.release = lambda *_: (_ for _ in ()).throw(OSError("disconnected"))
    outcome = _perform(svc)
    assert outcome.status == "partial"
    assert outcome.code == "LEASE_OR_ARTIFACT_RELEASE_UNCONFIRMED"


def test_local_release_unconfirmed_downgrades_result(secure_dir, store, monkeypatch):
    svc, *_ = _setup(secure_dir, store)
    monkeypatch.setattr(store, "release", lambda _: False)
    outcome = _perform(svc)
    assert outcome.status == "partial"
    assert outcome.code == "LEASE_OR_ARTIFACT_RELEASE_UNCONFIRMED"


def test_local_release_error_downgrades_result(secure_dir, store, monkeypatch):
    svc, *_ = _setup(secure_dir, store)
    monkeypatch.setattr(store, "release", lambda _: (_ for _ in ()).throw(OSError("disk")))
    outcome = _perform(svc)
    assert outcome.status == "partial"
    assert outcome.code == "LEASE_OR_ARTIFACT_RELEASE_UNCONFIRMED"


def test_unexpected_broken_native_bridge_never_runs_adb(secure_dir, store):
    svc, bridge, *_ = _setup(secure_dir, store)
    bridge.acquire = lambda *_: (_ for _ in ()).throw(RuntimeError("private"))
    outcome = _perform(svc, runner=lambda *_: pytest.fail("malformed native lease"))
    assert outcome.status == "blocked"
    assert outcome.code == "SECURITY_GATE_FAILURE"


def test_staged_cleanup_exception_downgrades(secure_dir, store, monkeypatch):
    import android_mcp_host.security.coordinator as module

    root = secure_dir / "allowed"
    root.mkdir(mode=0o700)
    apk = root / "demo.apk"
    apk.write_bytes(b"PK\x03\x04" + b"source" * 100)
    plan = Plan("install_apk", ("install", str(apk)), True, 2, apk.name)
    svc, *_ = _setup(secure_dir, store, allowed_roots=(root,))
    real = module.remove_staged

    def cleanup_fault(artifact):
        real(artifact)
        raise OSError("private cleanup failed")

    monkeypatch.setattr(module, "remove_staged", cleanup_fault)
    outcome = _perform(svc, plan, runner=lambda *_: RunResult(0, "Success\n", "", False))
    assert outcome.status == "partial"
    assert outcome.code == "LEASE_OR_ARTIFACT_RELEASE_UNCONFIRMED"


def test_native_lease_loss_during_execution_never_claims_success(secure_dir, store):
    service, bridge, *_ = _setup(secure_dir, store)

    def lose_lease(argv, timeout, cap):
        bridge.healthy = False
        return RunResult(0, "OK (1 test)\nINSTRUMENTATION_CODE: -1", "", False)

    result = _perform(service, runner=lose_lease)
    assert result.status == "partial"
    assert result.code == "LEASE_LOST_DURING_EXECUTION"
