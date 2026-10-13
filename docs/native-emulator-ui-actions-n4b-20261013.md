# N4.b — isolated disposable-emulator UIAutomator/ADB action acceptance

**Status:** implemented opt-in emulator-only safety and real UI tests. This is
NOT a production Native UI gesture capability. The current Native MCP catalog
remains exactly device_status, and the Android APK still does not declare or
activate AccessibilityService or any gesture APIs.

## Exact UI input safety boundary

scripts/smoke-native-ui-action-emulator.py requires an explicit emulator-XXXX
ADB serial, a supported API (30/33/34/36), and a known ABI (arm64-v8a or
x86_64). Before ANY APK install, Activity start, key input, force-stop or
owned dump cleanup, it checks online state, ro.kernel.qemu=1, exact API/ABI
and completed boot via serial-scoped ADB. No physical serial, implicit ADB
device, IP/USB target or fallback is accepted.

The outer verify_native_ui_action_matrix.py preflights all four distinct API
targets and their ABIs before allowing a single mutation. Each child then
re-verifies the exact emulator before every input. The only installed APK
is the locally built Native debug APK for package org.androidmcp.nativeapp.
An arbitrary or symlinked APK path is rejected before installation: the
runner accepts only this exact worktree's expected debug APK output.

Before acting, the runner requires its own Activity to be top-resumed AND
the Android focused window to belong to the same app. UIAutomator must show
the expected title and one owned, enabled Start button within verified
display bounds. Invalid XML, XML DTD/entities, cross-app interactive overlays
covering the input region, ambiguous/foreign buttons and stale UI fingerprints
all cause denial. Each UI input refreshes the same-app hierarchy. In
particular, Stopped-to-Running must invalidate an earlier tap proof.

Permitted operations are limited to a tap on this app's Start button, a
180-ms swipe in its validated non-interactive left strip, and
KEYCODE_DPAD_DOWN while its Activity remains running. There is no arbitrary
gesture coordinate/key/shell API, other-package launch, Settings action,
HOME/BACK/POWER command, network or physical-device control. Real
UIAutomator and ADB verify the app's UI state before and after each input.
This is standalone emulator acceptance, not AndroidJUnitRunner instrumentation.

On input timeout, ADB disconnect or KeyboardInterrupt after possible
dispatch, the operation is uncertain and never automatically retried.
The runner fails closed instead of reporting success. A SIGKILL cannot
return a final status, but there is no retry daemon or automatic restart.
Cleanup affects only the verified emulator's own application (force-stop)
and fixed UI dump file /sdcard/android-mcp-n4b-ui.xml, not entire user
storage, another app, another AVD or a physical Android device.

## Test-first and executed emulator evidence

Six T-N4B-01..06 tests began with 15 expected behavior failures against an
intentionally incomplete guard. After implementation, all six pass.
Supplemental tests deny hostile overlays, malformed UI/XML, unexpected
commands, KeyboardInterrupt/retry risk and mixed-ABI matrix preflight.
The final N4.b SDK-free Python test file has 23 passing tests.

Real disposable ARM64 QEMU Android API30, 33, 34 and 36 AVDs were
independently preflighted. Each performed bounded app-owned tap, swipe and
navigation key input; an obsolete app UI proof was rejected before input,
and only the project's Activity was affected. The final four-API matrix
ran after focused-window, overlay, XML and stale-proof hardening and reports
physical_android_used=false.

The ordinary full scripts/check-native-local-ci.sh gate covers Python
safety, Kotlin/JVM, Python/Kotlin MCP wire, Host security and coverage,
signed APK, Android Lint and unchanged Manifest permissions. The separate
existing N2/N3 matrix provides foreground service, notification Stop and
permission-revocation regression evidence where executed. GitHub Hosted
Actions are unavailable due billing; no paid service is required.

## Deferred activation and remaining risks

No real Native MCP Accessibility Tool or UI executor is enabled.
Emulator-only input acceptance is NOT user authorization to operate
physical devices. A production input service requires purpose-reviewed
AccessibilityService declaration, genuine Android user activation,
independent security review and N6 authenticated caller/lease fencing.
An OS-killed test runner cannot retrospectively prove what Android did;
this remains explicitly uncertain rather than claimed as idempotent.
The PR records exact source, test evidence, emulator/API/ABI, APK hash,
merge commit, and authorization-dependent work.
