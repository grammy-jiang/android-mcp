#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

# Use exactly the selected CI matrix interpreter, never silently switch to 3.13.
uv_run() {
  if [[ -n "$(printenv HOST_PYTHON || true)" ]]; then
    uv run --python "$(printenv HOST_PYTHON)" "$@"
  else
    uv run "$@"
  fi
}

# The offline lock check must use the matrix interpreter as well: otherwise
# host/.python-version (3.13) makes isolated 3.11/3.14 Linux runners fail
# before any tests are launched.
if [[ -n "$(printenv HOST_PYTHON || true)" ]]; then
  uv lock --check --offline --project host --python "$(printenv HOST_PYTHON)"
else
  uv lock --check --offline --project host
fi
uv_run --project host --locked --group dev ruff check host/src host/tests scripts
uv_run --project host --locked --group dev ruff format --check host/src host/tests scripts
uv_run --project host --locked --group dev mypy --config-file host/pyproject.toml host/src
uv_run --project host --locked --group dev bandit -q -r host/src -ll

cd "$repo_root/host"
uv_run --locked --group dev pytest -q --cov=android_mcp_host --cov-branch \
  --cov-report=term-missing --cov-report=json:.coverage.json

cd "$repo_root"
uv_run --project host --locked --group dev python scripts/check_quality_policy.py
uv_run --project host --locked --group dev android-mcp-host doctor >/dev/null
echo "All Host quality gates passed."
