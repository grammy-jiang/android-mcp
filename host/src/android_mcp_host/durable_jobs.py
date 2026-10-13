"""Host-only durable job-state ledger, never a privileged command executor.

Only trusted Host components can authorize transitions. Public MCP exposes
owner-scoped status only; no dispatch, retry, or arbitrary shell arguments.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import os
import re
import secrets
import sqlite3
import stat
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from android_mcp_host.durable_job_support import (
    _DIGEST,
    _IDENTITY,
    _JOB_ID,
    _REQUEST_ID,
    _WORKER,
    JobStoreError,
    _job_find,
    _job_visible,
)
from android_mcp_host.durable_job_support import (
    get_job_status_schema as get_job_status_schema,
)
from android_mcp_host.private_artifact_support import _private_directory, _read_secret

MAX_JOBS = 4096
MAX_LEASE = 300.0
_EVENTS = {
    "prepared",
    "queued",
    "claimed",
    "succeeded",
    "failed",
    "cancelled",
    "uncertain",
    "reconciled",
}
_TERMINAL = frozenset({"succeeded", "failed", "cancelled"})


class DurableJobStore:
    """SQLite immediate transactions serialize competing synthetic workers."""

    def __init__(
        self,
        root: Path,
        *,
        clock: Callable[[], float] = time.time,
        lease_seconds: float = 30.0,
        max_records: int = 1000,
        token_factory: Callable[[int], str] = secrets.token_urlsafe,
    ) -> None:
        if not root.is_absolute() or ".." in root.parts or len(str(root)) > 1024:
            raise JobStoreError("UNTRUSTED_ROOT")
        if (
            type(lease_seconds) not in (float, int)
            or not math.isfinite(lease_seconds)
            or not 0 < lease_seconds <= MAX_LEASE
            or type(max_records) is not int
            or not 1 <= max_records <= MAX_JOBS
        ):
            raise ValueError("Invalid durable job retention or lease bounds")
        self._root = root
        self._index = root / "jobs.sqlite3"
        self._clock = clock
        self._lease = lease_seconds
        self._max_records = max_records
        self._token_factory = token_factory
        try:
            _private_directory(root)
            self._secret = _read_secret(root / ".job-secret")
            if self._index.is_symlink():
                raise JobStoreError("UNTRUSTED_ROOT")
            if self._index.exists():
                info = self._index.lstat()
                if (
                    not stat.S_ISREG(info.st_mode)
                    or stat.S_IMODE(info.st_mode) & 0o077
                    or info.st_uid != os.getuid()
                    or info.st_nlink != 1
                ):
                    raise JobStoreError("UNTRUSTED_ROOT")
            with self._connect() as db:
                db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS jobs (
                        job_id TEXT PRIMARY KEY,
                        owner_key TEXT NOT NULL,
                        request_key TEXT NOT NULL,
                        identity_key TEXT NOT NULL,
                        plan_digest TEXT NOT NULL,
                        state TEXT NOT NULL,
                        created REAL NOT NULL,
                        updated REAL NOT NULL,
                        finished REAL,
                        lease_expires REAL,
                        worker_key TEXT,
                        attempts INTEGER NOT NULL,
                        generation INTEGER NOT NULL,
                        result_digest TEXT,
                        cancel_requested INTEGER NOT NULL DEFAULT 0,
                        UNIQUE(owner_key, request_key)
                    )
                    """
                )
                db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS audit (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        job_id TEXT NOT NULL,
                        event TEXT NOT NULL,
                        at REAL NOT NULL
                    )
                    """
                )
            os.chmod(self._index, 0o600)
        except (sqlite3.Error, OSError) as error:
            raise JobStoreError("STORAGE_FAILURE") from error
        self.recover()

    @staticmethod
    def validate_owner(owner: str) -> bool:
        return (
            isinstance(owner, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_-]{0,63}", owner, re.ASCII) is not None
        )

    @staticmethod
    def _require_authorized(authorized: bool) -> None:
        if authorized is not True:
            raise JobStoreError("NOT_AUTHORIZED")

    @staticmethod
    def _now(clock: Callable[[], float]) -> float:
        moment = clock()
        if type(moment) not in (float, int) or not math.isfinite(moment) or moment < 0:
            raise JobStoreError("INVALID_CLOCK")
        return float(moment)

    def _key(self, value: str) -> str:
        return hmac.new(self._secret, value.encode("ascii"), hashlib.sha256).hexdigest()

    def _owner(self, owner: str) -> str:
        if not self.validate_owner(owner):
            raise JobStoreError("INVALID_OWNER")
        return self._key(owner)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db: sqlite3.Connection | None = None
        try:
            db = sqlite3.connect(str(self._index), timeout=10.0, isolation_level=None)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA busy_timeout=10000")
            yield db
        except sqlite3.Error as error:
            raise JobStoreError("STORAGE_FAILURE") from error
        finally:
            if db is not None:
                db.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._connect() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    @staticmethod
    def _event(db: sqlite3.Connection, job_id: str, event: str, now: float) -> None:
        assert event in _EVENTS
        db.execute("INSERT INTO audit(job_id,event,at) VALUES(?,?,?)", (job_id, event, now))

    _visible = staticmethod(_job_visible)
    _find = staticmethod(_job_find)

    def _checked(
        self,
        db: sqlite3.Connection,
        owner: str,
        job_id: str,
        identity: str,
    ) -> sqlite3.Row:
        if not isinstance(identity, str) or _IDENTITY.fullmatch(identity) is None:
            raise JobStoreError("STALE_IDENTITY")
        row = self._find(db, self._owner(owner), job_id)
        if not hmac.compare_digest(str(row["identity_key"]), self._key(identity)):
            raise JobStoreError("STALE_IDENTITY")
        return row

    def prepare(
        self,
        owner: str,
        request_id: str,
        plan_digest: str,
        *,
        identity: str,
        authorized: bool = False,
    ) -> dict[str, Any]:
        """Prepare one stable idempotent record; never begin execution."""
        self._require_authorized(authorized)
        owner_key = self._owner(owner)
        if not isinstance(request_id, str) or _REQUEST_ID.fullmatch(request_id) is None:
            raise JobStoreError("INVALID_REQUEST")
        if not isinstance(plan_digest, str) or _DIGEST.fullmatch(plan_digest) is None:
            raise JobStoreError("INVALID_PLAN")
        if not isinstance(identity, str) or _IDENTITY.fullmatch(identity) is None:
            raise JobStoreError("INVALID_IDENTITY")
        now = self._now(self._clock)
        request_key = self._key(owner_key + ":" + request_id)
        identity_key = self._key(identity)
        with self._tx() as db:
            previous = db.execute(
                "SELECT * FROM jobs WHERE owner_key=? AND request_key=?", (owner_key, request_key)
            ).fetchone()
            if previous is not None:
                if (
                    previous["plan_digest"] != plan_digest
                    or previous["identity_key"] != identity_key
                ):
                    raise JobStoreError("IDEMPOTENCY_CONFLICT")
                return self._visible(previous)
            count = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            if count >= self._max_records:
                raise JobStoreError("RESOURCE_LIMIT")
            job_id = ""
            for _ in range(5):
                candidate = "job_" + self._token_factory(24)
                if _JOB_ID.fullmatch(candidate) is None:
                    raise JobStoreError("STORAGE_FAILURE")
                if db.execute("SELECT 1 FROM jobs WHERE job_id=?", (candidate,)).fetchone() is None:
                    job_id = candidate
                    break
            if not job_id:
                raise JobStoreError("STORAGE_FAILURE")
            db.execute(
                """
                INSERT INTO jobs(
                    job_id,owner_key,request_key,identity_key,plan_digest,state,
                    created,updated,attempts,generation
                ) VALUES(?,?,?,?,?,'prepared',?,?,0,0)
                """,
                (job_id, owner_key, request_key, identity_key, plan_digest, now, now),
            )
            self._event(db, job_id, "prepared", now)
            row = self._find(db, owner_key, job_id)
            return self._visible(row)

    def queue(
        self, owner: str, job_id: str, *, identity: str, authorized: bool = False
    ) -> dict[str, Any]:
        self._require_authorized(authorized)
        now = self._now(self._clock)
        with self._tx() as db:
            row = self._checked(db, owner, job_id, identity)
            if row["state"] != "prepared":
                raise JobStoreError("INVALID_TRANSITION")
            db.execute("UPDATE jobs SET state='queued',updated=? WHERE job_id=?", (now, job_id))
            self._event(db, job_id, "queued", now)
            return self._visible(self._find(db, self._owner(owner), job_id))

    def claim(
        self,
        owner: str,
        job_id: str,
        worker_id: str,
        identity: str,
        *,
        authorized: bool = False,
    ) -> dict[str, Any]:
        self._require_authorized(authorized)
        if not isinstance(worker_id, str) or _WORKER.fullmatch(worker_id) is None:
            raise JobStoreError("INVALID_WORKER")
        now = self._now(self._clock)
        with self._tx() as db:
            row = self._checked(db, owner, job_id, identity)
            if row["state"] != "queued":
                if row["state"] == "prepared":
                    raise JobStoreError("INVALID_TRANSITION")
                raise JobStoreError("NOT_CLAIMABLE")
            db.execute(
                """
                UPDATE jobs SET state='running',updated=?,worker_key=?,
                    attempts=attempts+1,generation=generation+1,lease_expires=?
                WHERE job_id=?
                """,
                (now, self._key(worker_id), now + self._lease, job_id),
            )
            self._event(db, job_id, "claimed", now)
            return self._visible(self._find(db, self._owner(owner), job_id))

    def complete(
        self,
        owner: str,
        job_id: str,
        worker_id: str,
        generation: int,
        identity: str,
        *,
        authorized: bool = False,
        result_digest: str | None = None,
        failure_code: str | None = None,
    ) -> dict[str, Any]:
        self._require_authorized(authorized)
        if not isinstance(worker_id, str) or _WORKER.fullmatch(worker_id) is None:
            raise JobStoreError("INVALID_WORKER")
        if type(generation) is not int or generation < 1:
            raise JobStoreError("STALE_WORKER")
        if (result_digest is None) == (failure_code is None):
            raise JobStoreError("INVALID_RESULT")
        if result_digest is not None and (
            not isinstance(result_digest, str) or _DIGEST.fullmatch(result_digest) is None
        ):
            raise JobStoreError("INVALID_RESULT")
        if failure_code is not None and (
            not isinstance(failure_code, str)
            or re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", failure_code, re.ASCII) is None
        ):
            raise JobStoreError("INVALID_RESULT")
        now = self._now(self._clock)
        expired = False
        with self._tx() as db:
            row = self._checked(db, owner, job_id, identity)
            if row["state"] == "uncertain":
                raise JobStoreError("UNCERTAIN_RESULT")
            if row["state"] != "running":
                raise JobStoreError("INVALID_TRANSITION")
            if row["generation"] != generation or not hmac.compare_digest(
                str(row["worker_key"]), self._key(worker_id)
            ):
                raise JobStoreError("STALE_WORKER")
            if row["lease_expires"] is None or now > row["lease_expires"]:
                db.execute(
                    "UPDATE jobs SET state='uncertain',updated=?,lease_expires=NULL WHERE job_id=?",
                    (now, job_id),
                )
                self._event(db, job_id, "uncertain", now)
                expired = True
            else:
                state = "succeeded" if result_digest is not None else "failed"
                db.execute(
                    """
                    UPDATE jobs SET state=?,updated=?,finished=?,result_digest=?,
                        lease_expires=NULL WHERE job_id=?
                    """,
                    (state, now, now, result_digest, job_id),
                )
                self._event(db, job_id, state, now)
            result = self._visible(self._find(db, self._owner(owner), job_id))
        if expired:
            raise JobStoreError("UNCERTAIN_RESULT")
        return result

    def cancel(
        self, owner: str, job_id: str, *, identity: str, authorized: bool = False
    ) -> dict[str, Any]:
        self._require_authorized(authorized)
        now = self._now(self._clock)
        with self._tx() as db:
            row = self._checked(db, owner, job_id, identity)
            if row["state"] not in {"prepared", "queued", "running"}:
                raise JobStoreError("INVALID_TRANSITION")
            uncertain = row["state"] == "running"
            state = "uncertain" if uncertain else "cancelled"
            db.execute(
                """
                UPDATE jobs SET state=?,updated=?,finished=?,lease_expires=NULL,
                    cancel_requested=1 WHERE job_id=?
                """,
                (state, now, None if uncertain else now, job_id),
            )
            self._event(db, job_id, state, now)
            return self._visible(self._find(db, self._owner(owner), job_id))

    def reconcile(
        self,
        owner: str,
        job_id: str,
        *,
        identity: str,
        authorized: bool = False,
        evidence_digest: str,
        outcome: str,
    ) -> dict[str, Any]:
        self._require_authorized(authorized)
        if not isinstance(evidence_digest, str) or _DIGEST.fullmatch(evidence_digest) is None:
            raise JobStoreError("INVALID_EVIDENCE")
        if outcome not in {"succeeded", "failed"}:
            raise JobStoreError("INVALID_OUTCOME")
        now = self._now(self._clock)
        with self._tx() as db:
            row = self._checked(db, owner, job_id, identity)
            if row["state"] != "uncertain":
                raise JobStoreError("INVALID_TRANSITION")
            db.execute(
                """
                UPDATE jobs SET state=?,updated=?,finished=?,result_digest=?
                WHERE job_id=?
                """,
                (outcome, now, now, evidence_digest if outcome == "succeeded" else None, job_id),
            )
            self._event(db, job_id, "reconciled", now)
            return self._visible(self._find(db, self._owner(owner), job_id))

    def recover(self) -> int:
        """Never claim/re-execute expired worker leases; mark uncertain."""
        now = self._now(self._clock)
        with self._tx() as db:
            expired = db.execute(
                """
                SELECT job_id FROM jobs
                WHERE state='running' AND lease_expires <= ?
                ORDER BY job_id LIMIT ?
                """,
                (now, self._max_records),
            ).fetchall()
            for row in expired:
                db.execute(
                    """
                    UPDATE jobs SET state='uncertain',updated=?,lease_expires=NULL
                    WHERE job_id=? AND state='running'
                    """,
                    (now, row["job_id"]),
                )
                self._event(db, row["job_id"], "uncertain", now)
            return len(expired)

    def status(self, owner: str, job_id: str) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": 1,
            "runtime": "host",
            "status": "not_found",
            "job": None,
            "errors": [{"code": "NOT_FOUND", "message": "Job is unavailable"}],
        }
        if not self.validate_owner(owner):
            return result
        try:
            with self._connect() as db:
                row = self._find(db, self._owner(owner), job_id)
        except JobStoreError:
            return result
        return {
            "schema_version": 1,
            "runtime": "host",
            "status": "ok",
            "job": self._visible(row),
            "errors": [],
        }

    def list_status(self, owner: str) -> list[dict[str, Any]]:
        owner_key = self._owner(owner)
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM jobs WHERE owner_key=? ORDER BY created,job_id LIMIT ?
                """,
                (owner_key, self._max_records),
            ).fetchall()
            return [self._visible(row) for row in rows]

    def audit(self, owner: str, job_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            self._find(db, self._owner(owner), job_id)
            rows = db.execute(
                """
                SELECT sequence,event,at FROM audit
                WHERE job_id=? ORDER BY sequence LIMIT ?
                """,
                (job_id, self._max_records * 8),
            ).fetchall()
        return [
            {"sequence": row["sequence"], "event": row["event"], "at": row["at"]} for row in rows
        ]
