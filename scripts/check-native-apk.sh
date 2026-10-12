#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

sdk_root="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
if [[ -z "$sdk_root" || ! -f "$sdk_root/platforms/android-36/android.jar" ]]; then
    echo "ERROR: SDK platform android-36 not installed in ANDROID_HOME/ANDROID_SDK_ROOT." >&2
    echo "Use an SDK with already accepted Google license terms; do not auto-accept them." >&2
    exit 2
fi
aapt="$sdk_root/build-tools/36.0.0/aapt"
apksigner="$sdk_root/build-tools/36.0.0/apksigner"
if [[ ! -x "$aapt" || ! -x "$apksigner" ]]; then
    echo "ERROR: SDK build-tools 36.0.0 not installed." >&2
    exit 2
fi
if [[ -z "${JAVA_HOME:-}" || ! -x "$JAVA_HOME/bin/java" ]]; then
    echo "ERROR: Set JAVA_HOME to JDK 17 before APK builds." >&2
    exit 2
fi

./android/gradlew --project-dir android --no-daemon --console=plain \
    -PenableAndroidApp=true :app:assembleDebug :app:lintDebug

apk="$repo_root/android/app/build/outputs/apk/debug/app-debug.apk"
test -s "$apk"
"$apksigner" verify "$apk"

# Compare the complete APK manifest permission set with the reviewed list.
raw_permissions="$("$aapt" dump permissions "$apk")"
actual_permissions="$(printf '%s\n' "$raw_permissions" | sed -n "s/^uses-permission: name='\([^']*\)'.*/\1/p" | LC_ALL=C sort)"
expected_permissions="$(printf '%s\n'     android.permission.INTERNET     android.permission.FOREGROUND_SERVICE     android.permission.FOREGROUND_SERVICE_SPECIAL_USE     android.permission.POST_NOTIFICATIONS | LC_ALL=C sort)"
if [[ "$actual_permissions" != "$expected_permissions" ]]; then
    echo "ERROR: APK permissions differ from the N3 reviewed allowlist." >&2
    echo "$raw_permissions" >&2
    exit 2
fi
echo "Android APK built, signed for debug, linted; exactly N3 reviewed permissions."
shasum -a 256 "$apk"
