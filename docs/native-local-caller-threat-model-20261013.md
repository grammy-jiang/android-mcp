# N0.b Native local caller and Origin threat boundary

**Status:** testable deny-by-default admission guard for the existing Native
Android/JVM loopback endpoint. This is **not** caller authentication, pairing,
sensitive-Tool enablement, a TLS front end, or a distributed device lease.

## Attacker and deployment model

Android applications share the device's TCP loopback namespace: an unrelated
application may attempt to connect to 127.0.0.1:38765/mcp. A browser may send
cross-origin requests, an attacker may choose hostile Host/Origin headers,
or a local process may send malformed, replayed or very large requests. An
ADB port forward may present the connection under a different, ephemeral
host-side port; neither host port nor loopback IP authenticates a caller.

Only the existing **public minimal v1 device_status** is registered. It
contains no device IDs, installed packages, screenshots, account data,
Accessibility operations or privileged Tools. Existing N2 foreground-only
Activity and explicit N3 foreground-service lifecycle remain unchanged.

## Behavior and non-behavior

- Both real Android and Kotlin/JVM MCP entrypoints call the same Kotlin
  NativeLocalCallerGuard before routing the request. A local Host must use
  exactly 127.0.0.1 or localhost with a valid optional TCP port. Missing
  Host, DNS suffixes, control characters and non-local peer addresses fail
  closed; exact numeric localhost host-side ports remain variable for ADB.
- Missing Origin remains compatible with non-browser MCP **public status**.
  A present Origin may be only plain-HTTP localhost. Untrusted origins,
  null origins and preflight OPTIONS are denied. A local Origin is not
  proof of identity; sensitive actions remain disabled even when all headers
  pass. The ephemeral internal readiness path is only a Ktor listener
  identity probe, never a caller authentication token.
- Deny non-MCP paths, invalid HTTP methods, unusual/chunked request transfer
  encoding, missing/invalid POST length, declared bodies over 128 KiB,
  more than 48 header names, more than 8 KiB parsed header bytes, and
  ambiguous duplicate security headers. Responses use short fixed typed
  public error codes: never echo attacker header values or device data.
- At most 32 concurrently admitted requests per listener (testable with a
  smaller bound). An idempotent ticket closure frees a slot even on handler
  exception, timeout or cancellation. Android lifecycle closes the gateway
  as before; one guard instance is created per listener startup.
- Synthetic approved callers are **unit-test fixtures**, not a cryptographic
  protocol. Fake challenge nonces are one-use within a process-local epoch,
  with a bounded replay set. Sensitive authorization always denies, including
  after a fake approval; this API must not be used as a security grant.
  Neither the UUID epoch nor a fake signature acceptance flag may be placed
  on a public API, emitted as a pairing key, or persisted.
- No new public MCP Tools, Android permissions, outbound network listeners,
  userless Android grants, physical-device operations or shared wire-schema
  changes are part of N0.b.

## Verification layers

1. NativeLocalCallerGuardTest exercises T-N0B-01 through T-N0B-06 and
   concurrent admission/header negative cases on the JVM. Red phase: all six
   behavior cases failed against an intentionally permissive stub.
2. scripts/smoke-native-local-guard.py starts the **real Kotlin MCP SDK**
   JVM server on one ephemeral localhost port and sends eleven hostile raw
   HTTP requests; all must be denied before MCP handlers (the Ktor parser may return HTTP 400 for duplicate or oversized headers before the typed guard).
3. scripts/check-native.sh retains the Python FastMCP-to-Kotlin normal
   device_status test, and adds the real HTTP denial smoke. This does
   **not** prove Android per-process caller identity.
4. Build, Lint, inspect signed APK permissions, and run the
   preverified disposable API 30/33/34/36 N2/N3 matrix. ADB target
   preflight is mandatory before any emulator installation. Physical-device
   functionality is neither tested nor enabled.

## Deferred security and availability issues

This change does **not** authenticate an Android client application: Origin,
Host and IP addresses are attacker-controlled or shared. Unapproved sensitive
Tools remain absent regardless of the declared caller. N6 requires separately
reviewed live paired identity, replay protection and durable lease/fencing.
Header bounds occur after Ktor parses HTTP headers, and declared body length
alone is not a full connection-level streaming rate limiter. Upstream socket
limits, per-client adaptive quotas, slow-client admission and an independently
reviewed authentication transport remain prerequisites to a sensitive live
profile. No remote interface or hardware activation is authorized here.
