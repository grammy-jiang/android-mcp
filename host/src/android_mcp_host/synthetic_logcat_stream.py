"""H5.b owner-pinned, finite, durable synthetic Logcat stream and polling.

No actual Android Logcat stream or physical reads are enabled. The bounded
trusted fixture runs once; only allowlisted sanitized event records persist.
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
from android_mcp_host.logcat_stream_store import LogcatStreamStore, StreamStoreError
from android_mcp_host.logcat_stream_support import (
    MAX_EVENTS,
    MAX_RAW_BYTES,
    InvalidSyntheticLogcat,
    digest,
    parse_events,
    reply,
    valid_request,
)

_TIMEOUT_S = 3.0
_WORKER = "h5b-synthetic-logcat"


@dataclass(frozen=True, slots=True)
class StreamApproval:
    owner: str
    avd_handle: str
    lifecycle_job_id: str
    purpose: str
    valid_until_epoch: float
    ttl_s: int


@dataclass(frozen=True, slots=True)
class StreamFrame:
    raw: bytes
    avd_name: str
    avd_handle: str
    lifecycle_job_id: str
    complete: bool
    synthetic: bool


FixtureReader = Callable[[str, str, str, int, int, float, threading.Event], StreamFrame]


def get_logcat_stream_schema() -> dict[str, Any]:
    result: Any = json.loads(
        files("android_mcp_host.wire_schemas")
        .joinpath("host-synthetic-logcat-stream.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(result, dict):
        raise ValueError("Missing finite Logcat stream output contract")
    return result


class SyntheticLogcatStream:
    """One consented fixture per exact owned AVD lifecycle; durable cursor pages."""

    def __init__(
        self,
        provisioner: AvdProvisioner,
        lifecycle: EmulatorLifecycle,
        jobs: DurableJobStore,
        *,
        owner: str,
        approval: StreamApproval | None = None,
        fixture_read: FixtureReader | None = None,
        clock: Callable[[], float] = time.time,
        streams: LogcatStreamStore | None = None,
    ) -> None:
        if (
            not jobs.validate_owner(owner)
            or owner != provisioner.trusted_owner
            or owner != lifecycle._owner
            or lifecycle.provisioner is not provisioner
        ):
            raise ValueError("Invalid trusted synthetic Logcat stream owner")
        self._provisioner = provisioner
        self._lifecycle = lifecycle
        self._jobs = jobs
        self._owner = owner
        self._approval = approval
        self._fixture = fixture_read
        self._clock = clock
        self._streams = (
            streams if streams is not None else LogcatStreamStore(jobs.private_root, clock=clock)
        )
        self._guard = threading.RLock()
        self._active: dict[str, threading.Event] = {}

    @staticmethod
    def _slot(lid: str) -> str:
        return "h5b-logcat-" + lid

    def _approved(self, handle: str, lid: str, ttl: int) -> bool:
        approval = self._approval
        if approval is None:
            return False
        try:
            remaining = approval.valid_until_epoch - self._clock()
        except (ArithmeticError, TypeError, ValueError):
            return False
        return (
            approval.owner == self._owner
            and approval.avd_handle == handle
            and approval.lifecycle_job_id == lid
            and approval.purpose == "synthetic-sanitized-logcat"
            and type(approval.valid_until_epoch) in (int, float)
            and type(approval.ttl_s) is int
            and math.isfinite(remaining)
            and 0 < remaining <= 120
            and 1 <= ttl <= approval.ttl_s <= 120
            and ttl <= remaining
        )

    @staticmethod
    def _meta(value: dict[str, Any], base: dict[str, Any], status: str = "ok") -> dict[str, Any]:
        return reply(
            status,
            str(value["state"]),
            job_id=base["job_id"],
            name=base["name"],
            handle=base["handle"],
            lifecycle=base["lifecycle"],
            cursor=value["cursor"],
            entries=value.get("entries"),
            from_index=value.get("from_index"),
            next_index=value.get("next_index"),
            total_events=value["total_events"],
            dropped_events=value["dropped_events"],
            truncated=value["truncated"],
            ttl=value["retention_seconds"],
        )

    def _replay(self, prior: dict[str, Any], base: dict[str, Any], request: str) -> dict[str, Any]:
        jid = str(prior["job_id"])
        base["job_id"] = jid
        if prior["state"] != "succeeded":
            return reply("blocked", "unknown", error="RECOVERY_REQUIRED", **base)
        try:
            value = self._streams.peek(jid, self._owner, base["handle"], base["lifecycle"], request)
            if value["state"] != "ready":
                return reply(
                    "ended" if value["state"] == "ended" else "stopped",
                    value["state"],
                    **base,
                )
            return self._meta(value, base)
        except StreamStoreError as error:
            return reply("blocked", "unknown", error=error.code, **base)

    def _start(
        self,
        info: dict[str, Any],
        lid: str,
        request: str,
        tag: str | None,
        maximum: int,
        ttl: int,
    ) -> dict[str, Any]:
        base: dict[str, Any] = {
            "name": info["name"],
            "handle": info["handle"],
            "lifecycle": lid,
        }
        plan_digest = digest(info["handle"], lid, request, tag, maximum, ttl)
        try:
            prior = self._jobs.lookup_request(
                self._owner, self._slot(lid), plan_digest, info["handle"]
            )
            if prior is not None:
                return self._replay(prior, base, request)
            if any(
                row["job_id"] != lid
                and row["state"] in {"prepared", "queued", "running", "uncertain"}
                for row in self._jobs.list_status(self._owner)
            ):
                return reply("blocked", error="RECOVERY_REQUIRED", **base)
            job = self._jobs.prepare(
                self._owner,
                self._slot(lid),
                plan_digest,
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
            code = (
                "IDEMPOTENCY_CONFLICT"
                if error.code == "IDEMPOTENCY_CONFLICT"
                else "JOB_UNAVAILABLE"
            )
            return reply("blocked", error=code, **base)
        base["job_id"] = jid
        stop = threading.Event()
        with self._guard:
            self._active[jid] = stop
        complete = False
        try:
            assert self._fixture is not None
            start = time.monotonic()
            frame = self._fixture(
                info["name"], info["handle"], lid, maximum, MAX_RAW_BYTES, _TIMEOUT_S, stop
            )
            if stop.is_set():
                return reply("uncertain", "unknown", error="CANCELLED", **base)
            if time.monotonic() - start > _TIMEOUT_S:
                return reply("uncertain", "unknown", error="TIMEOUT", **base)
            if not self._approved(info["handle"], lid, ttl):
                return reply("uncertain", "unknown", error="CONSENT_REQUIRED", **base)
            if not verified_fake_target(self._lifecycle, info, lid):
                return reply("uncertain", "unknown", error="UNVERIFIED_TARGET", **base)
            if (
                type(frame) is not StreamFrame
                or frame.avd_name != info["name"]
                or frame.avd_handle != info["handle"]
                or frame.lifecycle_job_id != lid
                or frame.complete is not True
                or frame.synthetic is not True
                or type(frame.raw) is not bytes
            ):
                self._jobs.complete(
                    self._owner,
                    jid,
                    _WORKER,
                    running["generation"],
                    info["handle"],
                    authorized=True,
                    failure_code="INVALID_FRAME",
                )
                complete = True
                return reply("failed", "unknown", error="INVALID_FRAME", **base)
            try:
                events, dropped, truncated = parse_events(frame.raw, tag=tag, maximum=maximum)
            except InvalidSyntheticLogcat:
                code = "OUTPUT_LIMIT" if len(frame.raw) > MAX_RAW_BYTES else "INVALID_LOGCAT"
                self._jobs.complete(
                    self._owner,
                    jid,
                    _WORKER,
                    running["generation"],
                    info["handle"],
                    authorized=True,
                    failure_code=code,
                )
                complete = True
                return reply("failed", "unknown", error=code, **base)
            if stop.is_set() or not verified_fake_target(self._lifecycle, info, lid):
                return reply("uncertain", "unknown", error="UNVERIFIED_TARGET", **base)
            snapshot = self._streams.insert(
                jid,
                self._owner,
                info["handle"],
                lid,
                request,
                events,
                dropped,
                truncated,
                ttl,
            )
            if stop.is_set() or not self._approved(info["handle"], lid, ttl):
                return reply("uncertain", "unknown", error="CANCELLED", **base)
            self._jobs.complete(
                self._owner,
                jid,
                _WORKER,
                running["generation"],
                info["handle"],
                authorized=True,
                result_digest=snapshot["sha256"],
            )
            complete = True
            return self._meta(snapshot, base)
        except subprocess.TimeoutExpired:
            return reply("uncertain", "unknown", error="TIMEOUT", **base)
        except (
            StreamStoreError,
            JobStoreError,
            OSError,
            RuntimeError,
            ValueError,
            TypeError,
            KeyError,
            subprocess.SubprocessError,
        ):
            return reply(
                "uncertain",
                "unknown",
                error="CANCELLED" if stop.is_set() else "RUNNER_FAILED",
                **base,
            )
        finally:
            with self._guard:
                self._active.pop(jid, None)
            if not complete:
                try:
                    self._streams.discard(jid)
                except StreamStoreError:
                    pass
                try:
                    self._jobs.cancel(self._owner, jid, identity=info["handle"], authorized=True)
                except JobStoreError:
                    pass

    def _ongoing(
        self,
        action: str,
        info: dict[str, Any],
        lid: str,
        request: str,
        job_id: str,
        cursor: str | None,
        tag: str | None,
        page_size: int,
        maximum: int,
        ttl: int,
    ) -> dict[str, Any]:
        base: dict[str, Any] = {
            "name": info["name"],
            "handle": info["handle"],
            "lifecycle": lid,
            "job_id": job_id,
        }
        try:
            prior = self._jobs.lookup_request(
                self._owner,
                self._slot(lid),
                digest(info["handle"], lid, request, tag, maximum, ttl),
                info["handle"],
            )
            if prior is None or prior["job_id"] != job_id:
                return reply("blocked", error="NOT_FOUND", **base)
            if action == "stop" and prior["state"] in {"prepared", "queued", "running"}:
                self._jobs.cancel(self._owner, job_id, identity=info["handle"], authorized=True)
                with self._guard:
                    if job_id in self._active:
                        self._active[job_id].set()
                return reply("uncertain", "unknown", error="CANCELLED", **base)
            if prior["state"] != "succeeded":
                return reply("blocked", "unknown", error="RECOVERY_REQUIRED", **base)
            if not verified_fake_target(self._lifecycle, info, lid):
                self._streams.stop(job_id, self._owner, info["handle"], lid, request)
                return reply("blocked", error="UNVERIFIED_TARGET", **base)
            if action == "stop":
                state = self._streams.stop(job_id, self._owner, info["handle"], lid, request)
                return reply("stopped" if state == "stopped" else "ended", state, **base)
            assert cursor is not None
            value = self._streams.poll(
                job_id, self._owner, info["handle"], lid, request, cursor, page_size
            )
            return self._meta(value, base, "ended" if value["state"] == "ended" else "ok")
        except JobStoreError as error:
            code = (
                "IDEMPOTENCY_CONFLICT"
                if error.code == "IDEMPOTENCY_CONFLICT"
                else "JOB_UNAVAILABLE"
            )
            return reply("blocked", error=code, **base)
        except StreamStoreError as error:
            return reply("blocked", error=error.code, **base)

    def submit(
        self,
        action: str,
        avd_name: str,
        avd_handle: str,
        lifecycle_job_id: str,
        *,
        request_id: str | None = None,
        job_id: str | None = None,
        cursor: str | None = None,
        tag: str | None = None,
        max_events: int = MAX_EVENTS,
        page_size: int = 8,
        ttl_s: int = 60,
    ) -> dict[str, Any]:
        code = valid_request(
            action,
            lifecycle_job_id,
            request_id,
            job_id,
            cursor,
            tag,
            page_size,
            max_events,
            ttl_s,
        )
        if code is not None:
            return reply("blocked", error=code)
        info = self._provisioner.verify_owned(avd_name, avd_handle)
        if info is None:
            return reply("blocked", error="NOT_OWNED")
        base = {"name": info["name"], "handle": info["handle"], "lifecycle": lifecycle_job_id}
        if action == "plan":
            return reply("planned", **base)
        assert request_id is not None
        if action == "start":
            if not self._approved(info["handle"], lifecycle_job_id, ttl_s):
                return reply("blocked", error="CONSENT_REQUIRED", **base)
            if self._fixture is None:
                return reply("blocked", error="EXECUTION_DISABLED", **base)
            if not verified_fake_target(self._lifecycle, info, lifecycle_job_id):
                return reply("blocked", error="UNVERIFIED_TARGET", **base)
            try:
                fd = claim_fixture_lock(self._jobs.private_root, info["handle"])
            except OSError:
                return reply("blocked", error="JOB_UNAVAILABLE", **base)
            if fd is None:
                return reply("blocked", error="RECOVERY_REQUIRED", **base)
            try:
                return self._start(info, lifecycle_job_id, request_id, tag, max_events, ttl_s)
            finally:
                os.close(fd)
        assert job_id is not None
        return self._ongoing(
            action,
            info,
            lifecycle_job_id,
            request_id,
            job_id,
            cursor,
            tag,
            page_size,
            max_events,
            ttl_s,
        )
