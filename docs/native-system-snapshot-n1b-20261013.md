# N1.b — permission-aware one-shot Android system snapshot

**Status:** internal implementation, no new public Native MCP Tool or
background subscription. The current APK's exact four-permission Manifest
does not include ACCESS_NETWORK_STATE, and this work does not add it.

## Data scope and conservative availability

The internal AndroidSystemSnapshotReader probes BatteryManager capacity
(0–100 percent), app-filesystem StatFs available/total bytes, and
app-view display dimensions in pixels. All are one-shot allowed Android
APIs. The monotonic sampled_elapsed_ms comes from
SystemClock.elapsedRealtime, not a time-zone or account-clock signal.
No physical display identification or system-wide storage data is
claimed. The same-package filesDir supplies the filesystem path.

Network monitoring is disabled in this APK. Because ACCESS_NETWORK_STATE
is absent from the approved Manifest, this adapter reports
permission_denied unconditionally and does not call ConnectivityManager
or any network observation API. A future separately reviewed package can
implement a permission-aware connectivity adapter if authorization and the
APK's approved permission allowlist permit it. No SSID, BSSID, network
identifier, Wi-Fi scan, MAC/IP, location or nearby-device data is read.
This conservative change fixes a real Android Lint MissingPermission
failure without weakening Lint policy or adding a new permission.

NativeSystemSnapshots is an immutable, version-1 Kotlin normalization
boundary. It validates Android API30+, battery percent, nonnegative
monotonic time, paired app-filesystem storage byte quantities and
app-display dimensions. Negative/overflow values, missing platform
services and OEM exceptions become null/partial/unavailable, never
fabricated plausible measurements. Supported API30/33/34/36 snapshots
are typed; API before 30 returns unsupported with all optional
measurements null. No logcat raw probes, background observer,
permission prompt or userless grant is registered.

The Native status public Tool continues exposing only the existing
N0.a minimal status. The new internal model is not remotely callable.
Any expanded publication waits for N1.d/N6 caller authorization,
privacy review and a stable versioned wire contract.

## Test-first and truthful Android evidence

T-N1B-01..06 provide the six required Kotlin/JUnit behavioral cases:
typed battery/storage/display/network and elapsed-time units;
permission refusal/offline/missing services; oversize/negative
counter failures; API30/33/34/36 availability; new fresh snapshot
after a simulated Stop without stale values; and absent SSID/device
identity/location with N0.b sensitive Tool denial. Five assertions
failed on a deliberately unimplemented first normalization, then
all six passed with the correction. Additional Native Python
checks verify source API allowlists and no new Manifest permissions
or published MCP Tools.

JDK17 Kotlin/JVM, SDK36 signed APK, Android Lint, dependency integrity,
repository static/privacy/Host checks and disposable real QEMU API
matrix are separate release gates. The emulator matrix exercises
unmodified N2/N3 live Activity/FGS, Home, notification Stop and
permission revocation; it does **not** exercise this unexposed
AndroidSystemSnapshotReader at runtime. Therefore N1.b may merge as
a fully unit-tested **inert internal service**, not as an activated
remote battery/network monitor or physical-device acceptance.
Physical Android devices and privileged APIs remain untouched.
