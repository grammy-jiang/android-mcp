# N5.d — explicit read-only Host/Native provider fallback status

**Scope:** An inert, pure Kotlin Host/Native provider-health model with a
default-DENIED Android app adapter. This does not connect to the Host MCP
server, invoke ADB, trust an Android serial as identity, execute a
fallback command or register a public Native Tool. The existing
device_status-only Native MCP contract remains unchanged.

## Provider identity and provenance

The synthetic model treats the Host ADB and Native local MCP endpoints as
two distinct read-only providers, never as interchangeable executors.
An injected Host observation has a test-only signed identity flag,
pinned host-key fingerprint, boot epoch, exact transport serial,
online status and bounded observation time. An injected Native
observation has an installation identity, boot epoch, user-started
service/loopback state, foreground state and observation time.
An explicit fake Host/Native binding pins both installation identities,
boot epochs and transport serial with a finite expiry. The serial is
a **transport hint**, not proof of installation identity or possession
of a signing key. Any mismatched pinned identity/boot epoch/serial,
unverified active transport, unverified signer or expired binding
fails closed as STALE_BINDING; old pairing must not be revived from
an ADB get-state response alone.

For Host available and Native stopped, the plan contains only
HOST_ADB and a read-only Host status/observation suggestion. For Host
offline and Native user-started/listening/foreground, it contains
only NATIVE_LOOPBACK and a minimal Native status suggestion. If
both are valid, BOTH_AVAILABLE lists both providers but explicitly
sets automatic_failover=false; it does **not** choose whichever was
checked first. If both are unavailable, it reports UNAVAILABLE; missing,
unknown or stale observations remain typed UNKNOWN/STALE rather than
being guessed as healthy. Probe freshness is limited to five seconds.

## Mutating operation firewall

Only HOST_ADB_OBSERVE and NATIVE_STATUS can return the synthetic
SUGGEST_READ_ONLY status when their provider is in the verified
read-only set. Even with an injected fake writeLeaseActive=true
claim, INSTALL_APK, ROOT, UI_WRITE, ACCESSIBILITY and REBOOT always
return DENIED. An unknown operation is UNSUPPORTED; attempting a read
through an unavailable provider is UNAVAILABLE. The fixed versioned
JSON response carries only status, provider provenance, read-only
flags and synthetic_only; no host key, Native installation ID, ADB
serial, boot epoch, private key, token, user account or transport path.

The AndroidHostFallbackBoundary remains unconditionally DENIED and
does not attempt Host discovery, USB connection, remote login, Android
mutation, service start or privilege elevation. This is a safe
architecture for a later authenticated status-only fallback rather
than a working Host/Native failover router. N6 mutual authentication,
signed challenges, pairing and high-water lease fencing must be
implemented and independently security reviewed before real
provider routing.

## Test-first evidence and deferred acceptance

Six required T-N5D-01..06 Kotlin/JUnit tests were written before
implementation. All six failed on the deliberately permissive
scaffold and subsequently passed with provenance-preserving
denial-first policy. Two supplemental Kotlin tests verify that an
ADB serial alone cannot establish a binding and that stale/future
observation or a disconnected Native user session cannot be silently
reported as healthy. Six Python source/Manifest checks require no
actual ADB or USB call, no Host mutation, no Android permission
expansion and unchanged Native public one-Tool catalog.

Required release gates are full macOS JDK17/SDK36 Host+Native
Kotlin/JVM, Python/Kotlin MCP transport, privacy/security, locked
dependencies, signed APK and Android Lint, plus a complete
preflighted disposable QEMU API30/33/34/36 baseline matrix. That
emulator matrix tests unchanged Native lifecycle, **not** a real
paired Host/Native transfer or sensitive write lease. No physical
Android device, Host-owned worktree, ADB device operation, app install
or privileged permission is touched by this feature package.
