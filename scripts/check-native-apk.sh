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

# Fail closed if the APK silently acquires additional Android permissions.
permissions="$("$aapt" dump permissions "$apk")"
echo "$permissions" | grep -Fq "android.permission.INTERNET"
extra="$(echo "$permissions" | grep 'uses-permission' | grep -v 'android.permission.INTERNET' || true)"
if [[ -n "$extra" ]]; then
    echo "ERROR: Unexpected manifest permissions:" >&2
    echo "$extra" >&2
    exit 2
fi
echo "Android APK built, signed for debug, linted; only INTERNET permission."
shasum -a 256 "$apk"
