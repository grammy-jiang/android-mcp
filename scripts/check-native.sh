#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

if [[ -z "$(printenv JAVA_HOME || true)" ]] || [[ ! -x "$(printenv JAVA_HOME || true)/bin/java" ]]; then
  echo "ERROR: Set JAVA_HOME to a supported JDK 17 installation." >&2
  exit 2
fi

echo "== Native Gradle version, dependency lock and checksum policy =="
uv run --project host --locked --group dev --python 3.13 python scripts/audit_native_gradle_policy.py --strict

echo "== JVM-only Native build; no Android SDK and no device mutation =="
"$JAVA_HOME/bin/java" -version
java_major="$("$JAVA_HOME/bin/java" -version 2>&1 | head -n 1 | sed -E 's/^.*version "([0-9]+).*/\1/')"
if [[ "$java_major" != 17 ]]; then
  echo "ERROR: Native JVM protocol tests require JDK 17, got: $java_major" >&2
  exit 2
fi
./android/gradlew --project-dir android --no-daemon --console=plain \
  :native-protocol:test :native-lifecycle:test :native-mcp-jvm:test :native-mcp-jvm:installDist

echo "== Live local Python <-> Kotlin MCP and shared schema acceptance =="
uv run --project host --locked --python 3.13 python scripts/smoke-native-jvm.py
echo "== N0.b Kotlin/JVM hostile localhost Host/Origin/HTTP denial smoke =="
uv run --project host --locked --python 3.13 python scripts/smoke-native-local-guard.py
echo "== Emulator-only guard and UI selection tests (no Android SDK) =="
uv run --project host --locked --group dev --python 3.13 pytest -q android/tests

echo "== V3 source requirements/admission and exclusive AVD negative-path tests =="
python3 -m unittest discover -s tests -p 'test_native_v3*.py' -v
python3 scripts/native_v3_gate.py \
  --registry docs/native-v3/Android_Native_MCP_E2E_Acceptance_Registry_V3_2026-10-14.json \
  --traceability docs/native-v3/Android_Native_MCP_V3_Legacy_228_Traceability_Template_2026-10-14.csv \
  --plan docs/native-v3/Android_Native_MCP_E2E_Implementation_Plan_V3_2026-10-14.md

echo "JVM Native protocol tests, cross-language MCP, V3 admission, and safety gates passed."
