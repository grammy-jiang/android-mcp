"""Versioned status contract and typed validation for private Host job records."""

from __future__ import annotations

import json
import re
import sqlite3
from importlib.resources import files
from typing import Any, cast

_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_JOB_ID = re.compile(r"job_[A-Za-z0-9_-]{32}\Z", re.ASCII)
_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}\Z", re.ASCII)
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z", re.ASCII)
_WORKER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z", re.ASCII)


class JobStoreError(Exception):
    """A stable denial that does not echo private owner/job information."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Host job unavailable: {code}")


def get_job_status_schema() -> dict[str, Any]:
    value: Any = json.loads(
        files("android_mcp_host.wire_schemas")
        .joinpath("host-durable-job-status.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(value, dict):
        raise ValueError("Invalid packaged Host job status schema")
    return value


def _job_visible(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "job_id": row["job_id"],
        "state": row["state"],
        "plan_digest": row["plan_digest"],
        "result_digest": row["result_digest"],
        "created_at": row["created"],
        "updated_at": row["updated"],
        "finished_at": row["finished"],
        "attempts": row["attempts"],
        "generation": row["generation"],
        "cancel_requested": bool(row["cancel_requested"]),
        "execution_enabled": False,
    }


def _job_find(db: sqlite3.Connection, owner_key: str, job_id: str) -> sqlite3.Row:
    if not isinstance(job_id, str) or _JOB_ID.fullmatch(job_id) is None:
        raise JobStoreError("NOT_FOUND")
    row = db.execute(
        "SELECT * FROM jobs WHERE owner_key=? AND job_id=?", (owner_key, job_id)
    ).fetchone()
    if row is None:
        raise JobStoreError("NOT_FOUND")
    return cast(sqlite3.Row, row)
