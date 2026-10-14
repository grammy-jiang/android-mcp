#!/usr/bin/env python3
"""Cold GitHub Actions shallow checkout repair for strict Native merge receipts.

Only an exact official repository Actions checkout may fetch history. This
does not bypass historical commit verification: after unshallowing the
existing strict git show / merge-base checks still run and may fail.
Ordinary user worktrees never fetch automatically or change Git state.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path


class CiHistoryError(ValueError):
    """CI could not independently prove full Native Git merge ancestry."""


_OFFICIAL_REPO = "grammy-jiang/android-mcp"
_OFFICIAL_HTTPS = re.compile(
    r"https://github\.com/grammy-jiang/android-mcp(?:\.git)?\Z",
    flags=re.IGNORECASE,
)


def _git(repo: Path, *argv: str, timeout: int = 15) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *argv],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CiHistoryError(
            "Git command unavailable for ancestry preflight"
        ) from error
    if result.returncode or len(result.stdout) > 512:
        raise CiHistoryError("Git ancestry preflight command failed")
    return result.stdout.strip()


def ensure_complete_ledger_history(
    repo: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Get actual commit history only in an exact GitHub Actions shallow clone.

    No simulated status; no test skip; no fake merge record. Provenance
    assertion remains in test_actual_merge_receipts_are_git_ancestral.
    """
    repo = repo.resolve(strict=True)
    if not repo.is_dir() or not (repo / ".git").exists():
        raise CiHistoryError("Git ancestry root is not a checkout")
    environment = environ if environ is not None else os.environ
    shallow = _git(repo, "rev-parse", "--is-shallow-repository")
    if shallow == "false":
        return "COMPLETE_NO_FETCH"
    if shallow != "true":
        raise CiHistoryError("Git shallow status is unknown")
    if (
        environment.get("GITHUB_ACTIONS") != "true"
        or environment.get("GITHUB_REPOSITORY") != _OFFICIAL_REPO
    ):
        raise CiHistoryError("Cannot unshallow outside official GitHub Actions")
    origin = _git(repo, "remote", "get-url", "origin")
    if _OFFICIAL_HTTPS.fullmatch(origin) is None:
        raise CiHistoryError("Unexpected CI remote URL; refuse history fetch")
    # Authenticated checkout already owns the official public remote. This
    # is a read-only history fetch into an ephemeral Actions checkout, not a
    # GitHub permission change, token prompt, commit rewrite, or approval.
    _git(
        repo,
        "fetch",
        "--unshallow",
        "--no-tags",
        "--filter=blob:none",
        "origin",
        timeout=120,
    )
    if _git(repo, "rev-parse", "--is-shallow-repository") != "false":
        raise CiHistoryError("Git remained shallow; do not claim merge proof")
    return "CI_FETCHED_COMPLETE_HISTORY"
