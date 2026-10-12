"""Protect the Host/Native CI separation and recurring security audit."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def _text(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_host_matrix_includes_every_declared_python_minor():
    workflow = _text("host-ci.yml")
    assert 'python: ["3.11", "3.12", "3.13", "3.14"]' in workflow
    assert "os: [ubuntu-latest, macos-latest]" in workflow


def test_host_ci_only_runs_on_main_pushes_and_relevant_prs():
    workflow = _text("host-ci.yml")
    assert "push:\n    branches: [main]" in workflow
    assert "pull_request:\n    paths:" in workflow
    for pattern in (
        '"host/**"',
        '"contracts/**"',
        '"scripts/check-host.sh"',
        '"quality-policy.json"',
    ):
        assert pattern in workflow
    assert '"android/**"' not in workflow
    assert "cancel-in-progress:" in workflow


def test_global_hygiene_checks_every_pr_including_native_and_docs():
    workflow = _text("repository-hygiene.yml")
    assert "pull_request:\n" in workflow
    assert "paths:" not in workflow
    assert "push:\n    branches: [main]" in workflow
    assert "pre-commit run --all-files" in workflow


def test_independent_security_audit_has_weekly_schedule():
    workflow = _text("host-security-audit.yml")
    assert "schedule:" in workflow
    assert "cron:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "uv audit --project host --locked" in workflow
    assert "contents: read" in workflow
