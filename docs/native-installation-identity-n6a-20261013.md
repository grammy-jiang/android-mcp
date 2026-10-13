# N6.a — private Native installation identity and signature verification

**Status:** safe, internal installation-identity foundation only. The Native
MCP public catalog remains exactly device_status. No host device is actually
paired and AndroidInstallationIdentityBoundary reports pairing_enabled=false,
mutation_enabled=false. No physical Android device or user account is changed.

## Key ownership and private persistence

The Kotlin NativeInstallationIdentity model uses an injected provider for
ECDSA/P-256 public-key generation, signature and verification. The Android
provider uses AndroidKeyStore with an application-owned signing alias and
SHA256withECDSA; no raw private-key bytes are exported, logged or persisted.
The JVM unit-test provider holds a synthetic key pair in process memory.
The public installation identity contains only a random installation UUID,
SHA-256 public verification-key fingerprint and X.509 public SPKI. It never
contains Android serial/MAC/IMEI or a persistent hardware identifier.

One record is persisted in the app-owned no-backup directory under an
exclusive file lock, with owner-only 0700/0600 permissions, NOFOLLOW_LINKS,
bounded record length, fsync and atomic staging. The record contains a
format version, random installation ID, public-key digest and signature
produced by the private Keystore provider. On reopening, the file signature
is independently checked against the same Android Keystore public key.
Corrupted record, altered ID, mismatched/missing keystore key, symbolic
link or competing process owner fails closed and never silently resets
an existing identity.

If an app uninstall/data-clear removes its private identity record,
a new owner explicitly deletes any orphaned key at the fixed app-scoped
alias and creates a fresh identity under the OS lock. Previous Host
bindings cannot be used to authenticate that new identity. A normal
FGS restart with intact state preserves the installation ID/public key
but rotates the process epoch and discards ephemeral challenges.

## Challenge security and deferred activation

The internal test-only challenge uses 192 bits of random input, a maximum
30-second monotonic TTL, and a per-process one-use pending slot. A forged
signature, stale challenge, clock rollback, process restart or second
attempt is rejected. Signatures are cryptographically verified against
the published public key rather than trusting a model-supplied key or
ADB serial. An accepted synthetic proof is NOT a signed Host/Native
pairing grant. The service does not publish a pairing route, sensitive
Tool, network listener or an authenticated remote channel.

The six T-N6A-01..06 behavioral Kotlin tests were written before the
implementation and all six failed on a permissive scaffold. All six
passed with the private owner model. Four extra Kotlin tests cover
signed-record tampering, malicious symlink, expired/replayed/clock-
rollback challenge, and six competing concurrent opens. Five Python
source/Manifest checks confirm AndroidKeystore use, no raw private key
encoding, strict filesystem ownership and unchanged one-Tool public
MCP profile and four-permission manifest.

Passing tests here proves a testable private identity design and built
Android Keystore code only; it is not evidence of live physical-device
key generation, hardware-backed security, Host enrollment or N6 pairing.
N6.b/N6.c mutual authentication and durable lease fencing, genuine
user approval and independent security review are prerequisites to
enabling an actual signed identity route.
