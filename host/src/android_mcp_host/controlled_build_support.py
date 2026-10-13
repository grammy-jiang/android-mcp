"""Private filesystem safeguards for the approved, single-checkout Gradle worker."""

from __future__ import annotations

import fcntl
import hashlib
import os
import stat
from pathlib import Path


def safe_build_file(path: Path, limit: int) -> bytes | None:
    """Read only an owned bounded regular file through a no-follow descriptor."""
    fd: int | None = None
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or not 0 < info.st_size <= limit
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
        ):
            return None
        with os.fdopen(fd, "rb") as stream:
            fd = None
            contents = stream.read(limit + 1)
        return contents if len(contents) == info.st_size else None
    except OSError:
        return None
    finally:
        if fd is not None:
            os.close(fd)


def checkout_lock(private_root: Path, project_root: Path) -> int | None:
    """Cross-process exclusive flock on a validated private stable file."""
    key = hashlib.sha256(str(project_root).encode("utf-8")).hexdigest()[:32]
    path = private_root / ("gradle-" + key + ".lock")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
        ):
            raise OSError("Untrusted checkout lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return None
        return fd
    except BaseException:
        os.close(fd)
        raise


def output_stamp(root: Path) -> tuple[int, ...] | None:
    """Reject stale APK outputs and unsafe symlink or hardlink path entries."""
    path = root / "android/app/build/outputs/apk/debug/app-debug.apk"
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
        raise ValueError("Untrusted Gradle output")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
