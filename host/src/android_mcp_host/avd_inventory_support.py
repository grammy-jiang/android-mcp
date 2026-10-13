"""Read-only bounded AVD configuration, snapshot and PID validation primitives."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Any

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z", re.ASCII)
_KEY = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z", re.ASCII)
_API = re.compile(r"android-([0-9]{1,2})\Z", re.ASCII)
_ABIS = frozenset({"arm64-v8a", "armeabi-v7a", "x86", "x86_64"})
MAX_INI_BYTES = 65536
MAX_SNAPSHOTS = 16


def valid_name(name: object) -> bool:
    return isinstance(name, str) and _NAME.fullmatch(name) is not None


def trusted_dir(path: Path) -> bool:
    """Inspect local owner and directory type; do not create or follow a root link."""
    try:
        if any(part.is_symlink() for part in (path, *path.parents)):
            return False
        info = path.lstat()
        return (
            stat.S_ISDIR(info.st_mode)
            and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) & 0o077 == 0
        )
    except OSError:
        return False


def read_private(path: Path, cap: int = MAX_INI_BYTES) -> bytes | None:
    """Read one bounded owner file using O_NOFOLLOW and fstat, never by filename twice."""
    fd: int | None = None
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_size > cap
            or info.st_size <= 0
            or info.st_nlink != 1
        ):
            return None
        with os.fdopen(fd, "rb") as stream:
            fd = None
            data = stream.read(cap + 1)
        return data if len(data) == info.st_size else None
    except OSError:
        return None
    finally:
        if fd is not None:
            os.close(fd)


def parse_ini(data: bytes | None) -> dict[str, str] | None:
    if data is None:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if any(ord(char) < 32 and char not in "\r\n\t" for char in text):
        return None
    result: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or _KEY.fullmatch(key) is None or len(value) > 1024 or key in result:
            return None
        result[key] = value.strip()
    return result


def snapshot_inventory(avd_path: Path) -> tuple[int, str] | None:
    """Only count snapshot metadata folders. Never interpret snapshot.pb binaries."""
    folder = avd_path / "snapshots"
    if folder.is_symlink():
        return None
    if not folder.exists():
        return (0, "none")
    if not trusted_dir(folder):
        return None
    try:
        names = list(folder.iterdir())
    except OSError:
        return None
    if len(names) > MAX_SNAPSHOTS:
        return None
    count = 0
    for entry in names:
        if not valid_name(entry.name) or not trusted_dir(entry):
            return None
        # Snapshot version is optional, but never infer binary format version.
        version = entry / "snapshot.version"
        if version.is_symlink():
            return None
        if version.exists():
            raw = read_private(version, 32)
            if raw is None or re.fullmatch(rb"[1-9][0-9]{0,2}\s*\Z", raw) is None:
                return None
            if not 1 <= int(raw) <= 100:
                return None
        count += 1
    return (count, "present_unverified" if count else "none")


def avd_metadata(root: Path, name: str) -> tuple[dict[str, Any] | None, Path | None]:
    """Check matching AVD paths, SDK target, ABI and optional snapshot presence."""
    if not valid_name(name) or not trusted_dir(root):
        return (None, None)
    root_ini = parse_ini(read_private(root / f"{name}.ini"))
    avd_dir = root / f"{name}.avd"
    if root_ini is None or not trusted_dir(avd_dir):
        return (None, None)
    config = parse_ini(read_private(avd_dir / "config.ini"))
    if config is None:
        return (None, None)
    api_raw = root_ini.get("target", "")
    api = _API.fullmatch(api_raw)
    abi = config.get("abi.type")
    cpu = config.get("hw.cpu.arch")
    cpu_for_abi = {
        "arm64-v8a": "arm64",
        "armeabi-v7a": "arm",
        "x86": "x86",
        "x86_64": "x86_64",
    }
    if (
        api is None
        or not 16 <= int(api.group(1)) <= 40
        or abi not in _ABIS
        or cpu != cpu_for_abi.get(abi)
        or root_ini.get("path") != str(avd_dir)
        or config.get("AvdId", name) != name
        or config.get("target", api_raw) != api_raw
        or config.get("image.sysdir.1") != f"system-images/{api_raw}/default/{abi}/"
        and config.get("image.sysdir.1")
        not in {
            f"system-images/{api_raw}/google_apis/{abi}/",
            f"system-images/{api_raw}/google_apis_playstore/{abi}/",
        }
    ):
        return (None, None)
    snapshots = snapshot_inventory(avd_dir)
    if snapshots is None:
        return (None, None)
    count, state = snapshots
    return (
        {
            "name": name,
            "api": int(api.group(1)),
            "abi": abi,
            "snapshot_count": count,
            "snapshot_state": state,
            "running_state": "stale_or_unverified",
        },
        avd_dir,
    )


def lock_pid(avd_dir: Path) -> int | None:
    data = read_private(avd_dir / "hardware-qemu.ini.lock", 32)
    if data is None:
        return None
    cleaned = data.strip(b"\0\r\n ")
    if re.fullmatch(rb"[1-9][0-9]{0,9}\Z", cleaned) is None:
        return None
    pid = int(cleaned)
    return pid if pid <= 2147483647 else None
