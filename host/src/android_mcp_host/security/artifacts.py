"""Content-addressed, host-private APK staging for a future authorized install.

Opened source FDs are verified, copied, hashed and fsynced. The copied file is
passed by path only after verifying its digest. This is *not* an OS-enforced
immutable inode; a same-UID host compromise still requires separate defenses.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

MAX_APK_BYTES = 2 * 1024**3
_CHUNK = 1024 * 1024


class ArtifactError(Exception):
    """Artifact cannot be safely staged; deny installation."""


@dataclass(frozen=True, slots=True)
class StagedArtifact:
    path: Path
    sha256: str
    size: int
    device: int
    inode: int
    ctime_ns: int


def _private_dir(root: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise ArtifactError("Staging directory must already exist")
    if root.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ArtifactError("Staging directory must have mode 0700")


def _within_approved_roots(source: Path, allowed_roots: tuple[Path, ...]) -> bool:
    return any(source.is_relative_to(root.resolve(strict=True)) for root in allowed_roots)


def stage_apk(
    source_path: Path,
    *,
    allowed_roots: tuple[Path, ...],
    staging_dir: Path,
    max_bytes: int = MAX_APK_BYTES,
) -> StagedArtifact:
    """Copy approved input to an independent, private staging inode.

    Never trust a path after checking it. Open with O_NOFOLLOW and bind the
    copied digest to an out-of-band signed approval before any future install.
    """
    source = Path(source_path)
    target_tmp: Path | None = None
    completed = False
    if max_bytes < 4 or max_bytes > MAX_APK_BYTES:
        raise ValueError("Invalid maximum APK size")
    try:
        _private_dir(staging_dir)
        if not source.is_absolute() or source.suffix.lower() != ".apk" or source.is_symlink():
            raise ArtifactError("Invalid or linked APK path")
        resolved = source.resolve(strict=True)
        if not _within_approved_roots(resolved, allowed_roots):
            raise ArtifactError("APK source is outside approved roots")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        fd = os.open(source, flags)
        try:
            before = os.fstat(fd)
            path_stat = os.stat(source, follow_symlinks=False)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_dev != path_stat.st_dev
                or before.st_ino != path_stat.st_ino
            ):
                raise ArtifactError("APK path changed during inspection")
            if not 4 <= before.st_size <= max_bytes:
                raise ArtifactError("APK size is outside the approved bounds")
            destination_fd, name = tempfile.mkstemp(prefix="apk-", suffix=".apk", dir=staging_dir)
            target_tmp = Path(name)
            digest = hashlib.sha256()
            size = 0
            with (
                os.fdopen(destination_fd, "wb") as destination,
                os.fdopen(fd, "rb", closefd=False) as origin,
            ):
                first = origin.read(4)
                if first != b"PK\x03\x04":
                    raise ArtifactError("APK does not have a ZIP local-file header")
                destination.write(first)
                digest.update(first)
                size += 4
                while part := origin.read(_CHUNK):
                    size += len(part)
                    if size > max_bytes:
                        raise ArtifactError("APK grew beyond the approved size")
                    destination.write(part)
                    digest.update(part)
                destination.flush()
                os.fsync(destination.fileno())
            after = os.fstat(fd)
            if size != before.st_size or (
                before.st_dev,
                before.st_ino,
                before.st_mtime_ns,
                before.st_size,
            ) != (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_size):
                raise ArtifactError("APK changed while being staged")
        finally:
            os.close(fd)
        os.chmod(target_tmp, 0o400)
        staged = target_tmp.stat()
        output = StagedArtifact(
            target_tmp,
            digest.hexdigest(),
            size,
            staged.st_dev,
            staged.st_ino,
            staged.st_ctime_ns,
        )
        completed = True
        return output
    except (OSError, RuntimeError) as error:
        raise ArtifactError("APK staging failed") from error
    finally:
        # Always clear a failed staging attempt, including a failure *after*
        # chmod(0400). A successfully returned artifact is cleaned by its owner.
        if not completed and target_tmp is not None:
            try:
                target_tmp.unlink(missing_ok=True)
            except OSError:
                pass


def verify_staged(artifact: StagedArtifact, *, max_bytes: int = MAX_APK_BYTES) -> bool:
    """Check same inode and exact bytes immediately before invoking ADB."""
    try:
        if artifact.path.is_symlink():
            return False
        fd = os.open(artifact.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            before = os.fstat(fd)
            if (
                not stat.S_ISREG(before.st_mode)
                or (before.st_dev, before.st_ino) != (artifact.device, artifact.inode)
                or before.st_size != artifact.size
                or artifact.size > max_bytes
            ):
                return False
            digest = hashlib.sha256()
            with os.fdopen(fd, "rb", closefd=False) as handle:
                while part := handle.read(_CHUNK):
                    digest.update(part)
            after = os.fstat(fd)
            return digest.hexdigest() == artifact.sha256 and (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ) == (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        finally:
            os.close(fd)
    except (OSError, RuntimeError):
        return False


def remove_staged(artifact: StagedArtifact) -> None:
    """Never remove a path replaced by another inode."""
    try:
        st = artifact.path.lstat()
        if not stat.S_ISREG(st.st_mode) or (st.st_dev, st.st_ino, st.st_ctime_ns) != (
            artifact.device,
            artifact.inode,
            artifact.ctime_ns,
        ):
            return
        artifact.path.unlink()
    except FileNotFoundError:
        return
