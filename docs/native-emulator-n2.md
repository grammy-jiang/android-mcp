# Native N2: real Android runtime test without touching a physical tablet

This workstream adds a **disposable Android 16 emulator** acceptance layer for
the Kotlin Native MCP APK built in N1. The emulator is an isolated test device,
not a substitute for LineageOS/OnePlus real-device acceptance.

## Tested/expected scope

1. Install the debug APK in a clean Android emulator.
2. Open the Native activity and **explicitly tap** the visible start button.
3. Forward a host-local port through ADB to the app's Android-local
   `127.0.0.1:38765/mcp` listener.
4. Connect a real Python FastMCP client, verify exactly one `device_status`
   tool, validate response with the versioned JSON Schema and ensure all
   Accessibility/privileged capabilities remain false.
5. Press Home, verify the MCP endpoint becomes unavailable; return to the
   foreground, tap Start again and verify the endpoint recovers.
6. Stop the test app and remove the host-local ADB port forwarding.

The script prints only a concise PASS/FAIL outcome; it does not store the UI
tree, screenshots, system logs, Android identifiers or account data.

## Critical safety guard

`scripts/smoke-native-emulator.py` **requires `--serial emulator-XXXX`**,
checks that ADB reports that exact serial as online, then reads
`ro.kernel.qemu` and requires `1` **before any APK install, Activity action
or other device mutation**. Physical Android devices must always be rejected,
even if connected to the same ADB server. No implicit first-device targeting.

The parser and target guard have SDK-free negative tests in
`android/tests/test_emulator_smoke.py` and are run by
`scripts/check-native.sh`.

## GitHub emulator acceptance

The separate Android emulator CI workflow targets Linux x86_64 API 36.
It uses an action pinned by commit SHA, builds and lints the APK, starts an
ephemeral Android emulator, runs the guarded Python MCP acceptance script and
discards the emulator. No connected OnePlus tablet is required. Third-party
GitHub Actions should remain SHA-pinned.

A GitHub-hosted runner has a pre-provisioned Android SDK/license environment.
This **does not imply** any Google SDK license was accepted on the user's Mac.

## MacBook Pro local emulator (when SDK license is authorized)

The MacBook has Apple Silicon virtualization support, and as of 2026-10-12
128 GiB RAM and ample free storage. Its `~/Library/Android/sdk` currently
has no Android Platform, Emulator or system image installed and no
`licenses/` receipt. A local emulator requires the Google SDK software
license to be accepted by an authorized user first; do not pipe automatic
acceptance into `sdkmanager --licenses` without consent.

After that authorization, install `emulator`, `platform-tools`,
`platforms;android-36`, `build-tools;36.0.0` and
`system-images;android-36;default;arm64-v8a`; create a fresh named AVD with
`avdmanager`, launch the headless emulator with Apple's Hypervisor.framework,
and use exactly the same Python runtime acceptance script against its
`emulator-XXXX` serial.

Before invoking any local test, independently verify the macOS ADB server is
talking to the intended emulator and not the physical device. Do not use
sextant's real OnePlus ADB transport for this step.

## What this milestone does *not* prove

- Android service operation after the UI is backgrounded. N1 intentionally
  **stops** the HTTP listener in `Activity.onStop`; a user-visible
  foreground service and permission model require a separate design.
- Real OnePlus Pad 3 or LineageOS compatibility. Emulator success is not a
  hardware acceptance certificate.
- Caller authentication, network exposure, system privileges, Accessibility,
  Root, UI automation outside the emulator or Host/Native distributed leases.
- Android app data persistence or recovery after OS reboot.

See [N1 APK foundation](native-android-app-n1.md), [Native bootstrap](native-bootstrap.md),
[security](security.md), [parallel ownership](parallel-workstreams.md) and
[Host/Native lease design](host-native-coordination.md).
