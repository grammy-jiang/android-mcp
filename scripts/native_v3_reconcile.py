#!/usr/bin/env python3
"""E00 truthful requirement, work package and gap reconciliation.

This tool intentionally does NOT count a production Kotlin class, merge,
APK build or old ledger row as a real Android MCP feature acceptance.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def reconcile(
    registry: dict[str, Any],
    old_ledger: dict[str, Any],
    plan_text: str,
    gateway_source: str,
) -> dict[str, Any]:
    packages = []
    package_re = re.compile(r"\*\*(E\d\d\.[a-z]) — ([^\n*]+)\*\*")
    for match in package_re.finditer(plan_text):
        package_id, objective = match.groups()
        block = plan_text[match.end() : match.end() + 450]
        deps_match = re.search(r"Dependencies: ([^;\n]+)", block)
        dependencies = []
        if deps_match:
            dependencies = re.findall(r"E\d\d\.[a-z]", deps_match.group(1))
        packages.append(
            {
                "id": package_id,
                "objective": objective.strip(),
                "dependencies": dependencies,
                "source": "V3 approved implementation plan prose; not the unavailable original registry JSON",
                "status": "NOT_VERIFIED_DONE",
            }
        )
    if len(packages) != 70 or len({p["id"] for p in packages}) != 70:
        raise ValueError(
            "V3 source plan must contain exactly 70 uniquely identified packages"
        )
    old = {item["id"]: item for item in old_ledger.get("capabilities", [])}
    tools = sorted(
        set(re.findall(r'\bserver\.addTool\(\s*name\s*=\s*"([^"]+)"', gateway_source))
    )
    families = registry.get("capability_families", [])
    if len(families) != 20:
        raise ValueError("V3 registry must define all 20 capability families")
    status = {}
    gaps = []
    for family in families:
        identity = family["capability_id"]
        role = family["target_scope"]
        tests = family["tests"]
        if len(tests) != 8:
            raise ValueError(f"V3 family {identity} missing acceptance cases")
        if identity == "N19":
            release_gate = (
                "BLOCKED_EXTERNAL: separately approved managed Device Owner laboratory"
            )
            authority = "Enterprise test-lab owner + Android OS Device Owner"
        elif identity == "N20":
            release_gate = "UNSUPPORTED_BY_PLATFORM: ordinary APK Root/ROM; verified Host read-only fallback outstanding"
            authority = "Host platform safety owner + independent release review"
        elif role == "SECURITY_FOUNDATION":
            release_gate = "BLOCKED_EXTERNAL: independent security review before production enablement"
            authority = "Operator-paired Host identity + independent security reviewer"
        elif role in ("SENSITIVE_USER_CONSENT", "OPTIONAL_CONSENT"):
            release_gate = "ANDROID_OS_USER_CONSENT + authenticated scoped Host authorization + independent security review"
            authority = "Android foreground user + scoped operator + independent security reviewer"
        elif role == "AUTHORIZED_WRITE":
            release_gate = "ANDROID_OS_USER_CONFIRMATION + signed grant + durable Native lease + review"
            authority = (
                "Android foreground user + operator + independent security reviewer"
            )
        else:
            release_gate = (
                "AUTHENTICATED_READ + verified emulator matrix + independent acceptance"
            )
            authority = "Bound Host identity + test owner + release reviewer"
        # The registry is a planned spec; old mock/inert states cannot prove a
        # feature works even if a prior ledger claims it is executable.
        tested = all(test.get("status") == "PASS_REAL_E2E" for test in tests)
        # Without independently attested receipts and release approvals, no
        # feature can be marked real-e2e-verified, even if the text is forged.
        real_e2e_verified = False
        status[identity] = {
            "family": family["family"],
            "profile": role,
            "old_ledger_status": old.get(identity, {}).get("status", "NOT_PRESENT"),
            "public_tool_source_inventory": tools if identity == "N01" else [],
            "real_e2e_verified": real_e2e_verified,
            "v3_planned_cases": [test["test_id"] for test in tests],
            "planned_spec_cases_all_claim_pass": tested,
            "release_gate": release_gate,
            "authority": authority,
            "status": "NOT_DONE",
        }
        gaps.append(
            {
                "id": f"GAP-{identity}-001",
                "status": "OPEN",
                "release_blocking": identity != "N20",
                "owner": "Native Android implementation"
                if identity != "N20"
                else "Host fallback integration",
                "source": "E00 startup reality audit; not a completed/merged work package",
                "description": "No attested complete real Native MCP → authorized Android API → independent OS effect path",
                "requirements": [test["test_id"] for test in tests],
                "next_action": (
                    "Demonstrate scoped read-only Host fallback without Root or ROM commands"
                    if identity == "N20"
                    else "Implement real authenticated Native MCP tool and OS side effect; "
                    "pass positive, refusal, Stop, crash, retry and per-API tests"
                ),
                "independent_oracle": "Signed independent Android fixture/OS oracle and exact installed APK proof",
                "profile": role,
            }
        )
    return {
        "snapshot_origin": "V3 full-lifecycle acceptance spec plus current app Tool registration source",
        "not_a_feature_completion_certificate": True,
        "tools_list_needs_runtime_verification": True,
        "live_native_tool_names": tools,
        "work_package_index": packages,
        "capabilities": status,
        "required_gaps": gaps,
        "verified_v3_cases": 0,
        "verified_legacy_cases": 0,
        "production_features_done": 0,
        "emulator_features_done": 0,
        "product": "PRODUCT_INCOMPLETE",
        "original_work_package_json": "UNAVAILABLE_IN_LIBRARY_ZIP_ONLY_NOT_CLAIMED_READ",
        "original_v3_delivery_summary": "UNAVAILABLE_IN_LIBRARY_ZIP_ONLY_NOT_CLAIMED_READ",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--legacy-ledger", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--gateway", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    data = reconcile(
        json.loads(args.registry.read_text()),
        json.loads(args.legacy_ledger.read_text()),
        args.plan.read_text(),
        args.gateway.read_text(),
    )
    args.out.parent.mkdir(exist_ok=True, parents=True)
    args.out.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "capabilities": len(data["capabilities"]),
                "open_gaps": len(data["required_gaps"]),
                "packages": len(data["work_package_index"]),
                "real_feature_done": data["production_features_done"],
                "public_native_tool_sources": data["live_native_tool_names"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
