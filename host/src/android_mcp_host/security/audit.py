"""Durable minimal audit journal: no device output, tokens or user secrets.

SHA-256 chaining detects accidental history changes; it is not a cryptographic
promise against a privileged attacker who can rewrite the entire database.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass

from android_mcp_host.security.store import StateStore

_EVENTS = frozenset({"deny", "begin", "end", "partial", "recover", "plan"})
_CODES = frozenset({"none", "authorized", "denied", "failed", "ok", "partial", "error", "blocked"})
_ZERO = "0" * 64


class AuditError(Exception):
    """Refuse mutations when the durable journal cannot be written."""


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event: str
    device_id: str
    operation: str
    plan_digest: str
    result_code: str

    def canonical(self, now: int) -> str:
        if self.event not in _EVENTS or self.result_code not in _CODES:
            raise ValueError("Audit event category is not allowlisted")
        if not (
            1 <= len(self.device_id) <= 128
            and 1 <= len(self.operation) <= 64
            and re.fullmatch(r"[0-9a-f]{64}", self.plan_digest)
        ):
            raise ValueError("Invalid audit identifier")
        return json.dumps(
            {
                "event": self.event,
                "device_id": self.device_id,
                "operation": self.operation,
                "plan_digest": self.plan_digest,
                "result_code": self.result_code,
                "at": now,
            },
            separators=(",", ":"),
            sort_keys=True,
        )


class AuditJournal:
    """Uses the same locally protected database as the one-time grant store."""

    def __init__(self, store: StateStore, *, clock: Callable[[], float] = time.time) -> None:
        self._store = store
        self._clock = clock
        with closing(store._connect()) as conn, conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS audit_events(
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                body TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                chain_hash TEXT NOT NULL)""")

    @staticmethod
    def _digest(previous: str, body: str) -> str:
        return hashlib.sha256((previous + "\n" + body).encode("utf-8")).hexdigest()

    def append(self, event: AuditEvent) -> int:
        body = event.canonical(int(self._clock()))
        try:
            with closing(self._store._connect()) as conn, conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT seq,body,prev_hash,chain_hash "
                    "FROM audit_events ORDER BY seq DESC LIMIT 1"
                ).fetchone()
                previous = row[3] if row is not None else _ZERO
                if row is not None and self._digest(row[2], row[1]) != row[3]:
                    raise AuditError("Audit chain head is inconsistent")
                cursor = conn.execute(
                    "INSERT INTO audit_events(body,prev_hash,chain_hash) VALUES(?,?,?)",
                    (body, previous, self._digest(previous, body)),
                )
                conn.commit()
                assert cursor.lastrowid is not None
                return cursor.lastrowid
        except (sqlite3.Error, OSError) as error:
            raise AuditError("Cannot persist mandatory audit event") from error

    def verify_chain(self) -> bool:
        try:
            with closing(self._store._connect()) as conn, conn:
                rows = conn.execute(
                    "SELECT seq,body,prev_hash,chain_hash FROM audit_events ORDER BY seq"
                ).fetchall()
        except (sqlite3.Error, OSError) as error:
            raise AuditError("Cannot read audit evidence") from error
        previous = _ZERO
        for expected, (seq, body, parent, digest) in enumerate(rows, start=1):
            if seq != expected or parent != previous or digest != self._digest(parent, body):
                return False
            previous = digest
        return True
