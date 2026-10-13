# Native N7.c — explicit Activity launch, non-idempotent safety planning

**State: non-executing model; third-party Android app launch remains disabled.**
The production Android Native MCP app still registers `device_status` ONLY.
Its `AndroidExplicitLaunchBoundary` always returns DENIED, with no
Android `startActivity`, arbitrary cross-package launch, foreground-service
background-start bypass, shell command or foreign package force-stop.

The typed local Kotlin planner wraps the existing N2.c exact-component
Intent planner, so it requires a visible, enabled, exported Activity in an
explicit package/component allowlist; only `ACTION_MAIN/CATEGORY_LAUNCHER`,
current user, no implicit/deep-link URI, extras, selector or activity flags.
Fake caller authentication, a fresh fake signed grant, simulated explicit
user approval, unlocked screen, own throwaway QEMU indicator and actual
foreground user gesture are prerequisites for a pure PLAN state. These
boolean test fixtures are NOT real OS identity/authorization; they cannot
be sourced from MCP, public HTTP or platform Intents.

API 30, 33, 34 and 36 are modelled. A fake foreground-service-only origin
or Android background state is always denied. One-use action IDs are
synchronized and capped at 64 entries; after a *synthetic* ambiguous
post-dispatch result the plan ID remains in a tombstone set. New action IDs
for the same plan cannot auto-repeat it. Owner/caller/Origin revocation or
Stop after planning and before fake dispatch blocks it. This is NOT an
authenticated persistent action journal, and no real task/Activity is moved.
All receipts say `real_launched=false`, `real_dispatch_allowed=false`,
`automatic_retry=false` and redact target package and action identifiers.

Six T-N7C-01..06 Kotlin tests failed as meaningful behavioral RED checks on
a permissive local fixture and later passed GREEN; two additional Kotlin
cases test hostile/fake consent/QEMU inputs and 10-thread same-action races.
Seven Python Manifest, public Tools, cross-user/implicit Intent and Android
boundary regression tests also pass. Four-API QEMU baseline smoke starts
ONLY the already-allowed Native Activity as before, not a new foreign-app
launch feature. Real user-authorized third-party Activity launch would
require a separate Android OS grant + independent security review and a
strict disposable-emulator-only implementation.
