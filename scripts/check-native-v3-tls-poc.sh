#!/usr/bin/env bash
# E02.a: real Android Keystore ↔ Python OpenSSL mTLS on isolated disposable API36.
# This is a genuine Android app/Host transport POC, not production Native MCP auth.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

if [[ $# -ne 0 ]]; then
  echo 'Usage: bash scripts/check-native-v3-tls-poc.sh' >&2
  exit 2
fi

sdk="$(printenv ANDROID_HOME || printenv ANDROID_SDK_ROOT || true)"
if [[ -z "$sdk" || ! -f "$sdk/platforms/android-36/android.jar" ]]; then
  echo 'E02A_FAIL_CLOSED: Android SDK 36 required' >&2
  exit 2
fi
if [[ -z "$(printenv JAVA_HOME || true)" || ! -x "$JAVA_HOME/bin/java" ]]; then
  echo 'E02A_FAIL_CLOSED: JAVA_HOME JDK 17 required' >&2
  exit 2
fi
if [[ -n "$(git status --porcelain)" ]]; then
  echo 'E02A_FAIL_CLOSED: cannot attribute APK effects to uncommitted Git source' >&2
  exit 2
fi
if [[ -z "$(git rev-parse HEAD^{tree})" ]]; then
  echo 'E02A_FAIL_CLOSED: missing source tree' >&2
  exit 2
fi

echo '=== E02.a Android SDK test fixture + instrumentation (not production APK) ==='
./android/gradlew --project-dir android --no-daemon --console=plain \
  -PenableV3TlsPoc=true \
  :native-v3-tls-fixture:assembleDebug \
  :native-v3-tls-fixture:assembleDebugAndroidTest \
  :native-v3-tls-fixture:lintDebug
sdk_tools="$sdk/build-tools/36.0.0"
for name in aapt apksigner; do
  test -x "$sdk_tools/$name" || { echo 'E02A_FAIL_CLOSED: missing Build Tools' >&2; exit 2; }
done

fixture="$root/android/native-v3-tls-fixture/build/outputs/apk/debug/native-v3-tls-fixture-debug.apk"
instrumentation="$root/android/native-v3-tls-fixture/build/outputs/apk/androidTest/debug/native-v3-tls-fixture-debug-androidTest.apk"
for item in "$fixture" "$instrumentation"; do
  test -s "$item"
  "$sdk_tools/apksigner" verify "$item"
done
application_permissions="$("$sdk_tools/aapt" dump permissions "$fixture" |
  sed -n "s/^uses-permission: name='\([^']*\)'.*/\1/p" | LC_ALL=C sort)"
test "$application_permissions" = 'android.permission.INTERNET' || {
  echo 'E02A_FAIL_CLOSED: unexpected test fixture app privilege' >&2
  exit 2
}
instrumentation_permissions="$("$sdk_tools/aapt" dump permissions "$instrumentation" |
  sed -n "s/^uses-permission: name='\([^']*\)'.*/\1/p" | LC_ALL=C sort)"
test "$instrumentation_permissions" = 'android.permission.REORDER_TASKS' || {
  echo 'E02A_FAIL_CLOSED: AndroidJUnitRunner permissions drift' >&2
  exit 2
}
python="$root/host/.venv/bin/python"
test -x "$python" || {
  echo 'E02A_FAIL_CLOSED: locked Host Python environment required' >&2
  exit 2
}

echo '=== E02.a negative/idempotency/pinning/TLS evidence gate ==='
"$python" -m unittest discover -s tests -p 'test_native_v3_tls*.py' -v

echo '=== E02.a actual AndroidKeyStore TLS SERVER; 1 trusted, 2 denied ==='
"$python" -m scripts.run_native_v3_tls_poc --repo "$root" \
  --evidence-dir "$root/artifacts/v3-e02a"

echo '=== E02.a actual AndroidKeyStore TLS CLIENT; 1 trusted, 2 denied ==='
"$python" -m scripts.run_native_v3_tls_client_poc --repo "$root" \
  --evidence-dir "$root/artifacts/v3-e02a"

echo '=== E02.a verify test-only ADB transport teardown ==='
if adb -s emulator-5570 forward --list | grep -q 'emulator-5570'; then
  echo 'E02A_FAIL_CLOSED: orphan ADB forward' >&2
  exit 2
fi
if adb -s emulator-5570 reverse --list | grep -q 'tcp:39145'; then
  echo 'E02A_FAIL_CLOSED: orphan ADB reverse' >&2
  exit 2
fi

echo 'E02A_PASS_REAL_TEST_MTLS_POC_ONLY: production Native Tool auth NOT_DONE'
