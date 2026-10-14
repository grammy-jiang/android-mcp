#!/usr/bin/env python3
"""GAP-N01-002: structural test assertion audit; never certifies Android E2E."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


class AssertionAuditError(ValueError):
    """Historical source test is missing, nonassertive, forged or untraceable."""


PYTEST_RAISES = {"raises", "warns"}
KOTLIN_ASSERT = re.compile(r"\b(assert[A-Z][A-Za-z0-9_]*|check|require|fail)\s*\(")
JAVA_ASSERT = frozenset(
    {
        "assertTrue",
        "assertFalse",
        "assertEquals",
        "assertNotEquals",
        "assertNull",
        "assertNotNull",
        "assertThrows",
        "assertArrayEquals",
        "assertSame",
        "assertNotSame",
        "assertAll",
        "assertIterableEquals",
        "assertTimeout",
        "assertTimeoutPreemptively",
        "assertInstanceOf",
        "fail",
        "check",
        "require",
    }
)


def _require(valid: bool, text: str) -> None:
    if not valid:
        raise AssertionAuditError(text)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _function_node(
    source: str, method_name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef:
    try:
        code = ast.parse(source)
    except SyntaxError as error:
        raise AssertionAuditError(
            "Python test source is not syntactically valid"
        ) from error
    methods = [
        node
        for node in code.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == method_name
    ]
    _require(len(methods) == 1, "Named Python test is missing or duplicate")
    return methods[0]


def _call_name(call: ast.expr) -> str | None:
    if isinstance(call, ast.Name):
        return call.id
    if isinstance(call, ast.Attribute):
        return call.attr
    return None


class _PythonAssertionWalk(ast.NodeVisitor):
    """Count actual executable AST nodes, not comments or nested definitions."""

    def __init__(self) -> None:
        self.forms: list[str] = []

    def visit_Assert(self, node: ast.Assert) -> None:
        _require(
            not (
                isinstance(node.test, ast.Constant) and node.test.value in (True, False)
            ),
            "An unconditional 'assert True/False' is not a substantive test",
        )
        self.forms.append("PY_ASSERT")
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            subject = item.context_expr
            if (
                isinstance(subject, ast.Call)
                and _call_name(subject.func) in PYTEST_RAISES
                and any(
                    isinstance(child, ast.Call) and _call_name(child.func) != "raises"
                    for statement in node.body
                    if not isinstance(
                        statement,
                        (
                            ast.Raise,
                            ast.FunctionDef,
                            ast.AsyncFunctionDef,
                            ast.ClassDef,
                        ),
                    )
                    for child in ast.walk(statement)
                )
            ):
                self.forms.append("PY_PYTEST_RAISES")
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        if name is not None and (
            name.startswith("assert") or name in {"check", "require"}
        ):
            if (
                name in {"assertTrue", "assertFalse"}
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value in (True, False)
            ):
                raise AssertionAuditError(
                    "Constant boolean assert cannot prove behavior"
                )
            self.forms.append("PY_METHOD_ASSERT")
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # A nested never-invoked function is not the outer test assertion.
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return


def audit_python_method(source: str, method_name: str) -> dict[str, Any]:
    node = _function_node(source, method_name)
    walker = _PythonAssertionWalk()
    for child in node.body:
        walker.visit(child)
    _require(walker.forms, f"{method_name}: no substantive executable AST assertion")
    body = ast.get_source_segment(source, node)
    _require(isinstance(body, str), "Python method body not recoverable")
    # Source-static classification is AST-based as well: test comments and
    # literal strings cannot promote a genuinely mocked test into source proof.
    nodes = [node] + [child for statement in node.body for child in ast.walk(statement)]
    read_source = any(
        isinstance(part, ast.Call)
        and _call_name(part.func) in {"read_text", "read_bytes", "parse"}
        and (
            not isinstance(part.func, ast.Attribute)
            or _call_name(part.func) != "parse"
            or (isinstance(part.func.value, ast.Name) and part.func.value.id == "ET")
        )
        for part in nodes
    )
    mock = any(
        token in body
        for token in (
            "monkeypatch",
            "Mock(",
            "mock_",
            "fake_",
            "Fake",
            "patch(",
            "stub_",
        )
    )
    basis = (
        "SOURCE_STATIC_ASSERTION"
        if read_source
        else "MOCKED_HARNESS_ASSERTION"
        if mock
        else "PYTHON_UNIT_ASSERTION"
    )
    return {
        "substantive_assertions": len(walker.forms),
        "assertion_forms": dict(sorted(Counter(walker.forms).items())),
        "basis": basis,
        "mock_or_stub_indicators": mock,
        "source_text_inspection": read_source,
        "body_sha256": _sha(body.encode("utf-8")),
    }


def _mask_noncode_kotlin(source: str) -> str:
    """Preserve positions and braces while hiding Kotlin comments and strings.

    Kotlin nested block comments, raw triple strings, ordinary escaped strings
    and chars cannot forge an assertion call or prematurely end a function.
    """
    out = list(source)
    pos = 0
    length = len(source)

    def blank(start: int, stop: int) -> None:
        for index in range(start, stop):
            if source[index] != "\n":
                out[index] = " "

    while pos < length:
        if source.startswith("//", pos):
            end = source.find("\n", pos)
            if end < 0:
                end = length
            blank(pos, end)
            pos = end
        elif source.startswith("/*", pos):
            start = pos
            pos += 2
            depth = 1
            while pos < length and depth:
                if source.startswith("/*", pos):
                    depth += 1
                    pos += 2
                elif source.startswith("*/", pos):
                    depth -= 1
                    pos += 2
                else:
                    pos += 1
            _require(depth == 0, "Unclosed Kotlin block comment")
            blank(start, pos)
        elif source.startswith('"""', pos):
            start = pos
            close = source.find('"""', pos + 3)
            _require(close >= 0, "Unclosed Kotlin multiline string")
            pos = close + 3
            blank(start, pos)
        elif source[pos] in ("'", '"'):
            start = pos
            kind = source[pos]
            pos += 1
            closed = False
            while pos < length:
                if source[pos] == "\\":
                    pos += 2
                elif source[pos] == kind:
                    pos += 1
                    closed = True
                    break
                else:
                    pos += 1
            _require(closed, "Unclosed Kotlin literal")
            blank(start, min(pos, length))
        else:
            pos += 1
    return "".join(out)


