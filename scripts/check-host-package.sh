#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

# Build both distribution formats and install the wheel in a truly clean venv.
uv build --project "$repo_root/host" --out-dir "$tmpdir/dist"
[[ "$(find "$tmpdir/dist" -type f -name '*.whl' | wc -l | tr -d ' ')" == 1 ]]
[[ "$(find "$tmpdir/dist" -type f -name '*.tar.gz' | wc -l | tr -d ' ')" == 1 ]]
wheel="$(find "$tmpdir/dist" -type f -name '*.whl' -print -quit)"
py="$(printenv HOST_PYTHON || echo 3.13)"
uv python install "$py"
uv venv --python "$py" "$tmpdir/clean-venv"
uv pip install --python "$tmpdir/clean-venv/bin/python" "$wheel"
"$tmpdir/clean-venv/bin/android-mcp-host" doctor > "$tmpdir/doctor.json"
"$tmpdir/clean-venv/bin/python" - "$tmpdir/doctor.json" <<'PY'
import json
import sys

from android_mcp_host.server import create_server

with open(sys.argv[1], encoding="utf-8") as report_file:
    report = json.load(report_file)
assert report["schema_version"] == 1
assert report["runtime"] == "host"
assert "devices" in report
assert callable(create_server)
PY
echo "Host sdist/wheel clean-install and CLI doctor passed."
