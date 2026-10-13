"""H4.a owner-pinned synthetic-only screenshots; real ADB capture disabled."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import struct
import subprocess
import zlib
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

_REQUEST = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}\Z", re.ASCII)
_JOB = re.compile(r"job_[A-Za-z0-9_-]{32}\Z", re.ASCII)
_WORKER = "h4a-synthetic-screenshot-worker"
_MAX_PNG = 4 * 1024 * 1024
_MAX_DIMENSION = 2048
_MAX_PIXELS = 4_194_304
_MAX_TTL = 300.0
_ERRORS = {
    "INVALID_ACTION": "Unsupported screenshot operation",
    "INVALID_INPUT": "Screenshot request has invalid fields",
    "NOT_OWNED": "Exact disposable AVD ownership is not verified",
    "CONSENT_REQUIRED": "Trusted sensitive-media capture approval is absent",
    "EXECUTION_DISABLED": "Real ADB screenshot capture remains disabled",
    "UNVERIFIED_TARGET": "Verified synthetic emulator session is unavailable",
    "RECOVERY_REQUIRED": "Prior capture requires trusted reconciliation",
    "IDEMPOTENCY_CONFLICT": "Request identifier conflicts with the prior capture",
    "JOB_UNAVAILABLE": "Durable capture job is unavailable",
    "BAD_FRAME": "Synthetic PNG failed bounded verification",
    "SECURE_CONTENT": "Protected window capture is forbidden",
    "TIMEOUT": "Capture result is uncertain after timeout",
    "CAPTURE_FAILED": "Synthetic capture or private storage failed",
    "ARTIFACT_EXPIRED": "Private capture or receipt is no longer available",
}


@dataclass(frozen=True, slots=True)
class CaptureApproval:
    """Trusted out-of-band approval, never a free-form MCP argument."""

    owner: str
    avd_handle: str
    lifecycle_job_id: str
    purpose: str
    ttl_s: float


@dataclass(frozen=True, slots=True)
class CaptureFrame:
    """Untrusted result of a synthetic fixture; all fields revalidated."""

    payload: bytes
    avd_name: str
    avd_handle: str
    lifecycle_job_id: str
    secure_window: bool
    locked_window: bool
    synthetic: bool


CaptureBackend = Callable[[str, str, str, float], CaptureFrame]


def get_screenshot_schema() -> dict[str, Any]:
    raw: Any = json.loads(
        files("android_mcp_host.wire_schemas")
        .joinpath("host-synthetic-screenshot.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(raw, dict):
        raise ValueError("Invalid packaged private screenshot schema")
    return raw


def validate_png(raw: bytes) -> tuple[int, int]:
    """Check minimal RGBA8 PNG structure, CRC and bounded decoded image.

    Strictly accept IHDR, one or more IDAT chunks, and terminal IEND.
    Ancillary chunks, interlace and alternate color modes are unsupported;
    untrusted chunk lengths never control unbounded allocation.
    """
    if type(raw) is not bytes or not 45 <= len(raw) <= _MAX_PNG:
        raise ValueError("Invalid bounded PNG payload")
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Invalid PNG signature")
    cursor = 8
    width = height = 0
    data = bytearray()
    seen_ihdr = False
    seen_end = False
    seen_idat = False
    while cursor < len(raw):
        if cursor + 12 > len(raw):
            raise ValueError("Truncated PNG chunk")
        length = struct.unpack_from(">I", raw, cursor)[0]
        kind = raw[cursor + 4 : cursor + 8]
        end = cursor + 12 + length
        if length > _MAX_PNG or end > len(raw):
            raise ValueError("Oversized PNG chunk")
        payload = raw[cursor + 8 : cursor + 8 + length]
        actual_crc = struct.unpack_from(">I", raw, cursor + 8 + length)[0]
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != actual_crc:
            raise ValueError("Bad PNG CRC")
        if kind == b"IHDR" and not seen_ihdr and cursor == 8:
            if length != 13:
                raise ValueError("Invalid PNG header length")
            width, height, depth, color, compress, filtering, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            if (
                not 1 <= width <= _MAX_DIMENSION
                or not 1 <= height <= _MAX_DIMENSION
                or width * height > _MAX_PIXELS
                or (depth, color, compress, filtering, interlace) != (8, 6, 0, 0, 0)
            ):
                raise ValueError("Unsupported PNG frame")
            seen_ihdr = True
        elif kind == b"IDAT" and seen_ihdr and not seen_end:
            if length == 0 or len(data) + length > _MAX_PNG:
                raise ValueError("Oversized PNG image payload")
            data.extend(payload)
            seen_idat = True
        elif kind == b"IEND" and seen_ihdr and seen_idat:
            if length != 0 or end != len(raw):
                raise ValueError("Invalid PNG trailer")
            seen_end = True
        else:
            raise ValueError("Unexpected PNG chunk or order")
        cursor = end
    if not seen_end:
        raise ValueError("Missing PNG trailer")
    row_size = 1 + 4 * width
    decoded_max = row_size * height
    try:
        stream = zlib.decompressobj()
        decoded = stream.decompress(bytes(data), decoded_max + 1)
        if (
            len(decoded) != decoded_max
            or not stream.eof
            or stream.unconsumed_tail
            or stream.unused_data
            or any(decoded[offset] > 4 for offset in range(0, len(decoded), row_size))
        ):
            raise ValueError("Invalid decoded PNG pixels")
    except zlib.error as error:
        raise ValueError("Corrupt compressed PNG pixels") from error
    return width, height


def _reply(
    status: str,
    state: str = "none",
    *,
    name: str | None = None,
    handle: str | None = None,
    lifecycle_id: str | None = None,
    job_id: str | None = None,
    artifact_handle: str | None = None,
    sha: str | None = None,
    size: int | None = None,
    dimensions: tuple[int, int] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "runtime": "host",
        "status": status,
        "capture_state": state,
        "avd_name": name,
        "avd_handle": handle,
        "lifecycle_job_id": lifecycle_id,
        "job_id": job_id,
        "artifact_handle": artifact_handle,
        "sha256": sha,
        "size_bytes": size,
        "width": dimensions[0] if dimensions else None,
        "height": dimensions[1] if dimensions else None,
        "privacy_class": "sensitive_private",
        "target": "disposable_emulator_only",
        "synthetic_fixture_only": True,
        "real_capture_enabled": False,
        "physical_device_writes_enabled": False,
        "errors": [{"code": error, "message": _ERRORS[error]}] if error else [],
    }


class ScreenshotArtifacts:
    """Private, one-shot, synthetic-only screenshot Tool backing service."""

    def __init__(
        self,
        provisioner: AvdProvisioner,
        lifecycle: EmulatorLifecycle,
        jobs: DurableJobStore,
        artifacts: PrivateArtifactStore,
        *,
        owner: str,
        artifact_owner: str,
        approval: CaptureApproval | None = None,
        fixture_capture: CaptureBackend | None = None,
    ) -> None:
        if (
            not jobs.validate_owner(owner)
            or not artifacts.validate_owner(artifact_owner)
            or owner != provisioner.trusted_owner
            or owner != lifecycle._owner
            or lifecycle.provisioner is not provisioner
        ):
            raise ValueError("Invalid owner-pinned private screenshot configuration")
        self._provisioner = provisioner
        self._lifecycle = lifecycle
        self._jobs = jobs
        self._artifacts = artifacts
        self._owner = owner
        self._artifact_owner = artifact_owner
        self._approval = approval
        self._fixture = fixture_capture

    def _approved(self, avd_handle: str, lifecycle_id: str) -> bool:
        grant = self._approval
        return (
            grant is not None
            and grant.owner == self._owner
            and grant.avd_handle == avd_handle
            and grant.lifecycle_job_id == lifecycle_id
            and grant.purpose == "synthetic-debug-screenshot"
            and type(grant.ttl_s) in (int, float)
            and math.isfinite(grant.ttl_s)
            and 1 <= grant.ttl_s <= _MAX_TTL
        )

    @staticmethod
    def _digest(info: dict[str, Any], lifecycle_id: str) -> str:
        plan = {
            "operation": "h4a-private-screenshot-v1",
            "handle": info["handle"],
            "lifecycle": lifecycle_id,
            "image_type": "image/png",
        }
        return hashlib.sha256(
            json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("ascii")
        ).hexdigest()

    def _replay(self, job: dict[str, Any], info: dict[str, Any], lid: str) -> dict[str, Any]:
        jid = str(job["job_id"])
        state = str(job["state"])
        base = {"name": info["name"], "handle": info["handle"], "lifecycle_id": lid, "job_id": jid}
        if state == "failed":
            return _reply("failed", "unknown", error="BAD_FRAME", **base)
        if state != "succeeded" or not isinstance(job.get("result_digest"), str):
            return _reply("uncertain", "unknown", error="RECOVERY_REQUIRED", **base)
        try:
            for record in self._artifacts.list_metadata(self._artifact_owner):
                if (
                    record["sha256"] != job["result_digest"]
                    or record["mime_type"] != "application/json"
                ):
                    continue
                receipt = json.loads(self._artifacts.read(self._artifact_owner, record["handle"]))
                if (
                    not isinstance(receipt, dict)
                    or receipt.get("job_id") != jid
                    or receipt.get("avd_handle") != info["handle"]
                    or receipt.get("lifecycle_job_id") != lid
                ):
                    continue
                meta = self._artifacts.public_metadata(
                    self._artifact_owner, receipt["artifact_handle"]
                )
                if meta["status"] != "ok" or meta["artifact"]["sha256"] != receipt["sha256"]:
                    continue
                image = self._artifacts.read(self._artifact_owner, receipt["artifact_handle"])
                dimensions = validate_png(image)
                if dimensions != (receipt["width"], receipt["height"]):
                    continue
                return _reply(
                    "ok",
                    "captured_synthetic",
                    artifact_handle=receipt["artifact_handle"],
                    sha=receipt["sha256"],
                    size=len(image),
                    dimensions=dimensions,
                    **base,
                )
        except (ArtifactStoreError, KeyError, ValueError, TypeError, OSError):
            pass
        return _reply("uncertain", "unknown", error="ARTIFACT_EXPIRED", **base)

    def _finish_bad(
        self, info: dict[str, Any], lid: str, job_id: str, generation: int, code: str
    ) -> dict[str, Any]:
        self._jobs.complete(
            self._owner,
            job_id,
            _WORKER,
            generation,
            info["handle"],
            authorized=True,
            failure_code=code,
        )
        return _reply(
            "blocked" if code == "SECURE_CONTENT" else "failed",
            "unknown",
            name=info["name"],
            handle=info["handle"],
            lifecycle_id=lid,
            job_id=job_id,
            error=code,
        )

    def _execute(self, info: dict[str, Any], lid: str, request_id: str) -> dict[str, Any]:
        digest = self._digest(info, lid)
        base = {"name": info["name"], "handle": info["handle"], "lifecycle_id": lid}
        try:
            prior = self._jobs.lookup_request(self._owner, request_id, digest, info["handle"])
            if prior is not None:
                return self._replay(prior, info, lid)
            # A grant permits one screenshot per lifecycle. Unrelated completed
            # instrumentation/debug jobs must not prevent a later screenshot.
            if any(
                row["job_id"] != lid
                and (
                    row["plan_digest"] == digest
                    or row["state"] in {"prepared", "queued", "running", "uncertain"}
                )
                for row in self._jobs.list_status(self._owner)
            ):
                return _reply("blocked", error="RECOVERY_REQUIRED", **base)
            item = self._jobs.prepare(
                self._owner, request_id, digest, identity=info["handle"], authorized=True
            )
            jid = str(item["job_id"])
            self._jobs.queue(self._owner, jid, identity=info["handle"], authorized=True)
            running = self._jobs.claim(self._owner, jid, _WORKER, info["handle"], authorized=True)
        except JobStoreError as error:
            code = (
                "IDEMPOTENCY_CONFLICT"
                if error.code == "IDEMPOTENCY_CONFLICT"
                else "JOB_UNAVAILABLE"
            )
            return _reply("blocked", error=code, **base)

        assert self._fixture is not None and self._approval is not None
        handles: list[str] = []
        finished = False
        try:
            frame = self._fixture(info["name"], info["handle"], lid, 3.0)
            if not verified_fake_target(self._lifecycle, info, lid):
                return _reply("uncertain", "unknown", job_id=jid, error="UNVERIFIED_TARGET", **base)
            if (
                type(frame) is not CaptureFrame
                or frame.avd_name != info["name"]
                or frame.avd_handle != info["handle"]
                or frame.lifecycle_job_id != lid
                or frame.synthetic is not True
                or type(frame.secure_window) is not bool
                or type(frame.locked_window) is not bool
            ):
                response = self._finish_bad(info, lid, jid, running["generation"], "BAD_FRAME")
                finished = True
                return response
            if frame.secure_window or frame.locked_window:
                response = self._finish_bad(info, lid, jid, running["generation"], "SECURE_CONTENT")
                finished = True
                return response
            try:
                dimensions = validate_png(frame.payload)
            except ValueError:
                response = self._finish_bad(info, lid, jid, running["generation"], "BAD_FRAME")
                finished = True
                return response

            meta = self._artifacts.put(
                self._artifact_owner,
                frame.payload,
                mime_type="image/png",
                ttl_s=self._approval.ttl_s,
            )
            handles.append(meta["handle"])
            receipt = {
                "schema_version": 1,
                "job_id": jid,
                "avd_handle": info["handle"],
                "lifecycle_job_id": lid,
                "artifact_handle": meta["handle"],
                "sha256": meta["sha256"],
                "width": dimensions[0],
                "height": dimensions[1],
                "synthetic_fixture_only": True,
            }
            encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("ascii")
            report = self._artifacts.put(
                self._artifact_owner,
                encoded,
                mime_type="application/json",
                ttl_s=self._approval.ttl_s,
            )
            handles.append(report["handle"])
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
                "ok",
                "captured_synthetic",
                job_id=jid,
                artifact_handle=meta["handle"],
                sha=meta["sha256"],
                size=meta["size_bytes"],
                dimensions=dimensions,
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
            ArtifactStoreError,
            JobStoreError,
        ):
            return _reply("uncertain", "unknown", job_id=jid, error="CAPTURE_FAILED", **base)
        finally:
            if not finished:
                for handle in handles:
                    try:
                        self._artifacts.revoke(self._artifact_owner, handle)
                    except ArtifactStoreError:
                        pass
                try:
                    self._jobs.cancel(self._owner, jid, identity=info["handle"], authorized=True)
                except JobStoreError:
                    pass

    def submit(
        self,
        action: str,
        avd_name: str,
        avd_handle: str,
        lifecycle_job_id: str,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if action not in ("plan", "capture"):
            return _reply("blocked", error="INVALID_ACTION")
        if not isinstance(lifecycle_job_id, str) or _JOB.fullmatch(lifecycle_job_id) is None:
            return _reply("blocked", error="INVALID_INPUT")
        if action == "capture" and (
            not isinstance(request_id, str) or _REQUEST.fullmatch(request_id) is None
        ):
            return _reply("blocked", error="INVALID_INPUT")
        info = self._provisioner.verify_owned(avd_name, avd_handle)
        if info is None:
            return _reply("blocked", error="NOT_OWNED")
        base = {"name": info["name"], "handle": info["handle"], "lifecycle_id": lifecycle_job_id}
        if action == "plan":
            return _reply("planned", **base)
        if not self._approved(avd_handle, lifecycle_job_id):
            return _reply("blocked", error="CONSENT_REQUIRED", **base)
        if self._fixture is None:
            return _reply("blocked", error="EXECUTION_DISABLED", **base)
        if not verified_fake_target(self._lifecycle, info, lifecycle_job_id):
            return _reply("blocked", error="UNVERIFIED_TARGET", **base)
        try:
            fd = claim_fixture_lock(self._jobs.private_root, info["handle"])
        except OSError:
            return _reply("blocked", error="JOB_UNAVAILABLE", **base)
        if fd is None:
            return _reply("blocked", error="RECOVERY_REQUIRED", **base)
        try:
            assert request_id is not None
            return self._execute(info, lifecycle_job_id, request_id)
        finally:
            os.close(fd)
