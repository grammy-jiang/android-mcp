#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root/host"

uv run --locked --group dev ruff check src tests
uv run --locked --group dev ruff format --check src tests
uv run --locked --group dev pytest -q
uv run --locked --group dev android-mcp-host doctor >/dev/null
echo "Host checks passed."
