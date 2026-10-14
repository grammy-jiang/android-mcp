"""GitHub CI shallow checkout must recover authentic Git ancestry, not skip it."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.native_v3_ci_git_history import (
    CiHistoryError,
    ensure_complete_ledger_history,
)

REPO = Path(__file__).resolve().parents[1]


class NativeV3CiShallowHistoryTests(unittest.TestCase):
    def test_full_local_repo_is_noop_and_never_networks(self) -> None:
        result = ensure_complete_ledger_history(
            REPO, environ={"GITHUB_ACTIONS": "false", "GITHUB_REPOSITORY": "x/y"}
        )
        self.assertEqual(result, "COMPLETE_NO_FETCH")

    def test_shallow_local_checkout_cannot_be_silently_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bare = root / "origin"
            bare.mkdir()
            subprocess.run(["git", "init", "--quiet", str(bare)], check=True)
            subprocess.run(
                ["git", "-C", str(bare), "config", "user.email", "n@invalid.local"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(bare), "config", "user.name", "CI Native"], check=True
            )
            for idx in range(2):
                (bare / "x.txt").write_text(str(idx))
                subprocess.run(["git", "-C", str(bare), "add", "x.txt"], check=True)
                subprocess.run(
                    ["git", "-C", str(bare), "commit", "-q", "-m", f"merge {idx}"],
                    check=True,
                )
            shallow = root / "shallow"
            subprocess.run(
                ["git", "clone", "-q", "--depth=1", bare.as_uri(), str(shallow)],
                check=True,
            )
            with self.assertRaises(CiHistoryError):
                ensure_complete_ledger_history(
                    shallow,
                    environ={"GITHUB_ACTIONS": "false", "GITHUB_REPOSITORY": "x/y"},
                )

    def test_authenticated_ci_shallow_fetches_actual_history_and_checks_result(
        self,
    ) -> None:
        env = {
            "GITHUB_ACTIONS": "true",
            "GITHUB_REPOSITORY": "grammy-jiang/android-mcp",
        }
        commands = []

        def fake(argv, **kwargs):
            commands.append(tuple(argv))
            if argv[-2:] == ["rev-parse", "--is-shallow-repository"]:
                completed = (
                    "true"
                    if sum("fetch" in args for args in commands) == 0
                    else "false"
                )
                return subprocess.CompletedProcess(
                    argv, 0, stdout=completed + "\n", stderr=""
                )
            if argv[-3:] == ["remote", "get-url", "origin"]:
                return subprocess.CompletedProcess(
                    argv,
                    0,
                    stdout="https://github.com/grammy-jiang/android-mcp\n",
                    stderr="",
                )
            if "fetch" in argv:
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
            raise AssertionError("Unexpected subprocess", argv)

        with patch("scripts.native_v3_ci_git_history.subprocess.run", side_effect=fake):
            result = ensure_complete_ledger_history(REPO, environ=env)
        self.assertEqual(result, "CI_FETCHED_COMPLETE_HISTORY")
        self.assertEqual(sum("fetch" in command for command in commands), 1)
        self.assertTrue(
            any(
                "--unshallow" in command and "--no-tags" in command
                for command in commands
            )
        )

    def test_shallow_ci_rejects_foreign_repository_or_mismatched_origin(self) -> None:
        known = {
            "GITHUB_ACTIONS": "true",
            "GITHUB_REPOSITORY": "grammy-jiang/android-mcp",
        }

        def fake(argv, **kwargs):
            if argv[-2:] == ["rev-parse", "--is-shallow-repository"]:
                return subprocess.CompletedProcess(argv, 0, stdout="true\n", stderr="")
            if argv[-3:] == ["remote", "get-url", "origin"]:
                return subprocess.CompletedProcess(
                    argv, 0, stdout="https://github.com/attacker/fork\n", stderr=""
                )
            raise AssertionError("No fetch allowed for attacker")

        with patch("scripts.native_v3_ci_git_history.subprocess.run", side_effect=fake):
            with self.assertRaises(CiHistoryError):
                ensure_complete_ledger_history(REPO, environ=known)
            with self.assertRaises(CiHistoryError):
                ensure_complete_ledger_history(
                    REPO,
                    environ={
                        "GITHUB_ACTIONS": "true",
                        "GITHUB_REPOSITORY": "evil/fork",
                    },
                )

    def test_failed_unshallow_or_still_shallow_fails_closed(self) -> None:
        env = {
            "GITHUB_ACTIONS": "true",
            "GITHUB_REPOSITORY": "grammy-jiang/android-mcp",
        }

        def fake(argv, **kwargs):
            if argv[-2:] == ["rev-parse", "--is-shallow-repository"]:
                return subprocess.CompletedProcess(argv, 0, stdout="true\n", stderr="")
            if argv[-3:] == ["remote", "get-url", "origin"]:
                return subprocess.CompletedProcess(
                    argv,
                    0,
                    stdout="https://github.com/grammy-jiang/android-mcp\n",
                    stderr="",
                )
            if "fetch" in argv:
                return subprocess.CompletedProcess(
                    argv, 1, stdout="", stderr="fetch denied"
                )
            raise AssertionError(argv)

        with (
            patch("scripts.native_v3_ci_git_history.subprocess.run", side_effect=fake),
            self.assertRaises(CiHistoryError),
        ):
            ensure_complete_ledger_history(REPO, environ=env)


if __name__ == "__main__":
    unittest.main()
