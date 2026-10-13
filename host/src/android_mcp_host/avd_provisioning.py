"""Opt-in Host synthetic, dedicated-root, ownership-fenced AVD provisioning.

Never operates on pre-existing user/Native AVDs. No emulator process is started.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from importlib.resources import files
from pathlib import Path
from typing import Any

from android_mcp_host.avd_provision_support import (
    MAX_DISPOSABLE_AVDS,
    OwnedAvdError,
    _sane_root,
    _write_owned,
    create_signature,
    image_preflight,
    owned_record,
    provision_lock,
    root_key,
    safe_remove_owned,
)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_NAME = re.compile(r"mcp_[A-Za-z0-9][A-Za-z0-9_-]{2,43}\Z", re.ASCII)
_OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9:_-]{0,63}\Z", re.ASCII)
_HANDLE = re.compile(r"mcpavd_[A-Za-z0-9_-]{32}\Z", re.ASCII)
_ABIS = {"arm64-v8a": "arm64", "armeabi-v7a": "arm", "x86": "x86", "x86_64": "x86_64"}
_MESSAGES = {
    "INVALID_ACTION": "AVD operation is unsupported",
    "INVALID_NAME": "Disposable AVD name is invalid",
    "INVALID_HANDLE": "Disposable AVD handle is invalid",
    "IMAGE_UNAVAILABLE": "Approved offline SDK image or license is unavailable",
    "UNTRUSTED_ROOT": "Dedicated AVD store is untrusted",
    "FOREIGN_AVD": "An existing AVD is not owned by this Host",
    "AVD_NOT_FOUND": "Owned AVD is unavailable",
    "RESOURCE_LIMIT": "Disposable AVD quota exceeded",
    "RESOURCE_BUSY": "Another AVD operation is in progress",
    "STORAGE_FAILURE": "Private AVD storage operation failed",
}


def get_avd_provision_schema() -> dict[str, Any]:
    value: Any = json.loads(
        files("android_mcp_host.wire_schemas")
        .joinpath("host-avd-provision.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(value, dict):
        raise ValueError("Invalid packaged Host AVD provisioning schema")
    return value


def _response(
    status: str,
    avd: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "runtime": "host",
        "status": status,
        "avd": avd,
        "errors": ([{"code": error, "message": _MESSAGES[error]}] if error is not None else []),
        "emulator_execution_enabled": False,
        "physical_device_writes_enabled": False,
    }


class AvdProvisioner:
    """Only create/delete private MCP-owned synthetic AVD metadata directories."""

    def __init__(
        self,
        root: Path,
        sdk_root: Path,
        owner: str,
        *,
        api: int,
        abi: str,
        source_properties_sha256: str,
        system_image_sha256: str,
        license_sha256: str,
    ) -> None:
        if (
            not isinstance(root, Path)
            or not isinstance(sdk_root, Path)
            or not _sane_root(root)
            or not _sane_root(sdk_root)
            or not isinstance(owner, str)
            or _OWNER.fullmatch(owner) is None
            or type(api) is not int
            or not 16 <= api <= 40
            or abi not in _ABIS
            or not isinstance(source_properties_sha256, str)
            or _DIGEST.fullmatch(source_properties_sha256) is None
            or not isinstance(system_image_sha256, str)
            or _DIGEST.fullmatch(system_image_sha256) is None
            or not isinstance(license_sha256, str)
            or _DIGEST.fullmatch(license_sha256) is None
            or sdk_root in root.parents
            or root in sdk_root.parents
            or root == sdk_root
        ):
            raise ValueError("Invalid trusted offline AVD operator configuration")
        self._root = root
        self._sdk = sdk_root
        self._owner = owner
        self._api = api
        self._abi = abi
        self._source_digest = source_properties_sha256
        self._image_digest = system_image_sha256
        self._license_digest = license_sha256
        self._owner_ref = hashlib.sha256(
            (owner + ":" + source_properties_sha256).encode("ascii")
        ).hexdigest()

    def _metadata(self, name: str, handle: str | None) -> dict[str, Any]:
        return {
            "name": name,
            "handle": handle,
            "owner_ref": self._owner_ref,
            "target": "disposable_emulator_only",
            "api": self._api,
            "abi": self._abi,
            "artifact_sha256": self._image_digest,
        }

    def _config(self, name: str) -> tuple[bytes, bytes]:
        path = self._root / f"{name}.avd"
        ini = (f"avd.ini.encoding=UTF-8\npath={path}\ntarget=android-{self._api}\n").encode()
        config = (
            f"AvdId={name}\nabi.type={self._abi}\n"
            f"hw.cpu.arch={_ABIS[self._abi]}\n"
            f"image.sysdir.1=system-images/android-{self._api}/default/{self._abi}/\n"
            f"target=android-{self._api}\n"
        ).encode()
        return ini, config

    def _record(self, name: str, secret: bytes) -> dict[str, Any] | None:
        ini, config = self._config(name)
        return owned_record(
            self._root, name, secret, self._owner_ref, self._image_digest, config, ini
        )

    def _create(self, name: str) -> dict[str, Any]:
        secret = root_key(self._root, create=True)
        assert secret is not None
        with provision_lock(self._root):
            folder = self._root / f"{name}.avd"
            ini_file = self._root / f"{name}.ini"
            if folder.exists() or folder.is_symlink() or ini_file.exists() or ini_file.is_symlink():
                record = self._record(name, secret)
                if record is None:
                    raise OwnedAvdError("FOREIGN_AVD")
                return _response("existing", self._metadata(name, record["handle"]))
            try:
                count = sum(1 for item in self._root.iterdir() if item.name.endswith(".avd"))
            except OSError as error:
                raise OwnedAvdError("STORAGE_FAILURE") from error
            if count >= MAX_DISPOSABLE_AVDS:
                raise OwnedAvdError("RESOURCE_LIMIT")
            handle_key = hmac.new(
                secret,
                (self._owner_ref + ":" + name + ":" + self._image_digest).encode("ascii"),
                hashlib.sha256,
            ).digest()[:24]
            handle = "mcpavd_" + base64.urlsafe_b64encode(handle_key).decode("ascii")
            assert _HANDLE.fullmatch(handle) is not None
            marker = {
                "schema_version": 1,
                "name": name,
                "handle": handle,
                "owner_ref": self._owner_ref,
                "image_sha256": self._image_digest,
            }
            marker["signature"] = create_signature(secret, marker)
            ini, config = self._config(name)
            created = False
            try:
                folder.mkdir(mode=0o700)
                created = True
                _write_owned(folder / "config.ini", config)
                _write_owned(
                    folder / ".mcp-owner.json",
                    json.dumps(marker, sort_keys=True, separators=(",", ":")).encode("ascii"),
                )
                _write_owned(ini_file, ini)
            except OSError as error:
                if created:
                    for child in ("config.ini", ".mcp-owner.json"):
                        candidate = folder / child
                        if candidate.is_file() and not candidate.is_symlink():
                            candidate.unlink()
                    folder.rmdir()
                # Never unlink a preexisting user's ini file.
                raise OwnedAvdError("STORAGE_FAILURE") from error
            return _response("created", self._metadata(name, handle))

    def _delete(self, name: str, handle: str) -> dict[str, Any]:
        secret = root_key(self._root, create=False)
        if secret is None:
            return _response("not_found", error="AVD_NOT_FOUND")
        with provision_lock(self._root):
            directory = self._root / f"{name}.avd"
            ini_file = self._root / f"{name}.ini"
            if not directory.exists() and not ini_file.exists():
                return _response("not_found", error="AVD_NOT_FOUND")
            record = self._record(name, secret)
            if record is None or record["handle"] != handle:
                raise OwnedAvdError("FOREIGN_AVD")
            try:
                safe_remove_owned(self._root, name)
            except OSError as error:
                raise OwnedAvdError("STORAGE_FAILURE") from error
            return _response("deleted", self._metadata(name, handle))

    @property
    def private_root(self) -> Path:
        """Trusted Host-internal root only; never returned by an MCP Tool."""
        return self._root

    @property
    def trusted_owner(self) -> str:
        """Host-internal provisioning owner; never exported to MCP callers."""
        return self._owner

    def verify_owned(self, name: str, handle: str) -> dict[str, Any] | None:
        """Confirm exact image and HMAC owner before any synthetic fixture job."""
        if (
            not isinstance(name, str)
            or _NAME.fullmatch(name) is None
            or not isinstance(handle, str)
            or _HANDLE.fullmatch(handle) is None
        ):
            return None
        if not image_preflight(
            self._sdk,
            self._api,
            self._abi,
            self._source_digest,
            self._image_digest,
            self._license_digest,
        ):
            return None
        try:
            secret = root_key(self._root, create=False)
            if secret is None:
                return None
            with provision_lock(self._root):
                record = self._record(name, secret)
                if record is None or record["handle"] != handle:
                    return None
                return self._metadata(name, handle)
        except OwnedAvdError:
            return None

    def provision(self, action: str, name: str, handle: str | None = None) -> dict[str, Any]:
        """Only operator-scoped synthetic local files; no emulator runs or installs."""
        if action not in ("plan", "create", "delete"):
            return _response("blocked", error="INVALID_ACTION")
        if not isinstance(name, str) or _NAME.fullmatch(name) is None:
            return _response("blocked", error="INVALID_NAME")
        if action == "delete" and (
            not isinstance(handle, str) or _HANDLE.fullmatch(handle) is None
        ):
            return _response("blocked", error="INVALID_HANDLE")
        if action in {"plan", "create"}:
            if not image_preflight(
                self._sdk,
                self._api,
                self._abi,
                self._source_digest,
                self._image_digest,
                self._license_digest,
            ):
                return _response("unavailable", error="IMAGE_UNAVAILABLE")
            if action == "plan":
                return _response("planned", self._metadata(name, None))
        try:
            if action == "create":
                return self._create(name)
            assert isinstance(handle, str)
            return self._delete(name, handle)
        except OwnedAvdError as error:
            return _response("blocked", error=error.code)
