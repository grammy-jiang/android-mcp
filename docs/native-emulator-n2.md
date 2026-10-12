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

On 2026-10-12 the user **explicitly authorized** accepting the Google SDK
license; all 8 license prompts were accepted on the MacBook. Android Emulator
37.2.12, Platform Tools 37.0.1, API 36, Build Tools 36.0.0 and the
`system-images;android-36;default;arm64-v8a` image were installed in
`~/Library/Android/sdk`. A dedicated Pixel Tablet AVD named
`android_mcp_native_api36` was then created and launched with
`-no-window` using Hypervisor.framework. No physical Android device was
connected to the MacBook during the validation.

The independent, real on-device MCP acceptance completed successfully using
an explicitly verified `emulator-5554` target and the Mac-built Debug APK:

```bash
export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
export ANDROID_HOME="$HOME/Library/Android/sdk"
bash scripts/check-native-apk.sh
uv run --project host --locked --group dev --python 3.13 python \
  scripts/smoke-native-emulator.py --serial emulator-5554 \
  --apk android/app/build/outputs/apk/debug/app-debug.apk
```

Result: `pass` for install, actual MCP HTTP `device_status`, activity Home/stop,
and user-initiated foreground restart. Kotlin Native executes on Android 16
ARM64 in a real local AVD, not only on the host JVM. The initial CI runtime
failure had a narrow UI test cause: Android exposes the Button label in
all capitals. The selector now matches the exact entire label using a
case-insensitive comparison, and has an explicit regression test. Further
Linux GitHub emulator validation remains a separate CI gate.

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
