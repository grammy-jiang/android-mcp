#!/usr/bin/env python3
"""Fail-closed, per-module Python coverage and physical module-size gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def check_policy(root: Path, report_path: Path, policy_path: Path) -> list[str]:
    """Return actionable errors instead of silently ignoring missing modules."""
    errors: list[str] = []
    policy = json.loads(policy_path.read_text(encoding="utf-8"))["python"]
    limit = policy["max_physical_lines_per_module"]
    source = root / "host" / "src" / "android_mcp_host"
    if not source.is_dir():
        return [f"Missing production source directory: {source}"]

    for folder in (root / "host" / "src", root / "host" / "tests", root / "scripts"):
        for path in sorted(folder.rglob("*.py")) if folder.exists() else []:
            lines = len(path.read_text(encoding="utf-8").splitlines())
            if lines > limit:
                errors.append(f"{path.relative_to(root)}: {lines} lines exceed {limit}")

    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not report.get("meta", {}).get("branch_coverage"):
        errors.append("Coverage report must have branch_coverage enabled")
    raw_files = report.get("files", {})
    if not isinstance(raw_files, dict) or not raw_files:
        return errors + ["Missing per-file coverage evidence"]

    files = {
        str(Path(name).as_posix()).lstrip("./"): details
        for name, details in raw_files.items()
    }
    exempt = set(policy["coverage_exempt_entrypoints"])
    production = {
        path.relative_to(root / "host").as_posix() for path in source.rglob("*.py")
    } - exempt
    if not production:
        errors.append("No production modules found for the coverage gate")

    critical = set(policy["coverage_critical_modules"])
    for name in sorted(critical - production):
        errors.append(f"Critical coverage policy names missing module: {name}")

    for name in sorted(production):
        evidence = files.get(name)
        if evidence is None:
            errors.append(f"Missing coverage report for production module: {name}")
            continue
        summary = evidence.get("summary", {})
        score = summary.get("percent_covered")
        if not isinstance(score, (int, float)):
            errors.append(f"Invalid coverage evidence for {name}")
            continue
        minimum = (
            policy["coverage_critical_minimum"]
            if name in critical
            else policy["coverage_default_minimum"]
        )
        if score + 0.000001 < minimum:
            errors.append(f"{name}: coverage {score:.2f}% below {minimum:.2f}%")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--policy", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    report = args.report or root / "host" / ".coverage.json"
    policy = args.policy or root / "quality-policy.json"
    errors = check_policy(root, report, policy)
    for error in errors:
        print("QUALITY FAIL:", error)
    if errors:
        return 1
    print("Quality policy passed: module size and per-module branch coverage.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
