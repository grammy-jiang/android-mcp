# N0.d — Native typed Android permission/readiness model

**Scope:** internal-only Kotlin permission snapshot and fail-closed N3
foreground-service startup recheck. This change adds no Android
Manifest permissions, exported components, public MCP Tools, privileged
operations, or physical-device deployment.

## Contract and Android boundary

- NativePermissionReadiness evaluates a fresh injected Android grant
  probe each time, with one versioned, bounded snapshot. Statuses are
  granted, denied, unknown, not_applicable, unsupported; a boolean
  foregroundMayStart() is true only if API is 34+ and all
  currently required permissions are actually reported granted.
- Android 11/API30 does not query POST_NOTIFICATIONS as a runtime
  permission; API33 does, but the current specialUse FGS design is
  explicitly unavailable on API33. API34/36 requires granted internet,
  foreground-service base, specialUse foreground-service declaration and
  granted notification permission, with all statuses rechecked before
  each user-requested foreground service start.
- AndroidPermissionReadiness lives behind Android's Context
  adapter; pure Kotlin/JVM tests inject deterministic grants, denial,
  revocation and OEM exceptions. Unknown or unexpected exceptions
  fail closed without exposing platform error details. No exception
  text is persisted or serialized.
- Both the user-visible Activity and the Android Service re-evaluate
  readiness at Start. An earlier permission callback cannot authorize
  a later start, and a subsequent denied/revoked Start directs an
  already-running service through the existing verified Stop pathway.
  The user-visible Stop remains operational regardless of grant state.
  A prior approval never grants Accessibility, MediaProjection,
  package-wide visibility, Device Owner, Root or UI mutation rights.
- The only public Native MCP Tool remains the exact N0.a v1
  device_status. The readiness snapshot is private application
  data, not a new public status or caller-authorization profile.

## Executed tests and honesty boundaries

- T-N0D-01..06: six named Kotlin/JVM tests, with five meaningful
  assertion failures on the initial conservative stub and all six
  green after implementation; supplemental tests cover combined FGS
  denial and exception/redaction. Python Native-only invariants verify
  Manifest permissions, source use of the Android OS recheck adapter,
  and absence of a new public Tool.
- Signed actual API36 APK, Android Lint, strict dependency policy,
  Kotlin/JVM MCP, SDK-free Python, zero-paid repository/local Host
  checks and verified disposable API30/33/34/36 acceptance are
  independent gates. Actual permission denial and service behavior
  must be proven on a real emulator, not inferred from JVM mocks.
- Revocation on Android may cause process death or be subject to OEM
  policy. This implementation never silently grants or automatically
  restarts any service. Revocation is caught at the next explicit
  Start/recheck; it does not implement continuous background
  monitoring, or claim to asynchronously stop all already-running
  sessions the instant Android policy changes.
- No physical OnePlus/other Android device is modified. No Google
  terms are accepted, and GitHub paid Hosted Actions are unavailable.

## Actual emulator permission-revocation acceptance

On 2026-10-13, the verified disposable QEMU Android API 34
(emulator-5556, job bac47c2c9b46) and API 36 (emulator-5554,
job 9de868bf4894) passed real notification-permission revocation.
The test started the app from the visible Activity with a granted
notification permission, verified the actual foreground service and
MCP socket, revoked POST_NOTIFICATIONS through the verified emulator
ADB target, required HTTP listener shutdown and Android service plus
notification removal, then confirmed a new user Start did not
silently relaunch under a revoked grant. Grant was restored for the
test environment afterward. This is OS/emulator evidence, **not**
physical-device permission approval, a continuous permission listener,
or a claim that Android's runtime revocation always kills processes
on every OEM build.
