# N3: explicitly user-started Android Native MCP foreground service

**Status:** development-only Native candidate, 2026-10-12. No real OnePlus Pad
APK installation is authorized or claimed.

## Why this increment exists

N2 proved the user-visible, Activity-only Android MCP loopback service, which
intentionally closes when the Activity leaves the foreground. N3 adds a
**separate, explicit opt-in mode** that survives Home/background via Android's
user-visible foreground-service lifecycle, without breaking N2 or exposing
sensitive device capabilities.

## Android components and permissions

- The original `NativeMcpActivity` keeps the same `Start local read-only MCP`
  button and Activity `onStop` semantics, plus a separate button to open the
  N3 service screen. Both modes share the exact same TCP loopback endpoint
  and must **not** be used concurrently. The `native-lifecycle` module has
  a fail-closed process-local port-owner guard: N3 rejects any second owner,
  checks its own Ktor HTTP readiness with a fresh correlation marker, and
  only releases the owner after verifying the kernel socket port can be
  re-bound. Shutdown failures keep an UNKNOWN owner and block handoff.
  This is **not** Host/Native authentication or a distributed Lease.
- `BackgroundMcpActivity` is **not exported**. The user sees explicit
  **Start background local MCP** and **Stop background local MCP** controls.
- On Android 13+ the Activity requires the user to allow notification
  permission *before* starting the persistent mode. A refusal starts nothing.
- `NativeMcpForegroundService` is **not exported**. It runs only after the
  user starts it from a visible Activity and calls Android's
  `startForeground` with type `specialUse`, plus an ongoing notification
  and immutable explicit **Stop** action.
- `START_NOT_STICKY` and no boot receiver: no automatic relaunch after
  Android process death or reboot.
- The MCP endpoint is still `127.0.0.1:38765/mcp`; only
  `device_status` is available, returning an intentionally minimal
  JSON Schema v1 response. No device serial, installed apps, screenshots,
  contact/account data, Accessibility or Root APIs.

Exact reviewed APK permissions:

```text
android.permission.INTERNET
android.permission.FOREGROUND_SERVICE
android.permission.FOREGROUND_SERVICE_SPECIAL_USE
android.permission.POST_NOTIFICATIONS
```

`scripts/check-native-apk.sh` fails if the **actual signed APK** declares
anything else. The `specialUse` subtype describes user-initiated, read-only
developer MCP connectivity. Any future Google Play distribution must undergo
the appropriate Play Console foreground-service type review; this project
makes no distribution-approval claim.

## Test layers

**Without SDK/device:** `bash scripts/check-native.sh` exercises Kotlin
contract/JVM MCP checks, N2 simulator target guards, N3 permission/selector
guards and service-state proof tests. These are not equivalent to actual
Android runtime behavior.

**Licensed SDK APK check:** `bash scripts/check-native-apk.sh` builds API 36
debug APK and runs Android Lint, debug signing verification and exact manifest
permission allowlist. It requires JDK 17 and `ANDROID_HOME`.

**Disposable emulator only:**

```bash
# Precondition: emulator-5554 is a dedicated, already booted Android 16 AVD.
# Every script rejects a real ADB device even if the host can see one.
bash scripts/check-native-emulator.sh
```

The combined acceptance suite verifies both behaviors separately:

- N2: local Activity start, HTTP MCP, Home stops, user restart.
- N3: permission refusal does not start service; permission granted in
  **verified emulator only**, explicit UI Start, real Kotlin HTTP MCP;
  `dumpsys activity services` proves `isForeground=true` with notification;
  Home preserves MCP; UI Stop closes listener; explicit restart works;
  Android process force-stop does **not** auto-restart the service.
- Both scripts clean up Android app/port forwarding on the disposable AVD,
  print only short PASS/FAIL summaries, and do not read or write physical
  devices. The real OnePlus Pad 3 connected to sextant is excluded.
- A separate Mac ARM64 simulator contention check started the foreground
  service, pressed Back into the original Activity, then deliberately tapped
  the legacy local Start button. The UI reported **Could not start local MCP
  listener.**, while Android still reported the foreground service as running.
  The N3-03 owner also checks a process-local ephemeral HTTP readiness path
  under `/_native_internal/ready/` and requires a verified released TCP
  port before owner handoff. That path carries no authentication key or
  privileged data and is not an MCP tool. The failed secondary start preserves
  the original foreground service's MCP response.
  This manual contention negative is not yet part of GitHub emulator CI.

## Actual local validation and remaining release gates

On 2026-10-12 the MacBook Pro (Apple Silicon, Android 16 ARM64 emulator)
compiled the APK with all four allowed permissions, and N2/N3 real
HTTP/lifecycle acceptance passed. At this checkpoint there were 41 SDK-free
Python emulator/permission tests passing, including bounded raw HTTP
stop-detection regressions. The app was not installed on the
real OnePlus Pad 3.

Before merging this PR, require GitHub's separate Linux x86_64 Android 16
emulator E2E to pass at the exact PR head, along with macOS/Linux Native JVM
and repository security gates. Test failures must be fixed, never skipped.

## Boundaries not established by this increment

- **Authentication**: loopback allows other apps on the same Android device
  to connect; this is harmless only while serving minimal public-like,
  read-only status. No sensitive capability may be added before strong
  caller authentication, Origin protection, pairing and security review.
- **OnePlus/LineageOS**: emulator behavior is not proof of OEM/ROM stability.
- **System controls**: no Accessibility permission, Root, ADB shell,
  system settings change, background boot trigger, or app automation.
- **Service resilience**: Android may still stop a foreground service under
  memory pressure or user action. `START_NOT_STICKY` intentionally avoids
  automatic resurrection. Long-duration and process-death recovery policy
  must be tested independently.
- **Notification action**: the action is registered in the ongoing Android
  notification. Simulator E2E proves the app's UI Stop flow; a separate
  user-visible notification-action interaction test should be added before
  calling the notification UX fully accepted.

Official Android sources:

- [Foreground service declarations and permissions](https://developer.android.com/develop/background-work/services/fgs/declare)
- [Foreground service types, special use](https://developer.android.com/develop/background-work/services/fgs/service-types)
- [Foreground service launch restrictions](https://developer.android.com/develop/background-work/services/fgs/launch)
- [Android notification runtime permission](https://developer.android.com/develop/ui/compose/notifications/notification-permission)

See [N2 emulator acceptance](native-emulator-n2.md),
[Host/Native coordination](host-native-coordination.md) and
[security model](security.md).
