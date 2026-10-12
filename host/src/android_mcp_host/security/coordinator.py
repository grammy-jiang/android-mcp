"""Deny-by-default Host mutation transaction coordinator (H3 prototype).

Not installed into the public MCP server. A real operator grant source and a
fenced Android Native lease bridge are mandatory for any mutation execution.
The bridge is deliberately an unimplemented interface until the Native runtime
can prove joint Host/Native arbitration.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from android_mcp_host.command_plan import Plan
from android_mcp_host.command_runner import RunResult
from android_mcp_host.security.approvals import ApprovalDenied, ApprovalVerifier
from android_mcp_host.security.artifacts import (
    ArtifactError,
    StagedArtifact,
    remove_staged,
    stage_apk,
    verify_staged,
)
from android_mcp_host.security.audit import AuditError, AuditEvent, AuditJournal
from android_mcp_host.security.identity import fingerprint
from android_mcp_host.security.store import Lease, StateError, StateStore


class NativeLease(Protocol):
    """Future trusted local USB/Native IPC lease bridge; not implemented."""

    def acquire(
        self, device_id: str, fence: int, plan_digest: str, ttl_s: int
    ) -> object | None: ...
    def is_current(self, handle: object) -> bool: ...
    def release(self, handle: object) -> None: ...


class TrustedGrantInbox(Protocol):
    """Read a trusted out-of-band signed grant; never take it from MCP args."""

    def fetch(self, device_id: str, plan_digest: str) -> object | None: ...


Runner = Callable[[list[str], float, int], RunResult]


@dataclass(frozen=True, slots=True)
class SecureOutcome:
    status: str  # blocked, error, partial, or completed (needs H2 result interpretation)
    code: str
    result: RunResult | None = None


class SecureMutationCoordinator:
    """Only executable when trusted bridge, inbox and signing keys exist."""

    def __init__(
        self,
        *,
        store: StateStore,
        journal: AuditJournal,
        approvals: ApprovalVerifier,
        grant_inbox: TrustedGrantInbox | None,
        native_lease: NativeLease | None,
        allowed_apk_roots: tuple[Path, ...],
        staging_dir: Path,
    ) -> None:
        self.store = store
        self.journal = journal
        self.approvals = approvals
        self.grant_inbox = grant_inbox
        self.native_lease = native_lease
        self.allowed_apk_roots = allowed_apk_roots
        self.staging_dir = staging_dir

    def _record(
        self, event: str, device_id: str, plan: Plan, digest: str, result_code: str
    ) -> None:
        self.journal.append(AuditEvent(event, device_id, plan.kind, digest, result_code))

    def perform(
        self,
        *,
        device_id: str,
        plan: Plan,
        binary: str,
        runner: Runner,
        output_byte_limit: int,
    ) -> SecureOutcome:
        """Authorize a validated command with durable evidence and joint leases.

        The production MCP composition does *not* install this coordinator.
        The Native lease bridge is currently a required but unimplemented port.
        """
        inbox = self.grant_inbox
        bridge = self.native_lease
        if not plan.mutating:
            return SecureOutcome("blocked", "MUTATION_REQUIRED")
        if inbox is None or bridge is None:
            return SecureOutcome("blocked", "MUTATION_DISABLED")
        if not binary or not 1024 <= output_byte_limit <= 262144:
            return SecureOutcome("blocked", "INVALID_EXECUTION_CONFIG")

        staged: StagedArtifact | None = None
        local: Lease | None = None
        remote: object | None = None
        result = SecureOutcome("blocked", "SECURITY_SERVICE_UNAVAILABLE")
        started = False
        cleanup_failed = False
        try:
            # Always hash immutable *copied bytes*, not a mutable source filename.
            suffix = list(plan.argv_suffix)
            apk_hash: str | None = None
            if plan.kind == "install_apk":
                staged = stage_apk(
                    Path(suffix[-1]),
                    allowed_roots=self.allowed_apk_roots,
                    staging_dir=self.staging_dir,
                )
                apk_hash = staged.sha256
            digest = fingerprint(
                device_id=device_id,
                kind=plan.kind,
                argv_suffix=plan.argv_suffix,
                artifact_sha256=apk_hash,
            )
            ttl_s = min(300, int(plan.timeout_s + 60))
            local = self.store.acquire(device_id, ttl_s=ttl_s)
            if local is None:
                result = SecureOutcome("blocked", "DEVICE_BUSY")
            else:
                remote = bridge.acquire(device_id, local.fence, digest, ttl_s)
                if remote is None:
                    result = SecureOutcome("blocked", "NATIVE_LEASE_UNAVAILABLE")
                else:
                    envelope = inbox.fetch(device_id, digest)
                    if envelope is None:
                        self._record("deny", device_id, plan, digest, "denied")
                        result = SecureOutcome("blocked", "OPERATOR_APPROVAL_REQUIRED")
                    else:
                        self.approvals.verify_and_consume(
                            envelope, device_id=device_id, plan_digest=digest
                        )
                        if not self.store.is_current(local) or not bridge.is_current(remote):
                            result = SecureOutcome("blocked", "LEASE_EXPIRED")
                        elif staged is not None and not verify_staged(staged):
                            result = SecureOutcome("blocked", "ARTIFACT_CHANGED")
                        else:
                            # A failed BEGIN journal write is a hard stop.
                            self._record("begin", device_id, plan, digest, "authorized")
                            if staged is not None:
                                suffix[-1] = str(staged.path)
                            started = True
                            try:
                                ran = runner(
                                    [binary, "-s", device_id, *suffix],
                                    plan.timeout_s,
                                    output_byte_limit,
                                )
                            except (subprocess.TimeoutExpired, OSError, ValueError):
                                result = SecureOutcome("error", "ADB_EXECUTION_FAILED")
                            else:
                                # Do not report adb client process exit as test/install success.
                                from android_mcp_host.operations import _diagnose

                                operation_status, diagnosis = _diagnose(plan.kind, ran)
                                result = SecureOutcome(
                                    "completed" if operation_status == "ok" else operation_status,
                                    "NONE" if diagnosis is None else diagnosis["code"],
                                    ran,
                                )
                            # A completed local process is not proof that
                            # joint device ownership was retained throughout.
                            if not self.store.is_current(local) or not bridge.is_current(remote):
                                result = SecureOutcome(
                                    "partial", "LEASE_LOST_DURING_EXECUTION", result.result
                                )
                            try:
                                self._record(
                                    "end",
                                    device_id,
                                    plan,
                                    digest,
                                    "ok"
                                    if result.status == "completed"
                                    else "partial"
                                    if result.status == "partial"
                                    else "failed",
                                )
                            except AuditError:
                                result = SecureOutcome("partial", "AUDIT_INCOMPLETE", result.result)
        except ApprovalDenied:
            result = SecureOutcome("blocked", "APPROVAL_DENIED")
        except ArtifactError:
            result = SecureOutcome("blocked", "ARTIFACT_REJECTED")
        except (AuditError, StateError, OSError, ValueError):
            result = SecureOutcome(
                "partial" if started else "blocked", "SECURITY_SERVICE_UNAVAILABLE"
            )
        except Exception:
            # Untrusted or broken bridge/inbox implementations cannot leak
            # private details, create an accidental success, or bypass cleanup.
            result = SecureOutcome("partial" if started else "blocked", "SECURITY_GATE_FAILURE")
        finally:
            if remote is not None:
                try:
                    bridge.release(remote)
                except Exception:
                    cleanup_failed = True
            if local is not None:
                try:
                    if not self.store.release(local):
                        cleanup_failed = True
                except Exception:
                    cleanup_failed = True
            if staged is not None:
                try:
                    remove_staged(staged)
                except Exception:
                    cleanup_failed = True
        if cleanup_failed:
            return SecureOutcome(
                "partial" if started else "blocked",
                "LEASE_OR_ARTIFACT_RELEASE_UNCONFIRMED",
                result.result,
            )
        return result
