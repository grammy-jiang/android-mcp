# N6.b — private signed Host challenge simulator; production pairing disabled

**Status:** internal, fake-only signature policy. Android Native MCP still
exposes only device_status and AndroidPairingChallengeBoundary unconditionally
returns UNAVAILABLE. Neither connecting a loopback client, supplying a Host
identity string, opening an ADB tunnel nor presenting a valid synthetic
signature enables a real pairing, a write Tool or any device capability.

## Synthetic signed challenge identity

The Kotlin NativePairingChallenge uses an injected P-256 Host verification
public key (X.509 SPKI), pinned Native installation ID, Native boot epoch,
Host identity and exact local Origin. It creates a 192-bit random nonce,
versioned N6B2 packet and action-plan SHA-256 digest with a monotonic
15-second TTL. The synthetic proof must have an authentic ECDSA signature
over exactly the canonical packet, belong to the expected pinned Host and
Origin, match the exact Native instance/boot epoch, and be consumed once.
Wrong signer, changed packet/digest, foreign Native installation, stale
clock, replay or missing/invalid Origin cannot be accepted.

The per-instance pending collection has no persistence, timer or background
worker; it accepts at most 100 simultaneous challenges, fixed 1024-byte
maximum packets and 256-byte maximum DER signature. Clock rollback
invalidates the entire session, and Stop/restart clears all pending
tokens. A model-provided fake boolean or unauthenticated localhost
request is never a verified signed proof. Even a valid synthetic
signature returns only FAKE_RECOGNIZED in internal Kotlin tests, and
productionPairingEnabled() remains false.

## Integration, testing and deferred activation

Six named T-N6B-01..06 Kotlin tests exercise bound signed challenge,
replay/wrong signer/origin/plan/cross-device/expiry denial, minimal
localhost status policy, restart invalidation, 100 concurrent
challenge capacity and absent joint protocol. Two initial test
expectations were corrected to reflect fail-closed cross-device
DENIED and an explicitly expired pending challenge, not to weaken
the verifier. Five additional Python code/Manifest tests verify
strong signature operations, exact Origin, capped resources, no
public enrollment route and unchanged Android permissions.

This intentionally does not invent a production shared Host/Native
protocol or Host-side signing grant. A future jointly accepted
schema, actual Host attestation, independent security review, user
enrollment, high-water lease fencing and genuine Android permission
gates remain mandatory before a public pairing endpoint is enabled.
Android API30/33/34/36 emulator acceptance verifies only unchanged
MCP Activity/foreground/notification lifecycle, not real signed
pairing over a device. No physical Android or Host-owned code is
modified by this package.
