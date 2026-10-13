"""H3.d owner-signed synthetic snapshot records; real emulator writes disabled."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from importlib.resources import files
from typing import Any

from android_mcp_host.avd_provision_support import (
    OwnedAvdError,
    _write_owned,
    provision_lock,
    root_key,
)
from android_mcp_host.avd_provisioning import AvdProvisioner
from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.durable_jobs import DurableJobStore
from android_mcp_host.emulator_snapshot_support import (
    MAX_SNAPSHOTS_PER_AVD,
    _canonical,
    public_snapshot,
    signed_record,
    snapshot_path,
    valid_snapshot,
    verified_record,
)

_REQUEST = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}\Z", re.ASCII)
_HANDLE = re.compile(r"mcpsnap_[A-Za-z0-9_-]{32}\Z", re.ASCII)
_WORKER = "h3d-private-snapshot-fixture-v1"
_CONDITIONS = frozenset({"boot_delay", "network_disconnect", "process_crash"})
_MESSAGES = {
    "INVALID_ACTION": "Snapshot action is unsupported",
    "INVALID_NAME": "Snapshot name is invalid",
    "INVALID_REQUEST": "Snapshot request identifier is invalid",
    "INVALID_HANDLE": "Snapshot handle is invalid",
    "NOT_OWNED": "Private disposable AVD owner is unverified",
    "UNTRUSTED_SNAPSHOT": "Snapshot does not belong to the approved AVD",
    "SNAPSHOT_NOT_FOUND": "Owned snapshot is unavailable",
    "RESOURCE_LIMIT": "Owned snapshot quota exceeded",
    "RECOVERY_REQUIRED": "Earlier snapshot job needs trusted reconciliation",
    "JOB_UNAVAILABLE": "Snapshot journal is unavailable",
    "IDEMPOTENCY_CONFLICT": "Request does not match original snapshot plan",
    "STORAGE_FAILURE": "Private snapshot persistence failed",
    "TIMEOUT": "Snapshot job outcome is uncertain",
    "INVALID_CONDITION": "Requested synthetic fault condition is unsupported",
}


def get_snapshot_output_schema() -> dict[str, Any]:
    value: Any = json.loads(
        files("android_mcp_host.wire_schemas")
        .joinpath("host-emulator-snapshot.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(value, dict):
        raise ValueError("Invalid packaged Host snapshot result schema")
    return value


def _response(
    status: str,
    action: str,
    *,
    avd: dict[str, Any] | None = None,
    snapshot: dict[str, Any] | None = None,
    snapshots: list[dict[str, Any]] | None = None,
    job_id: str | None = None,
    error: str | None = None,
    condition: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "runtime": "host",
        "status": status,
        "action": action,
        "condition": condition,
        "avd_name": avd["name"] if avd else None,
        "avd_handle": avd["handle"] if avd else None,
        "target": "disposable_emulator_only",
        "snapshot": snapshot,
        "snapshots": snapshots if snapshots is not None else [],
        "job_id": job_id,
        "possible_emulator_state_change": False,
        "real_snapshot_execution_enabled": False,
        "physical_device_writes_enabled": False,
        "errors": [{"code": error, "message": _MESSAGES[error]}] if error else [],
    }


def _before_mutation(action: str, snapshot_name: str) -> None:
    """Synthetic zero-effect hook; instrumented by timeout tests only."""
    return


class EmulatorSnapshotManager:
    """HMAC-authorized records without real QEMU save/load or disk rollback."""

    def __init__(self, provisioner: AvdProvisioner, jobs: DurableJobStore, *, owner: str) -> None:
        if not jobs.validate_owner(owner) or owner != provisioner.trusted_owner:
            raise ValueError("Snapshot owner must match the approved private AVD owner")
        self.provisioner = provisioner
        self._jobs = jobs
        self._owner = owner

    @staticmethod
    def _plan_digest(action: str, avd: dict[str, Any], snapshot_name: str) -> str:
        return hashlib.sha256(
            _canonical(
                {
                    "schema_version": 1,
                    "action": action,
                    "name": avd["name"],
                    "avd_handle": avd["handle"],
                    "image_sha256": avd["artifact_sha256"],
                    "snapshot": snapshot_name,
                }
            )
        ).hexdigest()

    def _owner_locked(self, avd: dict[str, Any], secret: bytes) -> bool:
        record = self.provisioner._record(avd["name"], secret)
        return record is not None and record["handle"] == avd["handle"]

    def _read(
        self, avd: dict[str, Any], secret: bytes, snapshot_name: str
    ) -> dict[str, Any] | None:
        return verified_record(
            snapshot_path(self.provisioner.private_root, avd["name"], snapshot_name),
            secret,
            avd,
            snapshot_name,
        )

    def _list(self, avd: dict[str, Any], secret: bytes) -> dict[str, Any]:
        prefix = f".mcp-snapshot-{avd['name']}-"
        folder = self.provisioner.private_root
        try:
            matching = sorted(
                item
                for item in folder.iterdir()
                if item.name.startswith(prefix) and item.name.endswith(".json")
            )
        except OSError:
            return _response("blocked", "list", avd=avd, error="STORAGE_FAILURE")
        if len(matching) > MAX_SNAPSHOTS_PER_AVD:
            return _response("blocked", "list", avd=avd, error="RESOURCE_LIMIT")
        snapshots: list[dict[str, Any]] = []
        for path in matching:
            snap = path.name[len(prefix) : -5]
            if not valid_snapshot(snap):
                return _response("blocked", "list", avd=avd, error="UNTRUSTED_SNAPSHOT")
            signed = self._read(avd, secret, snap)
            if signed is None:
                return _response("blocked", "list", avd=avd, error="UNTRUSTED_SNAPSHOT")
            snapshots.append(public_snapshot(signed))
        return _response("ok", "list", avd=avd, snapshots=snapshots)

    def _existing_job(
        self,
        action: str,
        avd: dict[str, Any],
        secret: bytes,
        snapshot_name: str,
        job: dict[str, Any],
    ) -> dict[str, Any]:
        job_id = str(job["job_id"])
        state = job["state"]
        if state != "succeeded":
            return _response(
                "failed" if state == "failed" else "uncertain",
                action,
                avd=avd,
                job_id=job_id,
            )
        found = self._read(avd, secret, snapshot_name)
        if action == "delete":
            if (
                found is None
                and not snapshot_path(
                    self.provisioner.private_root, avd["name"], snapshot_name
                ).exists()
            ):
                return _response("deleted", action, avd=avd, job_id=job_id)
            return _response("uncertain", action, avd=avd, job_id=job_id)
        if found is None:
            return _response("uncertain", action, avd=avd, job_id=job_id)
        return _response(
            "existing" if action == "create" else "simulated",
            action,
            avd=avd,
            snapshot=public_snapshot(found),
            job_id=job_id,
        )

    def _execute(
        self,
        action: str,
        avd: dict[str, Any],
        secret: bytes,
        name: str,
        snapshot_handle: str | None,
        job_id: str,
    ) -> dict[str, Any]:
        path = snapshot_path(self.provisioner.private_root, avd["name"], name)
        signed = self._read(avd, secret, name)
        if action == "create":
            if path.exists() or path.is_symlink():
                if signed is None:
                    return _response(
                        "blocked", action, avd=avd, job_id=job_id, error="UNTRUSTED_SNAPSHOT"
                    )
                return _response(
                    "existing", action, avd=avd, snapshot=public_snapshot(signed), job_id=job_id
                )
            listing = self._list(avd, secret)
            if listing["status"] != "ok":
                return _response(
                    "blocked", action, avd=avd, job_id=job_id, error="UNTRUSTED_SNAPSHOT"
                )
            if len(listing["snapshots"]) >= MAX_SNAPSHOTS_PER_AVD:
                return _response("blocked", action, avd=avd, job_id=job_id, error="RESOURCE_LIMIT")
            _before_mutation(action, name)
            signed = signed_record(secret, avd, name)
            _write_owned(path, _canonical(signed))
            return _response(
                "created", action, avd=avd, snapshot=public_snapshot(signed), job_id=job_id
            )
        if signed is None:
            return _response("blocked", action, avd=avd, job_id=job_id, error="UNTRUSTED_SNAPSHOT")
        if signed["snapshot_handle"] != snapshot_handle:
            return _response("blocked", action, avd=avd, job_id=job_id, error="INVALID_HANDLE")
        _before_mutation(action, name)
        if action == "delete":
            path.unlink()
            return _response(
                "deleted", action, avd=avd, snapshot=public_snapshot(signed), job_id=job_id
            )
        return _response(
            "simulated", action, avd=avd, snapshot=public_snapshot(signed), job_id=job_id
        )

    def _journal(
        self,
        action: str,
        avd: dict[str, Any],
        secret: bytes,
        name: str,
        snapshot_handle: str | None,
        request_id: str,
    ) -> dict[str, Any]:
        digest = self._plan_digest(action, avd, name)
        try:
            prior = self._jobs.lookup_request(self._owner, request_id, digest, avd["handle"])
            if prior is not None:
                return self._existing_job(action, avd, secret, name, prior)
            if any(
                row["state"] in {"prepared", "queued", "running", "uncertain"}
                for row in self._jobs.list_status(self._owner)
            ):
                return _response("blocked", action, avd=avd, error="RECOVERY_REQUIRED")
            prepared = self._jobs.prepare(
                self._owner, request_id, digest, identity=avd["handle"], authorized=True
            )
            job_id = str(prepared["job_id"])
            self._jobs.queue(self._owner, job_id, identity=avd["handle"], authorized=True)
            claimed = self._jobs.claim(self._owner, job_id, _WORKER, avd["handle"], authorized=True)
        except JobStoreError as error:
            code = (
                "IDEMPOTENCY_CONFLICT"
                if error.code == "IDEMPOTENCY_CONFLICT"
                else ("JOB_UNAVAILABLE")
            )
            return _response("blocked", action, avd=avd, error=code)
        try:
            output = self._execute(action, avd, secret, name, snapshot_handle, job_id)
            failure_code = output["errors"][0]["code"] if output["status"] == "blocked" else None
            result_digest = hashlib.sha256(
                _canonical({"job_id": job_id, "output": output["status"]})
            ).hexdigest()
            self._jobs.complete(
                self._owner,
                job_id,
                _WORKER,
                claimed["generation"],
                avd["handle"],
                authorized=True,
                failure_code=failure_code,
                result_digest=result_digest if failure_code is None else None,
            )
            return output
        except subprocess.TimeoutExpired:
            try:
                self._jobs.cancel(self._owner, job_id, identity=avd["handle"], authorized=True)
            except JobStoreError:
                pass
            return _response("uncertain", action, avd=avd, job_id=job_id, error="TIMEOUT")
        except OSError:
            path = snapshot_path(self.provisioner.private_root, avd["name"], name)
            if action == "create" and not path.exists() and not path.is_symlink():
                try:
                    self._jobs.complete(
                        self._owner,
                        job_id,
                        _WORKER,
                        claimed["generation"],
                        avd["handle"],
                        authorized=True,
                        failure_code="STORAGE_FAILURE",
                    )
                except JobStoreError:
                    pass
                else:
                    return _response(
                        "failed", action, avd=avd, job_id=job_id, error="STORAGE_FAILURE"
                    )
            try:
                self._jobs.cancel(self._owner, job_id, identity=avd["handle"], authorized=True)
            except JobStoreError:
                pass
            return _response("uncertain", action, avd=avd, job_id=job_id, error="STORAGE_FAILURE")
        except (ValueError, RuntimeError, JobStoreError):
            try:
                self._jobs.cancel(self._owner, job_id, identity=avd["handle"], authorized=True)
            except JobStoreError:
                pass
            return _response("uncertain", action, avd=avd, job_id=job_id, error="STORAGE_FAILURE")

    def operate(
        self,
        action: str,
        avd_name: str,
        avd_handle: str,
        snapshot_name: str | None = None,
        *,
        snapshot_handle: str | None = None,
        request_id: str | None = None,
        job_id: str | None = None,
        condition: str | None = None,
    ) -> dict[str, Any]:
        if action not in {"create", "restore", "delete", "list", "fault_plan", "cancel"}:
            return _response("blocked", action, error="INVALID_ACTION")
        if action in {"create", "restore", "delete", "cancel"} and not valid_snapshot(
            snapshot_name
        ):
            return _response("blocked", action, error="INVALID_NAME")
        if action in {"restore", "delete"} and (
            not isinstance(snapshot_handle, str) or _HANDLE.fullmatch(snapshot_handle) is None
        ):
            return _response("blocked", action, error="INVALID_HANDLE")
        if action in {"create", "restore", "delete"} and (
            not isinstance(request_id, str) or _REQUEST.fullmatch(request_id) is None
        ):
            return _response("blocked", action, error="INVALID_REQUEST")
        if action == "fault_plan" and condition not in _CONDITIONS:
            return _response("blocked", action, error="INVALID_CONDITION")
        avd = self.provisioner.verify_owned(avd_name, avd_handle)
        if avd is None:
            return _response("blocked", action, error="NOT_OWNED")
        if action == "fault_plan":
            return _response("planned", action, avd=avd, condition=condition)
        try:
            secret = root_key(self.provisioner.private_root, create=False)
            if secret is None:
                return _response("blocked", action, avd=avd, error="NOT_OWNED")
            with provision_lock(self.provisioner.private_root):
                if not self._owner_locked(avd, secret):
                    return _response("blocked", action, avd=avd, error="NOT_OWNED")
                if action == "list":
                    return self._list(avd, secret)
                if action == "cancel":
                    if not isinstance(job_id, str):
                        return _response("blocked", action, avd=avd, error="JOB_UNAVAILABLE")
                    try:
                        self._jobs.cancel(
                            self._owner, job_id, identity=avd["handle"], authorized=True
                        )
                    except JobStoreError:
                        return _response("uncertain", action, avd=avd, job_id=job_id)
                    return _response("uncertain", action, avd=avd, job_id=job_id)
                assert snapshot_name is not None and request_id is not None
                return self._journal(
                    action, avd, secret, snapshot_name, snapshot_handle, request_id
                )
        except OwnedAvdError:
            return _response("blocked", action, avd=avd, error="NOT_OWNED")
