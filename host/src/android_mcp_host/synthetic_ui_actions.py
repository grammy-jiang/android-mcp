"""H4.f owner-pinned synthetic-only UI actions, no Android input capability.

Production has no fake runner, window observer or per-intent grant. A trusted
test harness must independently inject all three. No real adb input is called.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from android_mcp_host.avd_provisioning import AvdProvisioner
from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.durable_jobs import DurableJobStore
from android_mcp_host.emulator_debug_support import verified_fake_target
from android_mcp_host.emulator_instrumentation_support import claim_fixture_lock
from android_mcp_host.emulator_lifecycle import EmulatorLifecycle
from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.private_artifact_support import ArtifactStoreError
from android_mcp_host.ui_action_control import cancel_ui_action
from android_mcp_host.ui_action_frame import (
    UiActionFrame,
    UiWitness,
    action_frame_error,
    witness_error,
)
from android_mcp_host.ui_action_receipts import _reply, replay_ui_action
from android_mcp_host.ui_action_support import (
    action_plan_digest,
    action_slot,
    compile_safe_argv,
    coordinates_fit,
    intent_digest,
    valid_action_intent,
    valid_lifecycle_job,
    valid_request_id,
    valid_ui_target,
)

_WORKER = "h4f-synthetic-ui-action-worker"
_MAX_TTL = 300


@dataclass(frozen=True, slots=True)
class UiActionApproval:
    owner: str
    avd_handle: str
    lifecycle_job_id: str
    window_id: str
    window_generation: int
    rotation: int
    focused_node_id: str
    intent_sha256: str
    purpose: str
    valid_until_epoch: float
    ttl_s: float


WitnessReader = Callable[[str, str, str, float], UiWitness]
ActionRunner = Callable[[list[str], threading.Event], UiActionFrame]


def get_ui_action_schema() -> dict[str, Any]:
    value: Any = json.loads(
        files("android_mcp_host.wire_schemas")
        .joinpath("host-synthetic-ui-actions.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(value, dict):
        raise ValueError("Invalid private UI action output schema")
    return value


class UiActionService:
    """Fixed action fixture with an exact time-limited window witness."""

    def __init__(
        self,
        provisioner: AvdProvisioner,
        lifecycle: EmulatorLifecycle,
        jobs: DurableJobStore,
        artifacts: PrivateArtifactStore,
        *,
        owner: str,
        artifact_owner: str,
        approval: UiActionApproval | None = None,
        fixture_witness: WitnessReader | None = None,
        fixture_runner: ActionRunner | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if (
            not jobs.validate_owner(owner)
            or not artifacts.validate_owner(artifact_owner)
            or owner != provisioner.trusted_owner
            or owner != lifecycle._owner
            or lifecycle.provisioner is not provisioner
        ):
            raise ValueError("Invalid owner-pinned synthetic UI action configuration")
        self._provisioner = provisioner
        self._lifecycle = lifecycle
        self._jobs = jobs
        self._artifacts = artifacts
        self._owner = owner
        self._artifact_owner = artifact_owner
        self._approval = approval
        self._witness = fixture_witness
        self._runner = fixture_runner
        self._clock = clock
        self._guard = threading.RLock()
        self._active: dict[str, threading.Event] = {}

    def _signal_stop(self, job_id: str) -> None:
        with self._guard:
            if job_id in self._active:
                self._active[job_id].set()

    def _approved(self, handle: str, lid: str, action: dict[str, Any]) -> bool:
        grant = self._approval
        if grant is None:
            return False
        try:
            remaining = grant.valid_until_epoch - self._clock()
        except (ValueError, TypeError, ArithmeticError):
            return False
        return (
            grant.owner == self._owner
            and grant.avd_handle == handle
            and grant.lifecycle_job_id == lid
            and grant.window_id == action["window_id"]
            and grant.window_generation == action["generation"]
            and grant.rotation == action["rotation"]
            and grant.focused_node_id == action["focused_node_id"]
            and grant.intent_sha256 == action["intent_sha256"]
            and grant.purpose == "synthetic-ui-input"
            and type(grant.valid_until_epoch) in (float, int)
            and type(grant.ttl_s) in (float, int)
            and math.isfinite(remaining)
            and math.isfinite(grant.ttl_s)
            and 0 < remaining <= _MAX_TTL
            and 1 <= grant.ttl_s <= _MAX_TTL
        )

    def _check_witness(
        self,
        info: dict[str, Any],
        lid: str,
        action: dict[str, Any],
        coords: tuple[object, object, object, object],
    ) -> str | None:
        if self._witness is None:
            return "CAPABILITY_UNAVAILABLE"
        try:
            witness = self._witness(info["name"], info["handle"], lid, 3.0)
        except subprocess.TimeoutExpired:
            return "TIMEOUT"
        except (OSError, RuntimeError, TypeError, ValueError, subprocess.SubprocessError):
            return "CAPABILITY_UNAVAILABLE"
        problem = witness_error(
            witness,
            info["handle"],
            lid,
            action["window_id"],
            action["generation"],
            action["rotation"],
            action["focused_node_id"],
        )
        if problem is not None:
            return problem
        assert isinstance(witness, UiWitness)
        if not coordinates_fit(action["kind"], witness.width, witness.height, *coords):
            return "INVALID_INPUT"
        return None

    def _execute(
        self,
        info: dict[str, Any],
        lid: str,
        action: dict[str, Any],
        request: str,
        argv: list[str],
        coords: tuple[object, object, object, object],
    ) -> dict[str, Any]:
        base: dict[str, Any] = {
            "name": info["name"],
            "handle": info["handle"],
            "lifecycle_id": lid,
            **action,
        }
        slot = action_slot(lid, action["window_id"], action["intent_sha256"])
        digest = action_plan_digest(
            info["handle"],
            lid,
            action["window_id"],
            action["generation"],
            action["rotation"],
            action["focused_node_id"],
            action["intent_sha256"],
            request,
        )
        try:
            prior = self._jobs.lookup_request(self._owner, slot, digest, info["handle"])
            if prior is not None:
                return replay_ui_action(
                    self._artifacts,
                    self._artifact_owner,
                    prior,
                    name=info["name"],
                    handle=info["handle"],
                    lifecycle_id=lid,
                    window_id=action["window_id"],
                    generation=action["generation"],
                    rotation=action["rotation"],
                    focus=action["focused_node_id"],
                    kind=action["kind"],
                    intent_sha=action["intent_sha256"],
                )
            if any(
                item["job_id"] != lid
                and item["state"] in {"prepared", "queued", "running", "uncertain"}
                for item in self._jobs.list_status(self._owner)
            ):
                return _reply("blocked", error="RECOVERY_REQUIRED", **base)
            job = self._jobs.prepare(
                self._owner,
                slot,
                digest,
                identity=info["handle"],
                authorized=True,
            )
            jid = str(job["job_id"])
            self._jobs.queue(self._owner, jid, identity=info["handle"], authorized=True)
            running = self._jobs.claim(
                self._owner,
                jid,
                _WORKER,
                info["handle"],
                authorized=True,
            )
        except JobStoreError as error:
            reason = (
                "IDEMPOTENCY_CONFLICT"
                if error.code == "IDEMPOTENCY_CONFLICT"
                else "JOB_UNAVAILABLE"
            )
            return _reply("blocked", error=reason, **base)

        stop = threading.Event()
        with self._guard:
            self._active[jid] = stop
        reports: list[str] = []
        finished = False
        try:
            assert self._runner is not None and self._approval is not None
            if not self._approved(info["handle"], lid, action):
                return _reply("uncertain", "unknown", job_id=jid, error="CONSENT_REQUIRED", **base)
            frame = self._runner(argv, stop)
            if stop.is_set():
                return _reply("uncertain", "unknown", job_id=jid, error="CANCELLED", **base)
            if not verified_fake_target(self._lifecycle, info, lid):
                return _reply("uncertain", "unknown", job_id=jid, error="UNVERIFIED_TARGET", **base)
            changed = self._check_witness(info, lid, action, coords)
            if changed is not None:
                return _reply("uncertain", "unknown", job_id=jid, error=changed, **base)
            if not self._approved(info["handle"], lid, action):
                return _reply("uncertain", "unknown", job_id=jid, error="CONSENT_REQUIRED", **base)
            result_problem = action_frame_error(
                frame,
                info,
                lid,
                action["window_id"],
                action["generation"],
                action["rotation"],
                action["focused_node_id"],
            )
            if result_problem is not None:
                return _reply("uncertain", "unknown", job_id=jid, error=result_problem, **base)
            receipt = {
                "purpose": "h4f-private-synthetic-ui-action-v1",
                "schema_version": 1,
                "job_id": jid,
                "avd_handle": info["handle"],
                "lifecycle_job_id": lid,
                "window_id": action["window_id"],
                "window_generation": action["generation"],
                "rotation": action["rotation"],
                "focused_node_id": action["focused_node_id"],
                "kind": action["kind"],
                "intent_sha256": action["intent_sha256"],
                "synthetic_fixture_only": True,
            }
            encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("ascii")
            report = self._artifacts.put(
                self._artifact_owner,
                encoded,
                mime_type="application/json",
                ttl_s=self._approval.ttl_s,
            )
            reports.append(report["handle"])
            if stop.is_set():
                return _reply("uncertain", "unknown", job_id=jid, error="CANCELLED", **base)
            if not self._approved(info["handle"], lid, action):
                return _reply("uncertain", "unknown", job_id=jid, error="CONSENT_REQUIRED", **base)
            if self._check_witness(info, lid, action, coords) is not None:
                return _reply("uncertain", "unknown", job_id=jid, error="STALE_WINDOW", **base)
            self._jobs.complete(
                self._owner,
                jid,
                _WORKER,
                running["generation"],
                info["handle"],
                authorized=True,
                result_digest=report["sha256"],
            )
            finished = True
            return _reply(
                "simulated",
                "applied_synthetic",
                job_id=jid,
                report_handle=report["handle"],
                report_sha256=report["sha256"],
                **base,
            )
        except subprocess.TimeoutExpired:
            return _reply("uncertain", "unknown", job_id=jid, error="TIMEOUT", **base)
        except (
            OSError,
            RuntimeError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            JobStoreError,
            ArtifactStoreError,
            subprocess.SubprocessError,
        ):
            return _reply("uncertain", "unknown", job_id=jid, error="RUNNER_FAILED", **base)
        finally:
            with self._guard:
                self._active.pop(jid, None)
            if not finished:
                for handle in reports:
                    try:
                        self._artifacts.revoke(self._artifact_owner, handle)
                    except ArtifactStoreError:
                        pass
                try:
                    self._jobs.cancel(
                        self._owner,
                        jid,
                        identity=info["handle"],
                        authorized=True,
                    )
                except JobStoreError:
                    pass

    def submit(
        self,
        operation: str,
        kind: str,
        avd_name: str,
        avd_handle: str,
        lifecycle_job_id: str,
        window_id: str,
        window_generation: int,
        rotation: int,
        focused_node_id: str,
        *,
        x: int | None = None,
        y: int | None = None,
        x2: int | None = None,
        y2: int | None = None,
        duration_ms: int | None = None,
        keycode: str | None = None,
        request_id: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(operation, str) or operation not in {"plan", "execute", "cancel"}:
            return _reply("blocked", error="INVALID_ACTION")
        if (
            not valid_lifecycle_job(lifecycle_job_id)
            or not valid_ui_target(window_id, window_generation, rotation, focused_node_id)
            or not valid_action_intent(
                kind,
                x=x,
                y=y,
                x2=x2,
                y2=y2,
                duration_ms=duration_ms,
                keycode=keycode,
            )
            or (operation != "plan" and not valid_request_id(request_id))
            or (operation == "cancel" and not valid_lifecycle_job(job_id))
        ):
            return _reply("blocked", error="INVALID_INPUT")
        info = self._provisioner.verify_owned(avd_name, avd_handle)
        if info is None:
            return _reply("blocked", error="NOT_OWNED")
        signature = intent_digest(
            kind=kind,
            x=x,
            y=y,
            x2=x2,
            y2=y2,
            duration_ms=duration_ms,
            keycode=keycode,
        )
        action: dict[str, Any] = {
            "window_id": window_id,
            "generation": window_generation,
            "rotation": rotation,
            "focused_node_id": focused_node_id,
            "kind": kind,
            "intent_sha256": signature,
        }
        base: dict[str, Any] = {
            "name": info["name"],
            "handle": info["handle"],
            "lifecycle_id": lifecycle_job_id,
            **action,
        }
        argv = compile_safe_argv(
            info["name"],
            kind,
            x=x,
            y=y,
            x2=x2,
            y2=y2,
            duration_ms=duration_ms,
            keycode=keycode,
        )
        if operation == "plan":
            return _reply("planned", preview_argv=argv, **base)
        assert request_id is not None
        if operation == "cancel":
            assert job_id is not None
            return cancel_ui_action(
                self._jobs,
                self._owner,
                info,
                lifecycle_job_id,
                window_id,
                window_generation,
                rotation,
                focused_node_id,
                kind,
                signature,
                request_id,
                job_id,
                self._signal_stop,
            )
        if self._runner is None or self._witness is None or self._approval is None:
            return _reply("blocked", error="MUTATION_DISABLED", **base)
        if not verified_fake_target(self._lifecycle, info, lifecycle_job_id):
            return _reply("blocked", error="UNVERIFIED_TARGET", **base)
        try:
            fd = claim_fixture_lock(self._jobs.private_root, info["handle"])
        except OSError:
            return _reply("blocked", error="JOB_UNAVAILABLE", **base)
        if fd is None:
            return _reply("blocked", error="RECOVERY_REQUIRED", **base)
        try:
            coords = (x, y, x2, y2)
            problem = self._check_witness(info, lifecycle_job_id, action, coords)
            if problem is not None:
                return _reply("blocked", error=problem, **base)
            if not self._approved(info["handle"], lifecycle_job_id, action):
                return _reply("blocked", error="MUTATION_DISABLED", **base)
            return self._execute(info, lifecycle_job_id, action, request_id, argv, coords)
        finally:
            os.close(fd)
