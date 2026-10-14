"""N01–N20 catalog audit: 38 merged safe slices != 20 enabled Android Tools."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/check_native_capability_ledger.py"
CANONICAL = ROOT / "docs/native-capability-ledger.v1.json"

# pytest executing android/tests directly does not add the repository root to
# sys.path. Load this exact source file without changing Python global paths.
_HISTORY = ROOT / "scripts/native_v3_ci_git_history.py"
_SPEC = importlib.util.spec_from_file_location("native_v3_ci_git_history", _HISTORY)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
ensure_complete_ledger_history = _MODULE.ensure_complete_ledger_history


def run(
    path: Path = CANONICAL, strict: bool = False
) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, str(SCRIPT), "--ledger", str(path)]
    if strict:
        args.append("--strict-git")
    return subprocess.run(args, capture_output=True, text=True, check=False)


def mutated(tmp_path: Path, modify: object) -> Path:
    value = json.loads(CANONICAL.read_text())
    modify(value)
    output = tmp_path / "changed-ledger.json"
    output.write_text(json.dumps(value))
    return output


def test_20_families_38_merged_packages_228_specified_cases() -> None:
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {
        "result": "pass",
        "capabilities": 20,
        "merged_packages": 38,
        "specified_case_ids": 228,
        "sensitive_live_tools": 0,
    }


def test_actual_merge_receipts_are_git_ancestral() -> None:
    # Only the exact official GitHub Actions shallow checkout may recover
    # historical commits. The strict test below still verifies all 38 real
    # merge receipts and does not accept a fabricated ancestry marker.
    ensure_complete_ledger_history(ROOT)
    result = run(strict=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_missing_capability_fails_closed(tmp_path: Path) -> None:
    result = run(mutated(tmp_path, lambda data: data["capabilities"].pop()))
    assert result.returncode == 2


def test_sensitive_tool_false_advertising_fails_closed(tmp_path: Path) -> None:
    def edit(data: dict[str, object]) -> None:
        data["capabilities"][6]["public_native_tool"] = "tap"

    result = run(mutated(tmp_path, edit))
    assert result.returncode == 2


def test_fake_production_mutation_enablement_is_rejected(tmp_path: Path) -> None:
    def edit(data: dict[str, object]) -> None:
        data["capabilities"][-1]["feature_executable_in_production"] = True

    assert run(mutated(tmp_path, edit)).returncode == 2


def test_incorrect_merge_provenance_is_rejected(tmp_path: Path) -> None:
    def edit(data: dict[str, object]) -> None:
        data["capabilities"][0]["merge_receipts"][0]["merge_sha"] = "0" * 40

    assert run(mutated(tmp_path, edit), strict=True).returncode == 2


def test_inconsistent_duplicate_package_receipts_fails_closed(tmp_path: Path) -> None:
    def edit(data: dict[str, object]) -> None:
        # N0.c is repeated in N01 and N16; inconsistent citations are invalid.
        data["capabilities"][15]["merge_receipts"][0]["pr"] = 9999

    assert run(mutated(tmp_path, edit)).returncode == 2


def test_snapshot_has_no_second_live_native_tool() -> None:
    content = json.loads(CANONICAL.read_text())
    assert content["production_public_native_tools"] == ["device_status"]
    assert content["specified_test_case_ids_are_not_an_executed_test_count"] is True
    enabled = [
        c for c in content["capabilities"] if c["feature_executable_in_production"]
    ]
    assert {c["id"] for c in enabled} == {"N01", "N16"}
