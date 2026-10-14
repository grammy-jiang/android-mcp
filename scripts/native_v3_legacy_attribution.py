#!/usr/bin/env python3
"""E00.b exact 228-case historical executable traceability and provenance.

Named historical source tests are different from full V3 end-to-end acceptance.
This tool discovers actual test functions; a future report can independently
join recorded JUnit/pytest XML executions without ever promoting them to real
Android effects or authenticated Native MCP functionality.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SPEC = re.compile(r"^- \*\*(T-N[0-8][A-F]-0[1-6]):\*\* (.+)$", re.MULTILINE)
KOTLIN = re.compile(r"(?m)^\s*fun\s+(t(N[0-8][A-F])([0-9]{2})[A-Za-z_0-9]*)\s*\(")
PYTHON = re.compile(r"^test_T_(N[0-8][A-F])_([0-9]{2})(?:_[A-Za-z_0-9]*)?$")
ID = re.compile(r"T-N[0-8][A-F]-0[1-6]\Z")


def python_case_methods(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Only parse real AST test functions; comments/strings never qualify."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        match = PYTHON.fullmatch(node.name)
        if match:
            case_id = f"T-{match.group(1)}-{match.group(2)}"
            output[case_id].append(
                {
                    "function": node.name,
                    "line": node.lineno,
                    "test_layer": "PYTHON_UNIT_HARNESS",
                    "test_runtime": "pytest",
                }
            )
    return dict(output)


def kotlin_case_methods(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Discover explicit Kotlin JUnit method names and mandatory @Test.

    This is a structural source audit, not an Android Runtime execution proof.
    """
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for match in KOTLIN.finditer(source):
        fn_name, pkg, suffix = match.groups()
        line = source.count("\n", 0, match.start()) + 1
        # A @Test annotation must be adjacent, with only blank lines or other
        # annotations between it and function; stop at ordinary statements.
        decorated = False
        for prior in reversed(lines[max(0, line - 5) : line - 1]):
            if prior.strip() == "@Test":
                decorated = True
                break
            if prior.strip() and not prior.lstrip().startswith("@"):
                break
        if not decorated:
            continue
        case_id = f"T-{pkg}-{suffix}"
        output[case_id].append(
            {
                "function": fn_name,
                "line": line,
                "test_layer": "KOTLIN_JVM_JUNIT",
                "test_runtime": "Gradle JUnit",
            }
        )
    return dict(output)


def validate_registry(csv_path: Path, specification: Path) -> list[dict[str, str]]:
    with csv_path.open(encoding="utf-8", newline="") as stream:
        registry = list(csv.DictReader(stream))
    if len(registry) != 228:
        raise ValueError("Expected 228 historical traceability entries")
    specs = SPEC.findall(specification.read_text(encoding="utf-8"))
    ids = [case_id for case_id, _description in specs]
    if len(ids) != 228 or len(set(ids)) != 228:
        raise ValueError("Original 228-case requirements missing/duplicated")
    _require_ids = [record["legacy_case_id"] for record in registry]
    if (
        len(set(_require_ids)) != 228
        or set(_require_ids) != set(ids)
        or not all(ID.fullmatch(entry) for entry in _require_ids)
    ):
        raise ValueError("Historical case registry differs from source specifications")
    grouped = Counter(record["legacy_work_package"] for record in registry)
    if len(grouped) != 38 or any(count != 6 for count in grouped.values()):
        raise ValueError("Historical 38 × 6 work packages mismatch")
    expected = dict(specs)
    for row in registry:
        case_id = row["legacy_case_id"]
        short = case_id.removeprefix("T-")
        pkg = f"{short[0:2]}.{short[2:3].lower()}"
        if row["legacy_work_package"] != pkg:
            raise ValueError(f"Historical package identity mismatch: {case_id}")
        if row["execution_state"] not in {"NOT_RUN_V3", "NOT_VERIFIED_V3"}:
            raise ValueError(f"Historical spec falsely credited: {case_id}")
        row["requirement_description"] = expected[case_id]
    return registry


