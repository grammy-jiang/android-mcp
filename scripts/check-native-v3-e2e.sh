#!/usr/bin/env bash
# E01.f: real AndroidJUnitRunner + installed Native APK Streamable HTTP MCP
# + independent fixture oracle on each exclusively owned API 30/33/34/36 AVD.
# This is a local, actual-device infrastructure test; NOT FUNCTION_DONE.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
sdk="$(printenv ANDROID_HOME || printenv ANDROID_SDK_ROOT || true)"
if [[ -z "$sdk" || ! -f "$sdk/platforms/android-36/android.jar" ]]; then
  echo "E01F_FAIL_CLOSED: Android SDK 36 must already be installed" >&2
  exit 2
fi
if [[ -z "$(printenv JAVA_HOME || true)" || ! -x "$JAVA_HOME/bin/java" ]]; then
  echo "E01F_FAIL_CLOSED: verified JAVA_HOME JDK 17 required" >&2
  exit 2
fi
if [[ $# -ne 0 ]]; then
  echo "Usage: bash scripts/check-native-v3-e2e.sh (no partial API flags)" >&2
  exit 2
fi

echo '=== E01.f: build real Native app + instrumentation with pinned deps ==='
./android/gradlew --project-dir android --no-daemon --console=plain \
  -PenableAndroidApp=true \
  :app:assembleDebug :app:assembleDebugAndroidTest :app:lintDebug

native_apk="$root/android/app/build/outputs/apk/debug/app-debug.apk"
native_test="$root/android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk"
signer="$sdk/build-tools/36.0.0/apksigner"
for path in "$native_apk" "$native_test"; do
  test -s "$path" || { echo "E01F_FAIL_CLOSED: missing Native signed APK" >&2; exit 2; }
  "$signer" verify "$path"
done

echo '=== E01.f: build and verify deterministic fixture APKs / UI consent denial boundary ==='
bash scripts/check-native-v3-fixtures.sh

echo '=== E01.f: adversarial matrix admission negative and recovery tests ==='
python3 -m unittest discover -s tests -p 'test_native_v3_e2e_gate.py' -v

echo '=== E01.f: FOUR real owned AVDs, Native APK MCP + Android OS/fixture oracles ==='
uv run --project host --locked --group dev --python 3.13 python \
  -m scripts.native_v3_e2e_gate \
  --repo "$root" \
  --python "$root/host/.venv/bin/python" \
  --evidence-dir "$root/artifacts/v3-e01"

echo 'E01F_PASS_INFRASTRUCTURE_ONLY: no Native feature closure claimed'
