"""Owner-scoped SQLite cursor ledger for bounded sanitized synthetic Logcat.

No raw logs are written here. A signed position is single-consume, and the
SQLite immediate transaction makes duplicate concurrent polls fail closed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import stat
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from android_mcp_host.logcat_stream_support import valid_stored_events
from android_mcp_host.private_artifact_support import _private_directory, _read_secret

MAX_SESSIONS = 32
_CURSOR = re.compile(r"cur_[0-9]{3}_[0-9a-f]{32}\Z", re.ASCII)


class StreamStoreError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class LogcatStreamStore:
    """A small, private, durable cursor store; not a Logcat collection backend."""

    def __init__(self, root: Path, *, clock: Callable[[], float] = time.time) -> None:
        if not root.is_absolute() or ".." in root.parts or len(str(root)) > 1024:
            raise StreamStoreError("JOB_UNAVAILABLE")
        self._root = root
        self._index = root / "logcat-stream.sqlite3"
        self._clock = clock
        try:
            _private_directory(root)
            self._secret = _read_secret(root / ".logcat-stream-secret")
            with self._connect() as db:
                db.execute(
                    """CREATE TABLE IF NOT EXISTS logcat_streams (
                      job_id TEXT PRIMARY KEY, owner_key TEXT NOT NULL,
                      target_key TEXT NOT NULL, lifecycle_key TEXT NOT NULL,
                      request_key TEXT NOT NULL, state TEXT NOT NULL,
                      created REAL NOT NULL, expires REAL NOT NULL,
                      position INTEGER NOT NULL, count INTEGER NOT NULL,
                      dropped INTEGER NOT NULL, truncated INTEGER NOT NULL,
                      content_sha256 TEXT NOT NULL, events TEXT NOT NULL
                    )"""
                )
            os.chmod(self._index, 0o600)
        except (OSError, ValueError, sqlite3.Error) as error:
            raise StreamStoreError("JOB_UNAVAILABLE") from error

    def _check_index(self) -> None:
        if self._index.is_symlink():
            raise StreamStoreError("JOB_UNAVAILABLE")
        if self._index.exists():
            info = self._index.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077
                or info.st_nlink != 1
            ):
                raise StreamStoreError("JOB_UNAVAILABLE")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db: sqlite3.Connection | None = None
        try:
            self._check_index()
            db = sqlite3.connect(str(self._index), timeout=3, isolation_level=None)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA busy_timeout=3000")
            yield db
        except sqlite3.Error as error:
            raise StreamStoreError("JOB_UNAVAILABLE") from error
        finally:
            if db is not None:
                db.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def _key(self, value: str) -> str:
        return hmac.new(self._secret, value.encode("ascii"), hashlib.sha256).hexdigest()

    def _cursor(self, job_id: str, principal: tuple[str, ...], position: int) -> str:
        data = ":".join((job_id, *principal, str(position))).encode("ascii")
        signature = hmac.new(self._secret, data, hashlib.sha256).hexdigest()[:32]
        return f"cur_{position:03d}_{signature}"

    def _scope(self, owner: str, handle: str, lifecycle: str, request: str) -> tuple[str, ...]:
        return tuple(self._key(value) for value in (owner, handle, lifecycle, request))

    @staticmethod
    def _load(db: sqlite3.Connection, job_id: str, principal: tuple[str, ...]) -> sqlite3.Row:
        row = db.execute("SELECT * FROM logcat_streams WHERE job_id=?", (job_id,)).fetchone()
        if row is None or any(
            not hmac.compare_digest(str(row[field]), secret)
            for field, secret in zip(
                ("owner_key", "target_key", "lifecycle_key", "request_key"),
                principal,
                strict=True,
            )
        ):
            raise StreamStoreError("NOT_FOUND")
        return cast(sqlite3.Row, row)

    def insert(
        self,
        job_id: str,
        owner: str,
        handle: str,
        lifecycle: str,
        request: str,
        events: list[dict[str, str]],
        dropped: int,
        truncated: bool,
        ttl: int,
    ) -> dict[str, Any]:
        if (
            len(events) > 128
            or not valid_stored_events(events)
            or dropped < 0
            or not 1 <= ttl <= 120
            or not isinstance(truncated, bool)
        ):
            raise StreamStoreError("INVALID_INPUT")
        blob = json.dumps(events, separators=(",", ":"), ensure_ascii=True)
        if len(blob.encode("ascii")) > 32768:
            raise StreamStoreError("OUTPUT_LIMIT")
        principal = self._scope(owner, handle, lifecycle, request)
        now = float(self._clock())
        with self._tx() as db:
            db.execute("DELETE FROM logcat_streams WHERE expires<=?", (now,))
            if db.execute("SELECT COUNT(*) FROM logcat_streams").fetchone()[0] >= MAX_SESSIONS:
                raise StreamStoreError("JOB_UNAVAILABLE")
            db.execute(
                """INSERT INTO logcat_streams
                (job_id,owner_key,target_key,lifecycle_key,request_key,state,
                 created,expires,position,count,dropped,truncated,content_sha256,events)
                VALUES(?,?,?,?,?,'ready',?,?,0,?,?,?,?,?)""",
                (
                    job_id,
                    *principal,
                    now,
                    now + ttl,
                    len(events),
                    dropped,
                    int(truncated),
                    hashlib.sha256(blob.encode("ascii")).hexdigest(),
                    blob,
                ),
            )
        return self.peek(job_id, owner, handle, lifecycle, request)

    def peek(
        self, job_id: str, owner: str, handle: str, lifecycle: str, request: str
    ) -> dict[str, Any]:
        principal = self._scope(owner, handle, lifecycle, request)
        with self._tx() as db:
            row = self._load(db, job_id, principal)
            if self._clock() >= row["expires"]:
                db.execute(
                    "UPDATE logcat_streams SET state='expired',events='[]' WHERE job_id=?",
                    (job_id,),
                )
                db.commit()
                raise StreamStoreError("EXPIRED")
            return {
                "state": row["state"],
                "cursor": self._cursor(job_id, principal, row["position"])
                if row["state"] == "ready"
                else None,
                "next_index": row["position"],
                "total_events": row["count"],
                "dropped_events": row["dropped"],
                "truncated": bool(row["truncated"]),
                "retention_seconds": max(0, int(row["expires"] - self._clock())),
                "sha256": row["content_sha256"],
            }

    def poll(
        self,
        job_id: str,
        owner: str,
        handle: str,
        lifecycle: str,
        request: str,
        cursor: str,
        page_size: int,
    ) -> dict[str, Any]:
        principal = self._scope(owner, handle, lifecycle, request)
        with self._tx() as db:
            row = self._load(db, job_id, principal)
            if self._clock() >= row["expires"]:
                db.execute(
                    "UPDATE logcat_streams SET state='expired',events='[]' WHERE job_id=?",
                    (job_id,),
                )
                db.commit()
                raise StreamStoreError("EXPIRED")
            if row["state"] == "stopped":
                raise StreamStoreError("STOPPED")
            if row["state"] != "ready":
                raise StreamStoreError("ENDED")
            expected = self._cursor(job_id, principal, row["position"])
            if (
                not isinstance(cursor, str)
                or _CURSOR.fullmatch(cursor) is None
                or not hmac.compare_digest(cursor, expected)
            ):
                raise StreamStoreError("CURSOR_CONFLICT")
            content = str(row["events"])
            if (
                len(content) > 32768
                or hashlib.sha256(content.encode("ascii")).hexdigest() != row["content_sha256"]
            ):
                raise StreamStoreError("RECOVERY_REQUIRED")
            try:
                records: list[dict[str, str]] = json.loads(content)
            except (TypeError, ValueError) as error:
                raise StreamStoreError("RECOVERY_REQUIRED") from error
            if not valid_stored_events(records) or len(records) != row["count"]:
                raise StreamStoreError("RECOVERY_REQUIRED")
            pos = int(row["position"])
            end = min(pos + page_size, len(records))
            done = end == len(records)
            db.execute(
                "UPDATE logcat_streams SET position=?,state=?,events=? WHERE job_id=?",
                (end, "ended" if done else "ready", "[]" if done else content, job_id),
            )
            return {
                "state": "ended" if done else "ready",
                "entries": records[pos:end],
                "from_index": pos,
                "next_index": end,
                "cursor": None if done else self._cursor(job_id, principal, end),
                "total_events": len(records),
                "dropped_events": row["dropped"],
                "truncated": bool(row["truncated"]),
                "retention_seconds": max(0, int(row["expires"] - self._clock())),
            }

    def stop(self, job_id: str, owner: str, handle: str, lifecycle: str, request: str) -> str:
        principal = self._scope(owner, handle, lifecycle, request)
        with self._tx() as db:
            row = self._load(db, job_id, principal)
            if self._clock() >= row["expires"]:
                db.execute(
                    "UPDATE logcat_streams SET state='expired',events='[]' WHERE job_id=?",
                    (job_id,),
                )
                db.commit()
                raise StreamStoreError("EXPIRED")
            state = str(row["state"])
            if state == "ready":
                db.execute(
                    "UPDATE logcat_streams SET state='stopped',events='[]' WHERE job_id=?",
                    (job_id,),
                )
                return "stopped"
            return state

    def discard(self, job_id: str) -> None:
        with self._tx() as db:
            db.execute("DELETE FROM logcat_streams WHERE job_id=?", (job_id,))
