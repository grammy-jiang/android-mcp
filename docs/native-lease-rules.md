# Android Native lease rules — pure Kotlin model

The lease-rule module is a **pure functional model**, not a currently enforced
lock on an Android tablet. It has no network listener, no database, no trusted
credentials, no ADB, and no Android OS permission.

The model checks explicit device/pairing/boot identities, exact owner +
request + fence on release, monotonic Native-side time, ≤300-second lease TTL,
device contention, stale fencing tokens, and malformed plan digests.

It defines an interface-independent transition from an observed state to
`Accepted(nextState)` or a typed `Rejected(reason)`. **Only a future
authenticated Native service may commit a proposed transition.**

## Production requirements before any mutation is enabled

1. Authenticate the caller and bind a Host pairing key to a Native
   installation identity. Model-supplied string IDs alone never authorize.
2. Persist both `highFence` and the active lease atomically with append-only
   audit evidence before acknowledging acquisition.
3. Use native `SystemClock.elapsedRealtime()` rather than a model-provided
   timestamp. Verify the Android boot epoch to make elapsed time comparable.
4. Native controls normal UI arbitration; Host SQLite controls only competing
   Host processes. The Host must not proceed without a fresh Native-issued
   lease receipt and valid external operator approval.
5. On process restart, revoked pairing, epoch change, or unknown state, deny
   automatic mutation; require explicit reviewed recovery.
6. Do not accept a public MCP argument like `approved=true`, and do not
   expose Root or a raw ADB/privileged shell through a network listener.

This Kotlin model intentionally cannot make the actual system safe alone;
its tests are preparatory evidence for the forthcoming Android IPC service.
