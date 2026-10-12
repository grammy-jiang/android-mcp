# N0.c Activity/FGS/port-owner lifecycle acceptance

**Scope:** Native-only state-machine hardening and disposable emulator
orientation regression. The Android app still exposes only minimal localhost
device_status, and the existing FGS remains explicitly user-started.
This is the N0.c incremental gate, not an independent security sign-off.

## Source change and test-first evidence

LocalPortOwner.beginStop previously accepted a duplicate stop while a first
stop was still in STOPPING. The new state check refuses this duplicate but
allows the original owner to retry shutdown after a failed closure or a
still-bound port leaves the owner UNKNOWN. Only a clean and verified stop
releases the singleton port to a competing Activity or FGS. No shared Host
lease or caller identity is inferred.

The six exact T-N0C-01..06 Kotlin tests cover Activity/FGS ownership
exclusivity, a competing mode failing closed, shutdown exception/port
uncertainty, duplicate Stop while STOPPING, API30/33/34/36 compatibility,
and Stop/Start race ordering. A seventh multithreaded contention test
ensures precisely one simultaneous stop begins. Initial RED evidence:
two targeted assertions failed before the production state guard change,
then the same tests passed without modifying old test cases.

## Real Android simulator acceptance

The opt-in emulator orientation script verifies QEMU, expected API and boot
status before any app installation or Settings write. It reads the Android
display's actual orientation, records the AVD's prior rotation preferences,
rotates the display by one quadrant, requires the N2 Activity listener to
close, and then verifies that an explicit user Start is needed to regain MCP.
Every path attempts to restore the prior rotation preferences and remove
the temporary ADB port forward. The safety fixtures deny non-emulators,
wrong API, unbooted targets, malformed orientation data and unsupported
rotation values. Failure-path tests verify restoration after an injected
synthetic failure.

For API 34/36, the existing N3 real foreground-service smoke now also
proves that its Android Service, notification and MCP endpoint remain
running after a real display rotation. Its established permission-denial,
Home, contention, notification Stop, UI Stop and process force-stop checks
remain unchanged and mandatory.

These are *disposable Android emulator* operations only. A physical Android
device, OnePlus tablet, user permissions or application data were not
modified; the APK's Manifest permission allowlist is unchanged.

## Deferred and excluded

A passing Kotlin state model is not enough to prove actual port closure,
SystemUI notification removal or Android foreground-service behavior; the
signed APK, Lint, exact Manifest and six N2/N3 E2E suites are required.
Kernel socket close/open probes remain a process-local safety boundary,
not a distributed Host/Native lease. Android OEM power-management and
physical-device process eviction are untested and remain deferred.
Draft Native PR #39 is a separate earlier N3 contention audit and is
neither rebased nor modified by this N0.c work.
