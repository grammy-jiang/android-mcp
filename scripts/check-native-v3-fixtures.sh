#!/usr/bin/env bash
# V3 E01.b: signed, deterministic fixture APKs; not Native product acceptance.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
sdk="$(printenv ANDROID_HOME || printenv ANDROID_SDK_ROOT || true)"
if [[ -z "$sdk" || ! -f "$sdk/platforms/android-36/android.jar" ]]; then
  echo "E01B_FAIL: Android SDK platform 36 required" >&2
  exit 2
fi
if [[ -z "$(printenv JAVA_HOME || true)" || ! -x "$JAVA_HOME/bin/java" ]]; then
  echo "E01B_FAIL: JAVA_HOME must point to existing JDK 17" >&2
  exit 2
fi
aapt="$sdk/build-tools/36.0.0/aapt"
apksigner="$sdk/build-tools/36.0.0/apksigner"
for tool in "$aapt" "$apksigner"; do
  [[ -x "$tool" ]] || { echo "E01B_FAIL: Missing Android Build Tools 36.0.0" >&2; exit 2; }
done
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != '--matrix' ) ]]; then
  echo "Usage: bash scripts/check-native-v3-fixtures.sh [--matrix]" >&2
  exit 2
fi

./android/gradlew --project-dir android --no-daemon --console=plain \
  -PenableV3Fixtures=true \
  :native-v3-fixture:assembleDebug \
  :native-v3-fixture:assembleDebugAndroidTest \
  :native-v3-fixture:lintDebug \
  :native-v3-install-fixture:assembleDebug \
  :native-v3-install-fixture:lintDebug

fixture="$root/android/native-v3-fixture/build/outputs/apk/debug/native-v3-fixture-debug.apk"
instrumentation="$root/android/native-v3-fixture/build/outputs/apk/androidTest/debug/native-v3-fixture-debug-androidTest.apk"
install_target="$root/android/native-v3-install-fixture/build/outputs/apk/debug/native-v3-install-fixture-debug.apk"

for pair in "org.androidmcp.v3fixture:$fixture" \
  "org.androidmcp.v3fixture.test:$instrumentation" \
  "org.androidmcp.v3installfixture:$install_target"; do
  IFS=: read -r pkg apk <<< "$pair"
  test -s "$apk" || { echo "E01B_FAIL: missing signed APK $pkg" >&2; exit 2; }
  "$apksigner" verify --print-certs "$apk" >/dev/null
  badging="$("$aapt" dump badging "$apk")"
  printf '%s\n' "$badging" | grep -q "package: name='$pkg'"
  permissions="$("$aapt" dump permissions "$apk" | sed -n "s/^uses-permission: name='\([^']*\)'.*/\1/p" | LC_ALL=C sort)"
  if [[ "$pkg" == 'org.androidmcp.v3fixture.test' ]]; then
    # AndroidX instrumentation's REORDER_TASKS is framework test infrastructure,
    # not a permission acquired by either independently installable fixture app.
    [[ "$permissions" == 'android.permission.REORDER_TASKS' ]] || {
      echo "E01B_FAIL: instrumentation permissions drift: $permissions" >&2; exit 2;
    }
  else
    printf '%s\n' "$badging" | grep -q "package: name='$pkg' versionCode='1'"
    [[ -z "$permissions" ]] || {
      echo "E01B_FAIL: synthetic fixture $pkg unexpectedly requests: $permissions" >&2; exit 2;
    }
  fi
  echo "E01B: verified signed minimal-permission package $pkg"
done
python3 scripts/audit_native_gradle_policy.py --strict
python3 -m unittest discover -s tests -p 'test_native_v3_fixture*.py' -q

if [[ $# -eq 1 ]]; then
  for api in 30 33 34 36; do
    python3 -m scripts.native_v3_fixture_matrix \
      --repo "$root" --api "$api" --evidence-dir "$root/artifacts/v3-e01"
  done
fi
echo "E01B_PASS: signed, linted, pinned fixture gate complete"
