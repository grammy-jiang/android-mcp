#!/usr/bin/env python3
"""Cross-platform local developer bootstrap and read-only environment doctor."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(argv: list[str], *, timeout: int = 45) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv, cwd=ROOT, capture_output=True, text=True, check=False, timeout=timeout
    )


def doctor(require_hooks: bool = False) -> tuple[dict[str, object], list[str]]:
    problems: list[str] = []
    git = shutil.which("git")
    uv = shutil.which("uv")
    output: dict[str, object] = {
        "repository": str(ROOT),
        "python": sys.version.split()[0],
        "git": bool(git),
        "uv": bool(uv),
        "adb_optional": bool(shutil.which("adb")),
        "java_optional": bool(shutil.which("java")),
        "android_sdk_optional": bool(
            os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
        ),
    }

    if git:
        top = _run([git, "rev-parse", "--show-toplevel"])
        output["git_root_valid"] = (
            top.returncode == 0 and Path(top.stdout.strip()) == ROOT
        )
        if not output["git_root_valid"]:
            problems.append("Expected a Git repository at the project root")
        status = _run([git, "status", "--porcelain=v1"])
        output["dirty_warning"] = bool(status.stdout.strip())
        if status.returncode != 0:
            problems.append("Cannot read Git worktree state")
        hook_base = _run([git, "rev-parse", "--git-path", "hooks"])
        if hook_base.returncode == 0:
            path = Path(hook_base.stdout.strip())
            if not path.is_absolute():
                path = ROOT / path
            hooks = {
                kind: (path / kind).is_file() and os.access(path / kind, os.X_OK)
                for kind in ("pre-commit", "pre-push")
            }
        else:
            hooks = {"pre-commit": False, "pre-push": False}
        output["hooks_installed"] = hooks
        if require_hooks and not all(hooks.values()):
            problems.append(
                "Missing configured pre-commit/pre-push hooks; run bootstrap"
            )
    else:
        problems.append("Git is required")

    if uv:
        uv_result = _run([uv, "--version"])
        output["uv_version"] = uv_result.stdout.strip()
        if uv_result.returncode != 0:
            problems.append("uv --version failed")
        lock = _run(
            [
                uv,
                "lock",
                "--check",
                "--offline",
                "--project",
                "host",
                "--python",
                sys.executable,
            ]
        )
        output["lock_consistent"] = lock.returncode == 0
        if lock.returncode != 0:
            problems.append("host/uv.lock is missing or out of sync")
    else:
        problems.append("uv is required")

    for path in ("host/pyproject.toml", "host/uv.lock", ".pre-commit-config.yaml"):
        if not (ROOT / path).is_file():
            problems.append(f"Missing project infrastructure: {path}")
    output["status"] = "ok" if not problems else "needs_attention"
    return output, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts/dev.py")
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("doctor", help="Read-only checkout/toolchain diagnostic.")
    d.add_argument("--json", action="store_true")
    d.add_argument("--require-hooks", action="store_true")
    sub.add_parser("bootstrap", help="Sync locked tools and install Git hooks.")
    sub.add_parser("check", help="Run all local Host quality gates.")
    args = parser.parse_args(argv)

    if args.command == "bootstrap":
        uv = shutil.which("uv")
        if not uv:
            parser.error("Install uv before bootstrap")
        commands = [
            [uv, "sync", "--project", "host", "--locked", "--group", "dev"],
            [
                uv,
                "run",
                "--project",
                "host",
                "--locked",
                "--group",
                "dev",
                "pre-commit",
                "install",
                "--install-hooks",
                "--hook-type",
                "pre-commit",
                "--hook-type",
                "pre-push",
            ],
        ]
        for command in commands:
            if subprocess.run(command, cwd=ROOT, check=False).returncode != 0:
                return 1
        result, problems = doctor(require_hooks=True)
        print(json.dumps(result, indent=2, sort_keys=True))
        return int(bool(problems))

    if args.command == "check":
        return subprocess.run(
            ["bash", "scripts/check-host.sh"], cwd=ROOT, check=False
        ).returncode

    result, problems = doctor(require_hooks=args.require_hooks)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("Developer environment:", result["status"])
        print("Host lock consistency:", result.get("lock_consistent", "unknown"))
        print("Git hooks:", result.get("hooks_installed", "unknown"))
        print("ADB (optional):", result["adb_optional"])
        print("Android SDK (optional):", result["android_sdk_optional"])
        if result.get("dirty_warning"):
            print("Note: working tree has changes (not treated as an error).")
    for problem in problems:
        print("ERROR:", problem, file=sys.stderr)
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