def _kotlin_method_body(source: str, method_name: str) -> tuple[str, str]:
    masked = _mask_noncode_kotlin(source)
    matches = list(
        re.finditer(rf"\bfun\s+{re.escape(method_name)}\s*\([^)]*\)\s*\{{", masked)
    )
    _require(len(matches) == 1, "Kotlin test function missing or duplicate")
    start = matches[0].start()
    opening = matches[0].end() - 1
    previous = masked[:start].rstrip()
    _require(
        previous.endswith(("@Test", "@Test()")),
        "Kotlin test method has no adjacent actual @Test annotation",
    )
    depth = 0
    end = -1
    for index in range(opening, len(masked)):
        ch = masked[index]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = index
                break
    _require(end > opening, "Kotlin JUnit method has no balanced code body")
    return source[opening + 1 : end], masked[opening + 1 : end]


def audit_kotlin_method(source: str, method_name: str) -> dict[str, Any]:
    raw, code = _kotlin_method_body(source, method_name)
    recognized: list[str] = []
    for occurrence in KOTLIN_ASSERT.finditer(code):
        name = occurrence.group(1)
        if name not in JAVA_ASSERT:
            continue
        arguments = code[occurrence.end() :]
        if name in ("assertTrue", "assertFalse") and re.match(
            r"\s*(?:true|false)\s*\)", arguments
        ):
            continue
        if name == "fail":
            continue
        if name in ("assertEquals", "assertNotEquals") and re.match(
            r"\s*([0-9]+)\s*,\s*\1\s*\)", arguments
        ):
            continue
        recognized.append(name)
    _require(recognized, f"{method_name}: no substantive JUnit/require/check call")
    return {
        "substantive_assertions": len(recognized),
        "assertion_forms": dict(sorted(Counter(recognized).items())),
        "basis": "KOTLIN_JVM_ASSERTION",
        "mock_or_stub_indicators": bool(
            re.search(
                r"\b(?:Synthetic|Fake|fake|mock|stub|PLAN_ONLY)\b",
                raw,
                flags=re.IGNORECASE,
            )
        ),
        "source_text_inspection": False,
        "body_sha256": _sha(raw.encode("utf-8")),
    }


