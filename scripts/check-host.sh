#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

uv lock --check --offline --project host
uv run --project host --locked --group dev ruff check host/src host/tests scripts
uv run --project host --locked --group dev ruff format --check host/src host/tests scripts
uv run --project host --locked --group dev mypy --config-file host/pyproject.toml host/src
uv run --project host --locked --group dev bandit -q -r host/src -ll

cd "$repo_root/host"
uv run --locked --group dev pytest -q --cov=android_mcp_host --cov-branch \
  --cov-report=term-missing --cov-report=json:.coverage.json

cd "$repo_root"
uv run --project host --locked --group dev python scripts/check_quality_policy.py
uv run --project host --locked --group dev android-mcp-host doctor >/dev/null
echo "All Host quality gates passed."
