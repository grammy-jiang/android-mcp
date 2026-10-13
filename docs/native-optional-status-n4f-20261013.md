# N4.f — app-scoped optional sensor and notification readiness, default off

**Status:** safe internal Kotlin/JVM status normalizer and private Android
one-shot adapter. The public Native MCP Tool catalog is unchanged and
contains only device_status. There is no live location tracking, audio
capture, motion sensor stream, notification-content listener, contacts
reader, network scan or background surveillance.

## Scope and Android permissions

AndroidOptionalStatusReader reuses only the existing app-scoped N1.b
AndroidSystemSnapshotReader. Its fields are process-monotonic elapsed
time, coarse battery percentage and app-view display dimensions.
It separately checks the Android notification POST permission, but
never queries notification content. This is not authorization to
read, observe or display notification messages.

The reviewed APK declares INTERNET, FOREGROUND_SERVICE,
FOREGROUND_SERVICE_SPECIAL_USE and POST_NOTIFICATIONS only. It does
not declare ACCESS_NETWORK_STATE or permissions for location,
microphone, contacts or body sensors. Consequently the adapter
reports network_permission_granted=false and cannot query
ConnectivityManager. In the pure Kotlin model a fake grant may cause
network readiness to be available/unknown, but it cannot reveal
SSID, BSSID, MAC or IP address. A withheld/revoked/unknown grant
reports permission_denied. Location, microphone, contacts and
notification-content capabilities are always denied regardless of
an injected fake positive permission flag. Optional motion status
is disabled or unsupported; no SensorManager listener is registered.

Inputs are normalized only for Android API30–100, with API30/33/34/36
explicitly unit tested. Out-of-range battery, display dimensions,
negative monotonic timestamp, unsupported API, no foreground Activity
or stopped session produce null/denied/disabled/unsupported values;
they never become plausible measurements. Output is one bounded
versioned JSON snapshot with fixed field names and coarse status codes,
not a sensor observation stream or device-identity inventory.

## Synthetic sampling and lifecycle

NativeOptionalStatusSession contains only a synthetic one-worker-free
fixture for deterministic Kotlin tests. A fake sample must be
foreground, monotonic and at least one second after the prior sample;
the queue can hold at most 16 timestamps, never raw sensor values.
A high-rate or overflowing event is throttled. FGS_STOP,
ACTIVITY_DESTROYED, CLIENT_DISCONNECT and PROCESS_DEATH all clear the
fake queue and permanently stop the instance. The implementation
offers no timer, Android receiver, OS listener, background polling,
live sensor subscription or automatic restart.

## Test-first evidence and activation limitations

Six required T-N4F-01..06 Kotlin behavior tests were written first;
five failed on the intentionally permissive initial model and all
six passed following implementation. They cover unit/permission
metadata, sensitive capabilities denied even under fake grants,
background/polling refusal, API30/33/34/36 and invalid/revoked states,
one-second rate and 16-event limits with explicit Stop, and
identity/location/notification-content redaction.

Five Native Python source/Manifest/privacy checks confirm use of
app-only existing metrics, no permission-inaccessible ConnectivityManager
calls, no sensitive Android API, no background listener and unchanged
four-permission APK allowlist and live one-Tool MCP catalog.

The release gate consists of full macOS JDK17/SDK36 Kotlin/JVM,
Host/Native locked local quality/security and cross-language MCP,
signed APK, Android Lint and exact permission verification, then one
explicit four-API disposable QEMU regression matrix. That matrix
tests existing status and Activity/FGS/notification lifecycles, not
real optional sensor streams or private user data. No physical
Android device, runtime grant, user's location, contacts, microphone,
notification text or system setting is read or changed in this slice.

Enabling any future sensitive sensor or notification-content feature
requires its own reviewed Android runtime permission, real user
consent, independently audited purpose/retention, and N6 caller
identity/lease authorization. This N4.f result must remain private
and disabled for unpaired MCP callers.