def build_attribution(repo: Path) -> dict[str, Any]:
    """Map all 228 cases to *existing method selectors*, no synthetic promotion."""
    repo = repo.resolve()
    historical = (
        repo
        / "docs/native-v3/Android_Native_MCP_V3_Legacy_228_Traceability_Template_2026-10-14.csv"
    )
    specifications = repo / "docs/native-mcp-serial-test-cases-20261013.md"
    old_rows = validate_registry(historical, specifications)
    methods: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in sorted((repo / "android").rglob("*Test.kt")):
        if "/src/test/" not in str(path):
            continue
        if path.is_symlink():
            raise ValueError("Symlink test candidate forbidden")
        for case_id, candidates in kotlin_case_methods(path).items():
            for candidate in candidates:
                methods[case_id].append(
                    {**candidate, "source": str(path.relative_to(repo))}
                )
    for path in sorted((repo / "android/tests").glob("test_*.py")):
        if path.is_symlink():
            raise ValueError("Symlink test candidate forbidden")
        for case_id, candidates in python_case_methods(path).items():
            for candidate in candidates:
                methods[case_id].append(
                    {**candidate, "source": str(path.relative_to(repo))}
                )
    case_rows = []
    method_identifiers: set[str] = set()
    for original in old_rows:
        case_id = original["legacy_case_id"]
        candidates = sorted(
            methods.get(case_id, []),
            key=lambda item: (item["source"], item["line"], item["function"]),
        )
        for candidate in candidates:
            identifier = f"{candidate['source']}::{candidate['function']}"
            if identifier in method_identifiers:
                raise ValueError("Duplicate test selector: " + identifier)
            method_identifiers.add(identifier)
        case_rows.append(
            {
                "case_id": case_id,
                "legacy_work_package": original["legacy_work_package"],
                "related_capabilities": original["related_capabilities"].split(";"),
                "accountable_v3_work_packages": original[
                    "accountable_v3_work_packages"
                ].split(";"),
                "requirement_description": original["requirement_description"],
                "executable_test_identifiers": candidates,
                "discovery_provenance": "EXPLICIT_CASE_ID_NAMED_REAL_SOURCE_METHOD",
                "semantic_assertion_review": "NOT_INDEPENDENTLY_REVIEWED_PER_CASE",
                "existing_tests_can_run": bool(candidates),
                "execution_record": "NOT_EXECUTED_IN_THIS_AUDIT",
                "e2e_result": "NOT_VERIFIED_REAL_E2E",
                "per_android_api": {
                    str(api): "NOT_VERIFIED_REAL_E2E" for api in (30, 33, 34, 36)
                },
                "product_capability_done": False,
                "gap_id": f"GAP-{original['related_capabilities'].split(';')[0]}-001",
            }
        )
    missing = [
        item["case_id"] for item in case_rows if not item["executable_test_identifiers"]
    ]
    unexpected = sorted(set(methods) - {row["case_id"] for row in case_rows})
    if missing or unexpected:
        raise ValueError(
            f"Missing/extra executable historical methods: missing={missing}, extra={unexpected}"
        )
    return {
        "schema_version": "v3.legacy-attribution.v1",
        "source_kind": "SOURCE_METHOD_DISCOVERY_NOT_RUNTIME_E2E",
        "historical_specifications": len(old_rows),
        "unique_case_ids": len({row["case_id"] for row in case_rows}),
        "case_id_with_executable_test": len(case_rows) - len(missing),
        "test_methods_discovered": len(method_identifiers),
        "source_method_layers": dict(
            Counter(
                method["test_layer"]
                for case in case_rows
                for method in case["executable_test_identifiers"]
            )
        ),
        "verified_real_android_native_tool_calls": 0,
        "e2e_android_feature_verified": 0,
        "product": "PRODUCT_INCOMPLETE",
        "cases": case_rows,
    }


def _read_junit_reports(
    location: Path, *, expected_prefix: str
) -> dict[tuple[str, str], str]:
    """Index complete local XML results, fail on duplicate exact selectors.

    XML is untrusted tool output: only source-matching selectors can be
    attributed. No XML result supplies Android OS effects or approval.
    """
    import xml.etree.ElementTree as ET

    if not location.exists():
        return {}
    if location.is_dir() and location.name == "android":
        files = sorted(location.glob("*/build/test-results/test/TEST-*.xml"))
    else:
        files = sorted(location.glob("*.xml")) if location.is_dir() else [location]
    seen: dict[tuple[str, str], str] = {}
    for file in files:
        if file.is_symlink() or not file.is_file() or file.stat().st_size > 1024 * 1024:
            raise ValueError("Unsafe or oversized JUnit XML report")
        try:
            root = ET.parse(file).getroot()
        except ET.ParseError as error:
            raise ValueError("Malformed JUnit XML") from error
        if root.tag not in ("testsuites", "testsuite"):
            raise ValueError("Not JUnit XML")
        for entry in root.findall(".//testcase"):
            classname = entry.attrib.get("classname", "")
            testname = entry.attrib.get("name", "")
            if not classname.startswith(expected_prefix):
                continue
            if not testname or not classname:
                raise ValueError("JUnit testcase identity incomplete")
            selector = classname, testname
            if selector in seen:
                raise ValueError(
                    f"Duplicate JUnit test identity across reports: {selector}"
                )
            if entry.find("failure") is not None or entry.find("error") is not None:
                seen[selector] = "FAIL"
            elif entry.find("skipped") is not None:
                seen[selector] = "SKIPPED"
            else:
                seen[selector] = "PASS"
    return seen


