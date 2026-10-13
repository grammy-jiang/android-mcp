"""Private atomic files, image attestation and ownership for disposable AVDs.

Never use these functions on the user's existing Android ~/.android/avd store.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from android_mcp_host.avd_inventory_support import (
    parse_ini,
    read_private,
    trusted_dir,
)

MAX_DISPOSABLE_AVDS = 16
MAX_RECORD_BYTES = 4096
MAX_SYSTEM_IMAGE_BYTES = 8 * 1024 * 1024 * 1024
_HANDLE = re.compile(r"mcpavd_[A-Za-z0-9_-]{32}\Z", re.ASCII)


class OwnedAvdError(Exception):
    """Stable private Host AVD denial; never echoes paths or user input."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Disposable AVD unavailable: {code}")


def _write_owned(path: Path, data: bytes) -> None:
    """Create one private file exactly once; never follow paths or overwrite."""
    fd = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _sane_root(root: Path) -> bool:
    """Reject the existing user AVD store and any symlinked private root."""
    if not root.is_absolute() or ".." in root.parts or len(str(root)) > 1024:
        return False
    real_avds = Path.home() / ".android" / "avd"
    if root == real_avds or real_avds in root.parents:
        return False
    if any(part.is_symlink() for part in (root, *root.parents)):
        return False
    return True


def root_key(root: Path, *, create: bool) -> bytes | None:
    """Create only a dedicated, absent owned root; never adopt pre-existing data."""
    if not _sane_root(root):
        raise OwnedAvdError("UNTRUSTED_ROOT")
    if not root.exists():
        if not create:
            return None
        made = False
        try:
            root.mkdir(mode=0o700)
            made = True
            _write_owned(root / ".avd-key", os.urandom(32))
        except OSError as error:
            if made:
                try:
                    root.rmdir()
                except OSError:
                    pass
            raise OwnedAvdError("STORAGE_FAILURE") from error
    if not trusted_dir(root):
        raise OwnedAvdError("UNTRUSTED_ROOT")
    secret_path = root / ".avd-key"
    try:
        info = secret_path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
        ):
            raise OwnedAvdError("UNTRUSTED_ROOT")
    except OSError as error:
        raise OwnedAvdError("UNTRUSTED_ROOT") from error
    secret = read_private(secret_path, 32)
    if secret is None or len(secret) != 32:
        raise OwnedAvdError("UNTRUSTED_ROOT")
    return secret


@contextmanager
def provision_lock(root: Path) -> Iterator[None]:
    """Serialize MCP-owned AVD transitions across threads and processes."""
    path = root / ".avd-lock"
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except OSError as error:
        raise OwnedAvdError("STORAGE_FAILURE") from error
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
        ):
            raise OwnedAvdError("UNTRUSTED_ROOT")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise OwnedAvdError("RESOURCE_BUSY") from error
        yield
    finally:
        os.close(fd)


def _system_image_digest(image: Path, expected: str) -> bool:
    """Stream the pinned binary safely; never load a large system image in RAM."""
    fd: int | None = None
    try:
        fd = os.open(image, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or not 0 < info.st_size <= MAX_SYSTEM_IMAGE_BYTES
        ):
            return False
        digest = hashlib.sha256()
        remaining = info.st_size
        while remaining:
            chunk = os.read(fd, min(1048576, remaining))
            if not chunk:
                return False
            digest.update(chunk)
            remaining -= len(chunk)
        after = os.fstat(fd)
        return digest.hexdigest() == expected and (
            info.st_dev,
            info.st_ino,
            info.st_size,
            info.st_mtime_ns,
        ) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    except OSError:
        return False
    finally:
        if fd is not None:
            os.close(fd)


def image_preflight(
    sdk: Path,
    api: int,
    abi: str,
    metadata_sha256: str,
    system_image_sha256: str,
    license_sha256: str,
) -> bool:
    """Read pinned installed synthetic SDK metadata, never download or accept terms."""
    folder = sdk / "system-images" / f"android-{api}" / "default" / abi
    license_file = sdk / "licenses" / "android-sdk-license"
    if not all(
        path.is_absolute()
        and ".." not in path.parts
        and not any(part.is_symlink() for part in (path, *path.parents))
        for path in (folder, license_file)
    ):
        return False
    try:
        if not folder.is_dir():
            return False
        image = folder / "system.img"
        if not _system_image_digest(image, system_image_sha256):
            return False
        metadata = read_private(folder / "source.properties", MAX_RECORD_BYTES)
        license_bytes = read_private(license_file, MAX_RECORD_BYTES)
        if metadata is None or license_bytes is None:
            return False
        if hashlib.sha256(metadata).hexdigest() != metadata_sha256:
            return False
        if hashlib.sha256(license_bytes).hexdigest() != license_sha256:
            return False
        values = parse_ini(metadata)
        return values is not None and (
            values.get("AndroidVersion.ApiLevel") == str(api)
            and values.get("SystemImage.Abi") == abi
            and values.get("SystemImage.TagId") == "default"
            and isinstance(values.get("Pkg.Revision"), str)
            and re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", values["Pkg.Revision"]) is not None
        )
    except (OSError, ValueError):
        return False


def create_signature(secret: bytes, record: dict[str, Any]) -> str:
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hmac.new(secret, canonical, hashlib.sha256).hexdigest()


def owned_record(
    avd_root: Path,
    name: str,
    secret: bytes,
    owner_ref: str,
    image_sha256: str,
    config_bytes: bytes,
    ini_bytes: bytes,
) -> dict[str, Any] | None:
    """Authenticate marker, exact generated files and a closed directory layout."""
    directory = avd_root / f"{name}.avd"
    if not trusted_dir(directory):
        return None
    try:
        members = {item.name for item in directory.iterdir()}
    except OSError:
        return None
    if members != {"config.ini", ".mcp-owner.json"}:
        return None
    marker = read_private(directory / ".mcp-owner.json", MAX_RECORD_BYTES)
    if marker is None:
        return None
    try:
        record: Any = json.loads(marker)
    except (json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(record, dict):
        return None
    signature = record.pop("signature", None)
    if (
        not isinstance(signature, str)
        or re.fullmatch(r"[0-9a-f]{64}", signature, re.ASCII) is None
        or record.get("schema_version") != 1
        or record.get("name") != name
        or record.get("owner_ref") != owner_ref
        or record.get("image_sha256") != image_sha256
        or not isinstance(record.get("handle"), str)
        or _HANDLE.fullmatch(record["handle"]) is None
    ):
        return None
    try:
        expected = create_signature(secret, record)
    except (UnicodeError, TypeError, ValueError):
        return None
    if not hmac.compare_digest(signature, expected):
        return None
    if (
        read_private(directory / "config.ini", MAX_RECORD_BYTES) != config_bytes
        or read_private(avd_root / f"{name}.ini", MAX_RECORD_BYTES) != ini_bytes
    ):
        return None
    return record


def safe_remove_owned(root: Path, name: str) -> None:
    """Only unlink three verified files; never recursively remove user data."""
    directory = root / f"{name}.avd"
    for filename in ("config.ini", ".mcp-owner.json"):
        (directory / filename).unlink()
    directory.rmdir()
    (root / f"{name}.ini").unlink()
