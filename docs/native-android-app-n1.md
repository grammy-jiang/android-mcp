# N1: Android app and foreground-only Native MCP loopback proof

**Scope:** buildable Android APK and one local read-only MCP tool, not a
production background or authenticated service.

## Runtime contract

- `android/app` uses AGP 9.4.0, Gradle 9.6.0 and JDK 17.
- Only include it with `-PenableAndroidApp=true`; the default
  `scripts/check-native.sh` stays SDK-free and must keep working.
- User opens the app and explicitly presses **Start local read-only MCP**;
  official Kotlin SDK / Ktor CIO serves on `127.0.0.1:38765/mcp`.
  Exactly one tool: `device_status`, with no device IDs or user data.
- The activity stops the listener in `onStop`. No unattended background
  service, boot receiver, AccessibilityService, Root, arbitrary shell,
  local credentials, authenticated Host pairing or public TCP listener.
- Android manifest declares only INTERNET. Extra permissions are denied by
  `scripts/check-native-apk.sh` at build verification.

## Reproducible APK build

A local or CI Android SDK must already have accepted the relevant Google
SDK licenses. Do not automatically approve license terms.

```bash
export JAVA_HOME=/path/to/jdk17
export ANDROID_HOME=/path/to/authorized/android/sdk
bash scripts/check-native-apk.sh
```

Requires `platforms;android-36` and `build-tools;36.0.0`. The build check
runs Gradle APK assembly and Android Lint, verifies debug signature and
checks APK permissions (only INTERNET). The output is
`android/app/build/outputs/apk/debug/app-debug.apk`. A successful JVM
smoke alone is not proof of this APK build.

## Explicit remaining gates

1. Real Android debug APK installation, port conflict and HTTP wire test
   must be separately authorized on the OnePlus Pad 3. No device mutation
   is authorized by committing this feature.
2. Android background/stop, process death, error handling, orientation and
   Android 16 UI/lifecycle should be tested with instrumentation.
3. Authenticated remote service and user-granted device capabilities must
   be designed before exposing meaningful diagnostics outside loopback.
4. Host/Native pairing and jointly fenced mutation leases are absent.
   Do not infer any mutation authority from `userdebug` or ADB authorization.

Official compatibility:
[AGP 9.4 compatibility](https://developer.android.com/build/releases/agp-9-4-0-release-notes)
[AGP 9 built-in Kotlin](https://developer.android.com/build/migrate-to-built-in-kotlin)