def build_assertion_audit(repo: Path) -> dict[str, Any]:
    repo = repo.resolve(strict=True)
    source_map = json.loads(
        (repo / "docs/native-v3/v3-legacy-228-source-attribution.json").read_text()
    )
    # Reconstruct the source-of-truth legacy specification identities, rather
    # than trusting a prefilled 228-row JSON to name methods that do not exist.
    from scripts.native_v3_legacy_attribution import build_attribution

    reconstructed = build_attribution(repo)
    _require(
        source_map == reconstructed,
        "Historical source map differs from actual spec/method declarations",
    )
    _require(
        source_map["historical_specifications"] == 228,
        "Historical source map incomplete",
    )
    _require(len(source_map["cases"]) == 228, "Missing historical case rows")
    rows: list[dict[str, Any]] = []
    method_count = 0
    basis: Counter[str] = Counter()
    files: dict[str, str] = {}
    selectors: set[str] = set()
    for original in source_map["cases"]:
        methods: list[dict[str, Any]] = []
        for entry in original["executable_test_identifiers"]:
            name = entry["function"]
            path_string = entry["source"]
            _require(
                path_string.startswith("android/")
                and not Path(path_string).is_absolute()
                and ".." not in Path(path_string).parts,
                "Untrusted source test path",
            )
            path = (repo / path_string).resolve()
            _require(
                path.is_relative_to(repo / "android")
                and path.is_file()
                and not (repo / path_string).is_symlink(),
                "Source test path missing/escaped",
            )
            raw = path.read_bytes()
            _require(len(raw) < 200_000, "Historical source test file oversized")
            digest = _sha(raw)
            files[path_string] = digest
            contents = raw.decode("utf-8")
            layer = entry["test_layer"]
            if layer == "PYTHON_UNIT_HARNESS":
                _require(
                    path_string.startswith("android/tests/test_")
                    and path.suffix == ".py",
                    "Wrong Python test source",
                )
                findings = audit_python_method(contents, name)
            elif layer == "KOTLIN_JVM_JUNIT":
                _require(
                    "/src/test/" in path_string and path.name.endswith("Test.kt"),
                    "Wrong Kotlin unit-test source",
                )
                findings = audit_kotlin_method(contents, name)
            else:
                raise AssertionAuditError("Unreviewed historical evidence layer")
            identity = path_string + "::" + name
            _require(identity not in selectors, "Historical selector credited twice")
            selectors.add(identity)
            methods.append(
                {
                    "source": path_string,
                    "function": name,
                    "declared_line": entry["line"],
                    "test_layer": layer,
                    "source_sha256": digest,
                    **findings,
                }
            )
            basis[findings["basis"]] += 1
            method_count += 1
        _require(bool(methods), "Historical spec has no named assertive methods")
        rows.append(
            {
                "case_id": original["case_id"],
                "legacy_work_package": original["legacy_work_package"],
                "requirement_description": original["requirement_description"],
                "method_count": len(methods),
                "methods": methods,
                "requirement_semantic_review": "NOT_INDEPENDENTLY_REVIEWED",
                "product_e2e_status": "NOT_VERIFIED_REAL_ANDROID_E2E",
                "verified_android_effect": False,
            }
        )
    _require(
        len(rows) == 228 and len({x["case_id"] for x in rows}) == 228,
        "Historical cases not uniquely accounted",
    )
    _require(
        method_count == 257, "Historical method number differs from source baseline"
    )
    return {
        "schema_version": "native-v3-historical-assertion-audit.v1",
        "source_kind": "STATIC_AST_AND_KOTLIN_JUNIT_METHOD_ASSERTION_AUDIT_ONLY",
        "historical_cases": 228,
        "actual_test_methods": method_count,
        "cases_with_assertions": len(rows),
        "methods_without_substantive_assertion": 0,
        "source_files_sha256": dict(sorted(files.items())),
        "assertion_basis_by_method": dict(sorted(basis.items())),
        "independently_reviewed_requirement_semantics": 0,
        "real_android_mcp_capabilities_proven": 0,
        "product_status": "PRODUCT_INCOMPLETE",
        "cases": rows,
    }


def validate_report(report: dict[str, Any], repo: Path) -> None:
    expected = build_assertion_audit(repo)
    _require(
        report == expected,
        "Historical assertion artifact changed, stale, promoted or forged; regenerate after review",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("docs/native-v3/v3-legacy-228-assertion-audit.json"),
    )
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    repo = args.repo.resolve(strict=True)
    path = (repo / args.out).resolve()
    _require(
        path.is_relative_to(repo / "docs/native-v3"), "Report path escapes V3 docs"
    )
    report = build_assertion_audit(repo)
    if args.verify:
        _require(path.is_file(), "Assertion audit artifact missing")
        validate_report(json.loads(path.read_text()), repo)
    else:
        path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "historical_cases",
                    "actual_test_methods",
                    "cases_with_assertions",
                    "assertion_basis_by_method",
                    "real_android_mcp_capabilities_proven",
                    "product_status",
                )
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
