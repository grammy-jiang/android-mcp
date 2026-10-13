# Native N7.d — user-visible service recovery without hidden persistence

The production Native app already has a strict `NativeServiceLifecycle`,
`LocalPortOwner` and explicit user Start/Stop in `NativeMcpForegroundService`.
N7.d adds a separate **synthetic** Kotlin recovery/epoch model to challenge
Stop/Start proof handling, port/notification release, process death, reboot,
owner collisions, Android foreground rules and simulated sensitive-session
invalidations. It does not add an alternate recovery service or a real
capture/lease caller credential.

The real Android service continues to use `START_NOT_STICKY`, a single serial
socket worker, explicit notification Stop, verified listener shutdown, and
fail-closed failed STOP state. API30/33 do not start the N3 FGS; API34/36
require OS readiness and POST_NOTIFICATIONS. Actual QEMU testing exercises
foreground notification refusal, user Stop and explicit re-Start on API34/36,
and legacy API30/33 denial. Source/Manifest checks prove there is no boot
receiver, wake lock, battery optimisation exemption, external port listener,
new Tool, device-admin privilege or auto-start after null Intent.

The **new model** only emits a fake readiness proof after explicit user Start,
never before confirmed port ownership. A failed port or notification release
retains UNKNOWN, where a different owner cannot steal the port. A fake service
restart issues fresh random capture/challenge/lease epochs; Stop, crash or
reboot immediately invalidates all previous epochs, and no real sensitive
resume is allowed. These fake epochs are not authenticated Host/Native records
and are not registered in a production MCP Tool; actual sensitive features
remain independently disabled.

## Acceptance evidence and honest limits

- T-N7D-01: Kotlin strict postverified Stop, explicit restart/new proof GREEN.
- T-N7D-02: process kill/reboot/implicit restart model denies resurrection;
  manifest and START_NOT_STICKY static guard GREEN. **A real emulator reboot
  was NOT performed**; this is not proven by destructive reboot testing.
- T-N7D-03: owner, unreleased port, failed notification Stop and UNKNOWN
  denial GREEN.
- T-N7D-04: Android QEMU API30/33/34/36 existing lifecycle and permission
  acceptance GREEN; model confirms API30/33 FGS denial.
- T-N7D-05: synthetic capture/challenge/lease epochs invalidated GREEN;
  there are no active real sensitive sessions to test.
- T-N7D-06: no boot/wake/battery bypass, additional Android permission,
  exported service or new public Tool GREEN.

All six Kotlin specified tests failed behaviorally RED on a permissive
scaffold, then GREEN after implementation; two extra Kotlin tests challenge
stale proof and concurrent duplicate explicit Start. Seven Python
source/Manifest/tool denial tests exercise real Android code paths. Full
Mac JDK17/SDK36 Host+Native gates, debug APK signing/Lint, Git hooks and
verified nonphysical four-API QEMU matrix are required before merge.
