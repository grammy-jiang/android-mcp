"""SQLite persistence for local leases and approval replay protection.

This store coordinates *host processes*, not the future Android Native MCP.
Cross-runtime mutation is deliberately blocked until a second native lease
protocol has been reviewed and implemented.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
import stat
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

Clock = Callable[[], float]


class StateError(Exception):
    """Storage or coordination failure; deny mutation on this exception."""


@dataclass(frozen=True, slots=True)
class Lease:
    device_id: str
    owner: str  # private random token; never write to MCP logs
    fence: int
    expires_at: float


class StateStore:
    """A private, fail-closed durable state database for one host installation."""

    def __init__(self, database: Path, *, clock: Clock = time.time) -> None:
        self.path = Path(database)
        self._clock = clock
        self._prepare_directory()
        self._initialize()

    def _prepare_directory(self) -> None:
        directory = self.path.parent
        if not directory.is_dir() or directory.is_symlink():
            raise StateError("State directory must already exist and not be a symlink")
        if directory.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise StateError("State directory must have mode 0700")
        if directory.stat().st_uid != os.getuid():
            raise StateError("State directory must be owned by current user")
        if self.path.is_symlink():
            raise StateError("State file symlinks are forbidden")
        if self.path.exists() and (
            not self.path.is_file()
            or self.path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO)
            or self.path.stat().st_uid != os.getuid()
        ):
            raise StateError("State database must be owned by current user and have mode 0600")

    def _connect(self) -> sqlite3.Connection:
        self._prepare_directory()
        try:
            fd = os.open(
                self.path, os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600
            )
        except FileExistsError:
            pass
        else:
            os.close(fd)
        self._prepare_directory()
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS lease_epochs(
                    device_id TEXT PRIMARY KEY, last_fence INTEGER NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS active_leases(
                    device_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    fence INTEGER NOT NULL, expires_at REAL NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS consumed_grants(
                    nonce TEXT PRIMARY KEY, consumed_at REAL NOT NULL,
                    plan_digest TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS lease_clock(
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    last_now REAL NOT NULL)""")
            conn.execute("INSERT OR IGNORE INTO lease_clock VALUES (1, 0)")

    def acquire(self, device_id: str, *, ttl_s: float = 180) -> Lease | None:
        from android_mcp_host.security.identity import fingerprint

        # Validate using the same fixed serial grammar as the plan fingerprint.
        fingerprint(device_id=device_id, kind="lease", argv_suffix=("lease",))
        if not 1 <= ttl_s <= 300:
            raise ValueError("Lease TTL must be between 1 and 300 seconds")
        now = self._clock()
        with closing(self._connect()) as conn, conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                previous = conn.execute(
                    "SELECT last_now FROM lease_clock WHERE singleton=1"
                ).fetchone()
                if previous is None or now < previous[0] - 1:
                    raise StateError("Host clock moved backwards; lease safety unknown")
                conn.execute("UPDATE lease_clock SET last_now=? WHERE singleton=1", (now,))
                active = conn.execute(
                    "SELECT expires_at FROM active_leases WHERE device_id=?", (device_id,)
                ).fetchone()
                if active is not None and active[0] > now:
                    conn.rollback()
                    return None
                epoch = conn.execute(
                    "SELECT last_fence FROM lease_epochs WHERE device_id=?", (device_id,)
                ).fetchone()
                fence = 1 if epoch is None else epoch[0] + 1
                if fence >= 2**62:
                    raise StateError("Lease fence exhausted")
                owner = secrets.token_hex(24)
                conn.execute(
                    "INSERT INTO lease_epochs(device_id,last_fence) VALUES(?,?) "
                    "ON CONFLICT(device_id) DO UPDATE SET last_fence=excluded.last_fence",
                    (device_id, fence),
                )
                conn.execute(
                    "INSERT INTO active_leases(device_id,owner,fence,expires_at) "
                    "VALUES(?,?,?,?) ON CONFLICT(device_id) DO UPDATE SET "
                    "owner=excluded.owner,fence=excluded.fence,expires_at=excluded.expires_at",
                    (device_id, owner, fence, now + ttl_s),
                )
                conn.commit()
                return Lease(device_id, owner, fence, now + ttl_s)
            except Exception:
                conn.rollback()
                raise

    def is_current(self, lease: Lease) -> bool:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT owner,fence,expires_at FROM active_leases WHERE device_id=?",
                (lease.device_id,),
            ).fetchone()
            return bool(
                row and row[0] == lease.owner and row[1] == lease.fence and row[2] > self._clock()
            )

    def release(self, lease: Lease) -> bool:
        with closing(self._connect()) as conn, conn:
            result = conn.execute(
                "DELETE FROM active_leases WHERE device_id=? AND owner=? AND fence=?",
                (lease.device_id, lease.owner, lease.fence),
            )
            return result.rowcount == 1

    def consume_grant(self, nonce: str, plan_digest: str) -> bool:
        now = self._clock()
        with closing(self._connect()) as conn, conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    "SELECT nonce FROM consumed_grants WHERE nonce=?", (nonce,)
                ).fetchone()
                if existing is not None:
                    conn.rollback()
                    return False
                conn.execute(
                    "INSERT INTO consumed_grants(nonce,consumed_at,plan_digest) VALUES(?,?,?)",
                    (nonce, now, plan_digest),
                )
                conn.commit()
                return True
            except Exception:
                conn.rollback()
                raise
