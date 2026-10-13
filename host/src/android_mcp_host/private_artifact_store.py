"""Owner-scoped, crash-recoverable Host private artifact records.

This service cannot write to arbitrary external paths or expose artifact
bytes through MCP metadata.
"""

from __future__ import annotations

import hashlib
import hmac
import itertools
import math
import os
import secrets
import sqlite3
import stat
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from android_mcp_host.private_artifact_support import (
    _FILENAME,
    _HANDLE,
    _OBJECT,
    _OWNER,
    MAX_BYTES,
    MAX_RECORDS,
    MAX_TOTAL_BYTES,
    MAX_TTL_S,
    SCAN_LIMIT,
    ArtifactStoreError,
    _private_directory,
    _read_secret,
    _validate_mime,
)
from android_mcp_host.private_artifact_support import (
    get_artifact_metadata_schema as _get_artifact_metadata_schema,
)


def get_artifact_metadata_schema() -> dict[str, Any]:
    """Return the packaged metadata-only MCP Tool Schema."""
    return _get_artifact_metadata_schema()


class PrivateArtifactStore:
    """Durable private Host store with opaque handles and bounded retention."""

    def __init__(
        self,
        root: Path,
        *,
        max_artifact_bytes: int = 8 * 1024 * 1024,
        max_total_bytes: int = 32 * 1024 * 1024,
        max_records: int = 256,
        clock: Callable[[], float] = time.time,
        token_factory: Callable[[int], str] = secrets.token_urlsafe,
    ) -> None:
        if not root.is_absolute() or ".." in root.parts or len(str(root)) > 1024:
            raise ArtifactStoreError("UNTRUSTED_ROOT")
        if (
            type(max_artifact_bytes) is not int
            or not 1 <= max_artifact_bytes <= MAX_BYTES
            or type(max_total_bytes) is not int
            or not max_artifact_bytes <= max_total_bytes <= MAX_TOTAL_BYTES
            or type(max_records) is not int
            or not 1 <= max_records <= MAX_RECORDS
        ):
            raise ValueError("Invalid private artifact quota")
        self._root = root
        self._objects = root / "objects"
        self._db_path = root / "index.sqlite3"
        self._clock = clock
        self._token_factory = token_factory
        self._max_artifact = max_artifact_bytes
        self._max_total = max_total_bytes
        self._max_records = max_records
        _private_directory(root)
        _private_directory(self._objects)
        self._secret = _read_secret(root / ".secret")
        try:
            if self._db_path.is_symlink():
                raise ArtifactStoreError("UNTRUSTED_ROOT")
            if self._db_path.exists():
                info = self._db_path.lstat()
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) & 0o077
                    or info.st_nlink != 1
                ):
                    raise ArtifactStoreError("UNTRUSTED_ROOT")
            with self._connection() as db:
                db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS records (
                        handle TEXT PRIMARY KEY,
                        owner_key TEXT NOT NULL,
                        object_key TEXT NOT NULL,
                        digest TEXT NOT NULL,
                        mime TEXT NOT NULL,
                        size INTEGER NOT NULL,
                        created REAL NOT NULL,
                        expires REAL NOT NULL,
                        revoked INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
                db.execute("CREATE INDEX IF NOT EXISTS records_expiry ON records(expires)")
            os.chmod(self._db_path, 0o600)
        except (sqlite3.Error, OSError) as error:
            raise ArtifactStoreError("STORAGE_FAILURE") from error
        self.cleanup()

    @staticmethod
    def validate_owner(owner: str) -> bool:
        return isinstance(owner, str) and _OWNER.fullmatch(owner) is not None

    def _owner_key(self, owner: str) -> str:
        if not self.validate_owner(owner):
            raise ArtifactStoreError("INVALID_OWNER")
        return hmac.new(self._secret, owner.encode("ascii"), hashlib.sha256).hexdigest()

    def _object_key(self, owner_key: str, digest: str) -> str:
        return hmac.new(
            self._secret, f"{owner_key}:{digest}".encode("ascii"), hashlib.sha256
        ).hexdigest()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        db: sqlite3.Connection | None = None
        try:
            db = sqlite3.connect(str(self._db_path), timeout=10.0, isolation_level=None)
            db.execute("PRAGMA busy_timeout=10000")
            yield db
        except sqlite3.Error as error:
            raise ArtifactStoreError("STORAGE_FAILURE") from error
        finally:
            if db is not None:
                db.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def _read_object(self, object_key: str, digest: str, expected_size: int) -> bytes:
        if _OBJECT.fullmatch(object_key) is None:
            raise ArtifactStoreError("INTEGRITY_FAIL")
        fd: int | None = None
        try:
            fd = os.open(
                self._objects / object_key,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            )
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or stat.S_IMODE(info.st_mode) & 0o077
                or info.st_nlink != 1
                or info.st_size != expected_size
            ):
                raise ArtifactStoreError("INTEGRITY_FAIL")
            chunks: list[bytes] = []
            remaining = expected_size
            while remaining:
                part = os.read(fd, min(65536, remaining))
                if not part:
                    raise ArtifactStoreError("INTEGRITY_FAIL")
                chunks.append(part)
                remaining -= len(part)
            if os.read(fd, 1):
                raise ArtifactStoreError("INTEGRITY_FAIL")
            payload = b"".join(chunks)
            if hashlib.sha256(payload).hexdigest() != digest:
                raise ArtifactStoreError("INTEGRITY_FAIL")
            return payload
        except OSError as error:
            raise ArtifactStoreError("INTEGRITY_FAIL") from error
        finally:
            if fd is not None:
                os.close(fd)

    def _write_object(self, key: str, data: bytes, digest: str) -> None:
        target = self._objects / key
        if target.exists() or target.is_symlink():
            self._read_object(key, digest, len(data))
            return
        temporary = self._objects / ("tmp-" + secrets.token_hex(16))
        fd: int | None = None
        try:
            fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            sent = 0
            while sent < len(data):
                sent += os.write(fd, data[sent:])
            os.fsync(fd)
            os.close(fd)
            fd = None
            os.replace(temporary, target)
            directory_fd = os.open(self._objects, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as error:
            raise ArtifactStoreError("STORAGE_FAILURE") from error
        finally:
            if fd is not None:
                os.close(fd)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _metadata(row: tuple[Any, ...]) -> dict[str, Any]:
        handle, digest, mime, size, created, expires = row
        return {
            "handle": handle,
            "sha256": digest,
            "mime_type": mime,
            "size_bytes": size,
            "created_at": created,
            "expires_at": expires,
        }

    def put(
        self,
        owner: str,
        data: bytes,
        *,
        mime_type: str,
        filename: str | None = None,
        ttl_s: float = 86400.0,
    ) -> dict[str, Any]:
        """Commit an opaque record; data is never returned by the public MCP Tool."""
        owner_key = self._owner_key(owner)
        if filename is not None and (
            not isinstance(filename, str)
            or _FILENAME.fullmatch(filename) is None
            or filename in (".", "..")
        ):
            raise ArtifactStoreError("INVALID_FILENAME")
        if not isinstance(data, bytes):
            raise ArtifactStoreError("INVALID_CONTENT")
        if not 1 <= len(data) <= self._max_artifact:
            raise ArtifactStoreError("ARTIFACT_TOO_LARGE")
        if (
            type(ttl_s) not in (int, float)
            or not math.isfinite(ttl_s)
            or not 1 <= ttl_s <= MAX_TTL_S
        ):
            raise ArtifactStoreError("INVALID_TTL")
        _validate_mime(data, mime_type)
        digest = hashlib.sha256(data).hexdigest()
        object_key = self._object_key(owner_key, digest)
        now = self._clock()
        try:
            with self._transaction() as db:
                db.execute("DELETE FROM records WHERE expires <= ? OR revoked=1", (now,))
                records = db.execute("SELECT COUNT(*) FROM records").fetchone()[0]
                if records >= self._max_records:
                    raise ArtifactStoreError("QUOTA_EXCEEDED")
                objects = db.execute(
                    """
                    SELECT object_key, MAX(size)
                    FROM records WHERE expires > ? AND revoked=0
                    GROUP BY object_key
                    """,
                    (now,),
                ).fetchall()
                existing = {key for key, _ in objects}
                size = sum(value for _, value in objects)
                if object_key not in existing and size + len(data) > self._max_total:
                    raise ArtifactStoreError("QUOTA_EXCEEDED")
                self._write_object(object_key, data, digest)
                handle = ""
                for _ in range(5):
                    candidate = "art_" + self._token_factory(24)
                    if _HANDLE.fullmatch(candidate) is None:
                        raise ArtifactStoreError("STORAGE_FAILURE")
                    if (
                        db.execute("SELECT 1 FROM records WHERE handle=?", (candidate,)).fetchone()
                        is None
                    ):
                        handle = candidate
                        break
                if not handle:
                    raise ArtifactStoreError("STORAGE_FAILURE")
                expires = now + ttl_s
                db.execute(
                    """
                    INSERT INTO records
                        (handle, owner_key, object_key, digest, mime, size, created, expires)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        handle,
                        owner_key,
                        object_key,
                        digest,
                        mime_type,
                        len(data),
                        now,
                        expires,
                    ),
                )
            return self._metadata((handle, digest, mime_type, len(data), now, expires))
        except OSError as error:
            raise ArtifactStoreError("STORAGE_FAILURE") from error

    def _lookup(self, owner: str, handle: str) -> tuple[Any, ...]:
        if (
            not self.validate_owner(owner)
            or not isinstance(handle, str)
            or _HANDLE.fullmatch(handle) is None
        ):
            raise ArtifactStoreError("NOT_FOUND")
        owner_key = self._owner_key(owner)
        with self._connection() as db:
            row = db.execute(
                """
                SELECT handle, digest, mime, size, created, expires, object_key
                FROM records
                WHERE owner_key=? AND handle=? AND revoked=0 AND expires > ?
                """,
                (owner_key, handle, self._clock()),
            ).fetchone()
        if row is None:
            raise ArtifactStoreError("NOT_FOUND")
        return tuple(row)

    def read(self, owner: str, handle: str) -> bytes:
        """Trusted Host-internal bytes access with fresh owner/integrity checks."""
        row = self._lookup(owner, handle)
        return self._read_object(row[6], row[1], row[3])

    def public_metadata(self, owner: str, handle: str) -> dict[str, Any]:
        """Privacy-bounded Tool response, never binary bytes or private paths."""
        try:
            row = self._lookup(owner, handle)
        except ArtifactStoreError:
            return {
                "schema_version": 1,
                "runtime": "host",
                "status": "not_found",
                "artifact": None,
                "errors": [{"code": "NOT_FOUND", "message": "Artifact is unavailable"}],
            }
        return {
            "schema_version": 1,
            "runtime": "host",
            "status": "ok",
            "artifact": self._metadata(row[:6]),
            "errors": [],
        }

    def list_metadata(self, owner: str) -> list[dict[str, Any]]:
        """Host-internal bounded listing of only live owner records."""
        owner_key = self._owner_key(owner)
        with self._connection() as db:
            rows = db.execute(
                """
                SELECT handle, digest, mime, size, created, expires
                FROM records
                WHERE owner_key=? AND revoked=0 AND expires > ?
                ORDER BY created, handle LIMIT ?
                """,
                (owner_key, self._clock(), self._max_records),
            ).fetchall()
        return [self._metadata(row) for row in rows]

    def revoke(self, owner: str, handle: str) -> bool:
        if (
            not self.validate_owner(owner)
            or not isinstance(handle, str)
            or _HANDLE.fullmatch(handle) is None
        ):
            return False
        owner_key = self._owner_key(owner)
        with self._transaction() as db:
            cursor = db.execute(
                """
                UPDATE records SET revoked=1
                WHERE owner_key=? AND handle=? AND revoked=0 AND expires > ?
                """,
                (owner_key, handle, self._clock()),
            )
            return cursor.rowcount == 1

    def cleanup(self) -> dict[str, int]:
        """Bounded expiry/revocation and orphan cleanup under exclusive SQL lock."""
        now = self._clock()
        with self._transaction() as db:
            previous = db.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            db.execute("DELETE FROM records WHERE expires <= ? OR revoked=1", (now,))
            active_rows = db.execute("SELECT DISTINCT object_key FROM records").fetchall()
            active = {row[0] for row in active_rows}
            remaining = db.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            try:
                entries = list(itertools.islice(self._objects.iterdir(), SCAN_LIMIT + 1))
                if len(entries) > SCAN_LIMIT:
                    raise ArtifactStoreError("RESOURCE_LIMIT")
                for path in entries:
                    if path.is_symlink() or not path.is_file():
                        raise ArtifactStoreError("INTEGRITY_FAIL")
                    if path.name.startswith("tmp-"):
                        path.unlink()
                    elif _OBJECT.fullmatch(path.name) is None:
                        raise ArtifactStoreError("INTEGRITY_FAIL")
                    elif path.name not in active:
                        path.unlink()
            except OSError as error:
                raise ArtifactStoreError("STORAGE_FAILURE") from error
        return {
            "removed_records": previous - remaining,
            "remaining_records": remaining,
        }