def join_local_unit_results(
    attribution: dict[str, Any],
    kotlin_results: Path,
    python_results: Path,
    repo: Path,
) -> dict[str, Any]:
    """Match exact declarations to executed test XML; never infer V3 E2E.

    Kotlin build/test-results/test outputs and pytest --junitxml must
    originate from actual local runs. This parser does not authenticate them.
    """
    import copy

    result = copy.deepcopy(attribution)
    kotlin = _read_junit_reports(kotlin_results, expected_prefix="org.androidmcp.")
    python = _read_junit_reports(python_results, expected_prefix="android.tests.")
    by_layer = Counter()
    records = 0
    for item in result["cases"]:
        individual = []
        for method in item["executable_test_identifiers"]:
            name = method["function"]
            if method["test_layer"] == "KOTLIN_JVM_JUNIT":
                if "/src/test/" not in method["source"]:
                    raise ValueError("Kotlin selector is not a test source")
                # Kotlin path: android/native-protocol/src/test/kotlin/org/androidmcp/protocol/File.kt
                relative = method["source"].split("/src/test/kotlin/", 1)[1]
                classname = relative.removesuffix(".kt").replace("/", ".")
                aliases = [(classname, name + "()"), (classname, name)]
                statuses = [kotlin[alias] for alias in aliases if alias in kotlin]
                matching = statuses[0] if len(statuses) == 1 else None
            else:
                if not method["source"].startswith("android/tests/"):
                    raise ValueError("Python selector is not in Android test path")
                classname = method["source"].removesuffix(".py").replace("/", ".")
                statuses = [
                    value
                    for (clazz, testname), value in python.items()
                    if clazz == classname
                    and (testname == name or testname.startswith(name + "["))
                ]
                matching = (
                    "FAIL"
                    if "FAIL" in statuses
                    else (
                        "SKIPPED"
                        if "SKIPPED" in statuses
                        else ("PASS" if statuses else None)
                    )
                )
            if matching:
                records += 1
                by_layer[method["test_layer"]] += 1
            method["reported_test_status"] = matching or "NOT_IN_SUPPLIED_XML"
            individual.append(matching)
        if any(value == "FAIL" for value in individual):
            state = "FAIL_REPORTED_UNIT_TEST"
        elif any(value == "SKIPPED" for value in individual):
            state = "SKIPPED_REPORTED_UNIT_TEST"
        elif all(value == "PASS" for value in individual):
            layers = {m["test_layer"] for m in item["executable_test_identifiers"]}
            state = {
                frozenset({"KOTLIN_JVM_JUNIT"}): "PASS_REPORTED_KOTLIN_JVM",
                frozenset({"PYTHON_UNIT_HARNESS"}): "PASS_REPORTED_PYTHON_UNIT",
                frozenset(
                    {"KOTLIN_JVM_JUNIT", "PYTHON_UNIT_HARNESS"}
                ): "PASS_REPORTED_BOTH_UNIT_LAYERS",
            }[frozenset(layers)]
        elif any(value is not None for value in individual):
            state = "PARTIAL_REPORTED_UNIT_TEST"
        else:
            state = "NOT_EXECUTED_IN_THIS_AUDIT"
        item["execution_record"] = state
        # Never set e2e_result or per_android_api from Kotlin/Python XML.
        if item["e2e_result"] != "NOT_VERIFIED_REAL_E2E":
            raise ValueError("Unit execution cannot repair forged E2E status")
    result["xml_method_results_discovered"] = records
    result["xml_layers_reported"] = dict(by_layer)
    result["local_cases_with_all_unit_tests_reported_pass"] = sum(
        record["execution_record"].startswith("PASS_REPORTED")
        for record in result["cases"]
    )
    result["e2e_android_feature_verified"] = 0
    result["source_kind"] = "LOCAL_UNIT_RESULTS_JUNIT_XML_NOT_ANDROID_E2E"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--kotlin-test-results", type=Path)
    parser.add_argument("--python-junit", type=Path)
    parser.add_argument("--require-all-unit-results", action="store_true")
    args = parser.parse_args()
    result = build_attribution(args.repo)
    if args.kotlin_test_results and args.python_junit:
        result = join_local_unit_results(
            result, args.kotlin_test_results, args.python_junit, args.repo
        )
    if (
        args.require_all_unit_results
        and result.get("local_cases_with_all_unit_tests_reported_pass") != 228
    ):
        raise ValueError("All 228 historical unit-test selectors must report PASS")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "historical": result["historical_specifications"],
                "mapped": result["case_id_with_executable_test"],
                "methods": result["test_methods_discovered"],
                "layers": result["source_method_layers"],
                "real_e2e_verified": result["e2e_android_feature_verified"],
                "unit_cases_reported_pass": result.get(
                    "local_cases_with_all_unit_tests_reported_pass", 0
                ),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
