"""Test the quality gate itself: missing, weak and oversized evidence must fail."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_quality_policy.py"


def _fixture(tmp_path, score=100, *, include_module=True, max_size=500):
    src = tmp_path / "host/src/android_mcp_host"
    src.mkdir(parents=True)
    (src / "adb.py").write_text("VALUE = 1\n")
    policy = {
        "python": {
            "max_physical_lines_per_module": max_size,
            "coverage_default_minimum": 90.0,
            "coverage_critical_minimum": 95.0,
            "coverage_critical_modules": ["src/android_mcp_host/adb.py"],
            "coverage_exempt_entrypoints": [],
        }
    }
    (tmp_path / "quality-policy.json").write_text(json.dumps(policy))
    raw = {
        "meta": {"branch_coverage": True},
        "files": (
            {
                "src/android_mcp_host/adb.py": {
                    "summary": {
                        "percent_covered": score,
                        "num_statements": 1_000_000,
                        "covered_lines": round(score * 10_000),
                        "num_branches": 1_000_000,
                        "covered_branches": round(score * 10_000),
                    }
                }
            }
            if include_module
            else {"src/android_mcp_host/stale.py": {"summary": {"percent_covered": 100}}}
        ),
    }
    (tmp_path / "host/.coverage.json").write_text(json.dumps(raw))
    return src


def _check(tmp_path):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def test_valid_report_passes(tmp_path):
    _fixture(tmp_path)
    result = _check(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("score", [0, 89.9, 94.999])
def test_critical_coverage_floor_is_enforced(tmp_path, score):
    _fixture(tmp_path, score)
    result = _check(tmp_path)
    assert result.returncode == 1
    assert "below 95.00%" in result.stdout


def test_missing_file_cannot_pass_with_high_total_coverage(tmp_path):
    _fixture(tmp_path, include_module=False)
    result = _check(tmp_path)
    assert result.returncode == 1
    assert "Missing coverage report" in result.stdout


def test_new_module_also_requires_coverage(tmp_path):
    src = _fixture(tmp_path)
    (src / "new_feature.py").write_text("VALUE = 2\n")
    result = _check(tmp_path)
    assert result.returncode == 1
    assert "new_feature.py" in result.stdout


def test_size_gate_fails_oversized_source(tmp_path):
    src = _fixture(tmp_path, max_size=5)
    (src / "adb.py").write_text("x = 0\n" * 6)
    result = _check(tmp_path)
    assert result.returncode == 1
    assert "exceed 5" in result.stdout


def test_branch_coverage_report_is_required(tmp_path):
    _fixture(tmp_path)
    report = tmp_path / "host/.coverage.json"
    parsed = json.loads(report.read_text())
    parsed["meta"]["branch_coverage"] = False
    report.write_text(json.dumps(parsed))
    result = _check(tmp_path)
    assert result.returncode == 1
    assert "branch_coverage" in result.stdout


def test_stale_critical_policy_entry_fails(tmp_path):
    _fixture(tmp_path)
    policy_file = tmp_path / "quality-policy.json"
    policy = json.loads(policy_file.read_text())
    policy["python"]["coverage_critical_modules"].append("src/android_mcp_host/old.py")
    policy_file.write_text(json.dumps(policy))
    result = _check(tmp_path)
    assert result.returncode == 1
    assert "old.py" in result.stdout


def test_nested_security_module_requires_coverage(tmp_path):
    src = _fixture(tmp_path)
    security = src / "security"
    security.mkdir()
    (security / "approvals.py").write_text("VALUE = 1\n")
    result = _check(tmp_path)
    assert result.returncode == 1
    assert "security/approvals.py" in result.stdout


def test_high_combined_percentage_cannot_hide_low_branch_coverage(tmp_path):
    _fixture(tmp_path)
    report = tmp_path / "host/.coverage.json"
    data = json.loads(report.read_text())
    summary = data["files"]["src/android_mcp_host/adb.py"]["summary"]
    summary.update(
        percent_covered=99.0,
        num_statements=1000,
        covered_lines=1000,
        num_branches=24,
        covered_branches=22,
    )
    report.write_text(json.dumps(data))
    result = _check(tmp_path)
    assert result.returncode == 1
    assert "branch coverage" in result.stdout
    assert "91.67%" in result.stdout


def test_statement_coverage_is_independently_enforced(tmp_path):
    _fixture(tmp_path)
    report = tmp_path / "host/.coverage.json"
    data = json.loads(report.read_text())
    summary = data["files"]["src/android_mcp_host/adb.py"]["summary"]
    summary.update(num_statements=100, covered_lines=94, num_branches=10, covered_branches=10)
    report.write_text(json.dumps(data))
    result = _check(tmp_path)
    assert result.returncode == 1
    assert "statement coverage 94.00%" in result.stdout


@pytest.mark.parametrize(
    "patch",
    [
        {"num_branches": "not-a-number"},
        {"covered_branches": 11, "num_branches": 10},
        {"num_statements": 0, "covered_lines": 0},
        {"num_branches": -1},
        {"num_statements": True},
        {"covered_lines": -1},
    ],
)
def test_malformed_coverage_counters_fail_closed(tmp_path, patch):
    _fixture(tmp_path)
    report = tmp_path / "host/.coverage.json"
    data = json.loads(report.read_text())
    data["files"]["src/android_mcp_host/adb.py"]["summary"].update(patch)
    report.write_text(json.dumps(data))
    result = _check(tmp_path)
    assert result.returncode == 1
    assert "Invalid coverage evidence" in result.stdout


def test_missing_branch_counter_fails_closed(tmp_path):
    _fixture(tmp_path)
    report = tmp_path / "host/.coverage.json"
    data = json.loads(report.read_text())
    del data["files"]["src/android_mcp_host/adb.py"]["summary"]["covered_branches"]
    report.write_text(json.dumps(data))
    result = _check(tmp_path)
    assert result.returncode == 1
    assert "Invalid coverage evidence" in result.stdout


def test_branchless_module_requires_statement_coverage(tmp_path):
    _fixture(tmp_path)
    report = tmp_path / "host/.coverage.json"
    data = json.loads(report.read_text())
    summary = data["files"]["src/android_mcp_host/adb.py"]["summary"]
    summary.update(num_branches=0, covered_branches=0)
    report.write_text(json.dumps(data))
    assert _check(tmp_path).returncode == 0


def test_docstring_only_package_marker_needs_no_statement_coverage(tmp_path):
    src = _fixture(tmp_path)
    marker = src / "__init__.py"
    marker.write_text('"""Package documentation."""\n')
    report = tmp_path / "host/.coverage.json"
    data = json.loads(report.read_text())
    data["files"]["src/android_mcp_host/__init__.py"] = {
        "summary": {
            "num_statements": 0,
            "covered_lines": 0,
            "num_branches": 0,
            "covered_branches": 0,
        }
    }
    report.write_text(json.dumps(data))
    assert _check(tmp_path).returncode == 0
