#!/usr/bin/env bash
# Reproducible, local Native/Host quality gates for environments where paid
# GitHub-hosted Actions cannot start. No remote changes or physical ADB use.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/check-native-local-ci.sh
  bash scripts/check-native-local-ci.sh --matrix --api30 emulator-5560 --api33 emulator-5558 --api34 emulator-5556 --api36 emulator-5554

Requirements:
  JDK 17 exported as JAVA_HOME, Android SDK 36 exported as ANDROID_HOME,
  uv with locked host dependencies, Git with standard pre-commit hooks.

  Default: repository hygiene, Host quality, Native Kotlin/JVM and Python
  safety tests, signed Android debug APK, Lint and dependency integrity.
  --matrix additionally requires explicit, QEMU-verified API30/33/34/36
  disposable emulators. Never targets or installs on physical Android.
USAGE
}

matrix=0
matrix_args=()
if [[ $# -eq 1 && "$1" == "--help" ]]; then
  usage
  exit 0
elif [[ $# -eq 0 ]]; then
  :
elif [[ $# -eq 9 && "$1" == "--matrix" ]]; then
  matrix=1
  shift
  matrix_args=("$@")
else
  usage >&2
  echo "ERROR: Invalid arguments; explicit four emulator mappings required." >&2
  exit 2
fi

# This runner never auto-accepts Google SDK license terms, installs packages,
# changes Git branches, pushes code, or invokes ADB for physical devices.
echo '=== All-repository non-mutating quality and security gates ==='
uv run --project host --locked --group dev pre-commit run --all-files
echo '=== Host current contract, coverage, safety gates ==='
bash scripts/check-host.sh
echo '=== Native Kotlin/JVM, MCP interoperability and safety tests ==='
bash scripts/check-native.sh
echo '=== Android APK signing, Lint and exact-permissions gate ==='
bash scripts/check-native-apk.sh
echo '=== Native static lockfiles and verification policy ==='
python3 scripts/audit_native_gradle_policy.py --strict

if [[ "$matrix" -eq 1 ]]; then
  echo '=== Explicit four-API emulator-only MCP end-to-end acceptance ==='
  uv run --project host --locked --group dev --python 3.13 python \
    scripts/verify_native_api_matrix.py "${matrix_args[@]}" \
    --apk android/app/build/outputs/apk/debug/app-debug.apk
fi

printf '{"result":"pass","local_quality":"passed","api_matrix_executed":%s,"physical_android_used":false}\n' \
  "$([[ "$matrix" -eq 1 ]] && echo true || echo false)"
