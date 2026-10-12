# N1.c — own-app and foreground-service health semantics

N1.c implements an **internal-only**, versioned Kotlin own-app health
normalizer and a one-shot Android adapter. It does not register a public MCP
Tool, inspect other applications, read process lists/PIDs, expose a filesystem
path, query Logcat or manage Android permissions.

## Typed state and lifecycle

The pure normalizer distinguishes Activity and explicitly user-started
foreground-service modes. Its health input is supplied by the Activity/FGS
owner and contains its verified process-local port phase, notification
promotion in FGS mode, lifecycle state and monotonic start/observation times.
A RUNNING response requires current listener ownership evidence; FGS
additionally requires a current foreground notification. Missing proof,
an injected port bind/start error or unconfirmed shutdown cannot report
healthy. Uptime is calculated only from bounded, nonnegative monotonic
timestamps; no wallclock, device ID or persistent process epoch is used.

Typed states are stopped, starting, running, stopping, failed_closed and
unsupported. Typed stop reasons distinguish user, notification, process death,
failed start and unknown, **when the owner provides reliable evidence**.
A pure simulated process-death input reports STOPPED with no inherited uptime;
a killed Android process cannot run this reporter to prove its own death.
Android 11/13 supports only foreground Activity mode; the N3 specialUse FGS
is supported on API34+. Existing FGS START_NOT_STICKY and absence of a boot
receiver remain unchanged. Neither Android reboot nor notification Stop
automatically restarts the service.

The encoded result contains only a fixed small set of non-identifying
fields: schema version, mode, phase, bounded uptime, endpoint readiness,
stop reason and fixed error code. No exception messages, private paths,
process IDs, credentials or device identifiers enter public status v1.
This model is **not** caller authentication, cross-process lease fencing
or external diagnostic availability.

## Evidence and activation boundary

Six specified T-N1C-01..06 Kotlin/JUnit tests exercise Activity/FGS readiness,
user/notification/process-death distinctions, bind/timeout/uncertain-close
failures, restart/API denial, privacy, and existing Native status/v1
compatibility. Initial deliberate incomplete model showed five semantic red
failures; all six tests now pass. Additional Android source/Manifest invariants
check the private adapter, actual lifecycle state usage, START_NOT_STICKY,
no autostart receiver and no public Tool exposure.

The full local Kotlin/JVM, signed APK, Android Lint, exact permissions,
cross-language MCP, security and Host gates must pass; verified disposable
API30/33/34/36 emulator N2/N3 suites provide actual lifecycle regression
evidence, not proof of an active public N1.c Tool. The Android adapter is
inert until a separately authorized in-app consumer is implemented. This
work changes no physical Android device, protected Android setting,
manifest permission, root privilege, Accessibility or MediaProjection grant.
