#!/usr/bin/env python3
"""Source-backed Android Native V3 70-package + open-GAP checklist renderer.

An engineering checkbox is never a product-level Android acceptance proof.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

PACKAGE_COUNTS = (4, 6, 7, 8, 4, 4, 3, 4, 4, 3, 3, 4, 4, 3, 6, 3)
BASELINE_PACKAGE_IDS = frozenset(
    f"E{stage:02d}.{chr(ord('a') + ix)}"
    for stage, count in enumerate(PACKAGE_COUNTS)
    for ix in range(count)
)
ALLOWED_STATES = frozenset(
    {
        "OPEN",
        "PARTIAL",
        "IN_PROGRESS",
        "DONE_ENGINEERING",
        "BLOCKED_EXTERNAL",
    }
)
PACKAGE = re.compile(r"(?m)^\*\*(E\d\d\.[a-z]) — (.+?)\*\*")


def _require(condition: bool, why: str) -> None:
    if not condition:
        raise ValueError(why)


def _evidence_path(repo: Path, raw: str) -> Path:
    _require(
        isinstance(raw, str)
        and bool(re.fullmatch(r"docs/native-v3/[A-Za-z0-9._/-]+\.(?:md|json)", raw)),
        "Completed task must reference versioned evidence",
    )
    root = repo.resolve(strict=True)
    path = root / raw
    resolved = path.resolve()
    _require(
        resolved.is_relative_to(root / "docs/native-v3")
        and resolved.is_file()
        and not path.is_symlink()
        and resolved.stat().st_size > 50,
        "Completion evidence must exist in V3 docs",
    )
    return resolved


def build_checklist(
    status: dict[str, Any],
    overrides: dict[str, dict[str, Any]],
    plan: str,
    repo: Path,
) -> dict[str, Any]:
    planned = [
        {"id": match.group(1), "title": match.group(2)}
        for match in PACKAGE.finditer(plan)
    ]
    discovered = [item["id"] for item in planned]
    _require(
        len(planned) == 70 and len(set(discovered)) == 70, "Missing baseline package"
    )
    _require(
        set(discovered) == BASELINE_PACKAGE_IDS, "16-stage package inventory drift"
    )
    source = status.get("work_package_index")
    _require(isinstance(source, list) and len(source) == 70, "Source ledger missing")
    index = {item["id"]: item for item in source}
    _require(set(index) == BASELINE_PACKAGE_IDS, "Machine ledger drift")
    _require(set(overrides).issubset(BASELINE_PACKAGE_IDS), "Unknown task override")
    _require(
        status.get("production_features_done") == 0
        and status.get("emulator_features_done") == 0
        and status.get("verified_v3_cases") == 0
        and status.get("product") == "PRODUCT_INCOMPLETE",
        "Unverified V3 product status cannot be upgraded",
    )

    gaps = status.get("required_gaps")
    _require(isinstance(gaps, list) and len(gaps) >= 26, "Previously found GAP deleted")
    gap_ids = [item.get("id") for item in gaps]
    _require(
        len(set(gap_ids)) == len(gaps)
        and all(
            isinstance(i, str) and re.fullmatch(r"GAP-N(?:0[1-9]|1[0-9]|20)-\d{3}", i)
            for i in gap_ids
        ),
        "GAP ID invalid or aliased",
    )
    _require(
        all(f"GAP-N{n:02d}-001" in gap_ids for n in range(1, 21))
        and all(f"GAP-N17-{n:03d}" in gap_ids for n in range(2, 5)),
        "Previously discovered required security gap hidden",
    )
    _require(
        {"GAP-N01-002", "GAP-N01-003", "GAP-N07-002"}.issubset(set(gap_ids)),
        "Previously discovered semantic or fixture gap hidden",
    )

    tasks: list[dict[str, Any]] = []
    checked = 0
    for item in planned:
        name = item["id"]
        info = overrides.get(name, {"state": "OPEN", "note": ""})
        state = info.get("state")
        _require(state in ALLOWED_STATES, f"Unknown state for {name}")
        evidence = info.get("evidence", [])
        _require(isinstance(evidence, list), f"{name} bad evidence shape")
        note = info.get("note", "")
        _require(isinstance(note, str) and len(note) <= 360, "Unbounded note")
        if state == "DONE_ENGINEERING":
            _require(
                bool(evidence) and len(note) >= 8, f"{name} no completion evidence"
            )
            for path in evidence:
                _evidence_path(repo, path)
            checked += 1
        task = {
            **item,
            "kind": "package",
            "state": state,
            "checked": state == "DONE_ENGINEERING",
            "dependencies": index[name].get("dependencies", []),
            "note": note,
            "evidence": evidence,
        }
        tasks.append(task)
    for gap in gaps:
        _require(
            gap.get("status") in {"OPEN", "BLOCKED_EXTERNAL", "IN_PROGRESS"},
            "GAP closed without real Android evidence",
        )
        tasks.append(
            {
                "id": gap["id"],
                "title": gap.get("description", ""),
                "kind": "gap",
                "state": gap.get("status"),
                "checked": False,
                "dependencies": gap.get("requirements", []),
                "note": gap.get("next_action", ""),
                "evidence": [],
            }
        )
    _require(len(tasks) == 70 + len(gaps), "Task missing")
    return {
        "version": 1,
        "initial_work_packages": 70,
        "engineering_done": checked,
        "engineering_remaining": 70 - checked,
        "open_gaps": len(gaps),
        "capabilities_done": 0,
        "v3_acceptance_pass_real_e2e": 0,
        "product_status": "PRODUCT_INCOMPLETE",
        "tasks": tasks,
    }


def render_markdown(report: dict[str, Any]) -> str:
    """Emit ticked engineering tasks, outstanding tasks and all mandatory gaps."""
    tasks = report["tasks"]
    sections = [
        "# Android Native MCP V3 — Live implementation checklist",
        "",
        "Check one work package only after its scoped implementation, tests and",
        "recorded evidence pass. An engineering checkbox does NOT certify a",
        "product capability or an independent security review.",
        "",
        f"- Baseline work packages: **{report['initial_work_packages']}**",
        f"- Engineering packages checked: **{report['engineering_done']}**",
        f"- Remaining or partially complete packages: **{report['engineering_remaining']}**",
        f"- Required GAP tasks still open: **{report['open_gaps']}**",
        f"- Real product capabilities accepted: **{report['capabilities_done']}/20**",
        f"- New V3 real-E2E case receipts admitted: **{report['v3_acceptance_pass_real_e2e']}/192**",
        f"- Product state: **{report['product_status']}**",
        "",
        "The initial 70 items are not the finish line. New GAP tasks must",
        "be added to the source ledger and rendered here immediately.",
    ]
    for stage in range(16):
        prefix = f"E{stage:02d}"
        sections.extend(["", f"## {prefix} — Work packages", ""])
        for task in tasks:
            if task["kind"] != "package" or not task["id"].startswith(prefix + "."):
                continue
            mark = "x" if task["checked"] else " "
            title = f"{task['id']} — {task['title']}"
            title = f"~~{title}~~" if task["checked"] else f"**{title}**"
            deps = ", ".join(task["dependencies"]) if task["dependencies"] else "none"
            sections.append(
                f"- [{mark}] {title} — {task['state']}; dependencies: {deps}"
            )
            if task["note"]:
                sections.append(f"  - {task['note']}")
            if task["checked"]:
                links = ", ".join(
                    f"[evidence]({Path(path).name})" for path in task["evidence"]
                )
                sections.append(f"  - Evidence: {links}")
    sections.extend(["", "## Mandatory GAP remediation tasks", ""])
    for task in tasks:
        if task["kind"] != "gap":
            continue
        sections.append(f"- [ ] **{task['id']}** — {task['state']}: {task['title']}")
        if task["note"]:
            sections.append(f"  - Next: {task['note']}")
    sections.extend(
        [
            "",
            "## Repeatable completion workflow",
            "",
            "Investigate; write behavioral RED tests; implement actual Android API;",
            "run real MCP plus independent OS oracle; check denial, Stop, death,",
            "retry and cleanup; add GAP tasks for anything missing; integrate a",
            "passing PR; rerun post-merge checks; tick the package only when",
            "its scoped acceptance conditions are satisfied; then select the",
            "next dependency-ready package.",
            "",
            "Regenerate with python3 scripts/native_v3_todo.py --repo .",
            "",
        ]
    )
    return "\n".join(sections)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument(
        "--out", type=Path, default=Path("docs/native-v3/V3-LIVE-TODO.md")
    )
    args = parser.parse_args()
    repo = args.repo.resolve(strict=True)
    docs = repo / "docs/native-v3"
    status = json.loads((docs / "v3-execution-status.json").read_text())
    overrides = json.loads((docs / "v3-work-task-state.json").read_text())
    plan = (
        docs / "Android_Native_MCP_E2E_Implementation_Plan_V3_2026-10-14.md"
    ).read_text()
    report = build_checklist(status, overrides, plan, repo)
    target = (repo / args.out).resolve()
    if not target.is_relative_to(docs):
        raise ValueError("Task list must stay in docs/native-v3")
    target.write_text(render_markdown(report))
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "engineering_done",
                    "engineering_remaining",
                    "open_gaps",
                    "product_status",
                )
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
