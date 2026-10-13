# N6.c — durable synthetic fencing high-water and boot epoch

**Status:** tested private high-water ledger, with real lease/mutation
authorization **disabled**. AndroidFenceBoundary always returns DENIED,
and the public Native MCP catalog remains device_status only.

## Durable owner and monotonic fencing rules

NativeFenceState holds an exclusive OS lock in a private 0700 directory
below the app's own no-backup root. Its bounded 0600 fixed journal
stores the last committed fence, Native installation/boot and Host identity,
monotonic timestamp and bounded SHA-256 nonce/action-digest replay
history. No private signing material or personal data is written.

A new synthetic fence must be strictly higher than the durable high-water,
carry a distinct nonce and plan digest, match pinned installation, Host
and boot epoch, be within a 30-second monotonic TTL and have a synthetic
proof flag. The journal is written and fsynced to private staging,
then atomically renamed before reporting a recognized fake fence.
A disk/IO failure before persistence is UNCERTAIN and does not claim a
valid grant. If a process crashes after publication but before response,
the next process sees the higher watermark and cannot blindly replay.

The file persists across normal foreground-service process restarts.
Changed Native installation, Host identity or boot epoch yields
PAIRING_REQUIRED without resetting the high-water mark. A clock rollback
is denied. Only new reviewed pairing could safely establish a different
durable identity. Exclusive file locks reject another concurrent writer;
symlinked/corrupt/oversized state fails closed. At most 32 nonce/digest
hashes are remembered, with an 8 KiB journal cap.

The journal has an unkeyed SHA-256 integrity checksum: this detects
accidental corruption but is NOT hardware-attested anti-tamper storage.
The model is intentionally unregistered for real mutations. Even a
successful fake fence always sets mutation_executed=false and
realMutationAllowed()=false. No model boolean, ADB serial or fake
lease string can authorize PackageInstaller, gestures or system changes.

## Test-first evidence and activation limits

Six T-N6C-01..06 Kotlin tests first failed on a permissive scaffold,
then passed with persistence, replay rejection, boot/reinstall binding,
disk-failure uncertainty, eight-way single-winner concurrency and
default-denied Native MCP. A further corruption/symlink case passed.
Six Python source/Manifest checks enforce owner lock, fsync/atomic
persistence, bounded state, default Android DENIED and unchanged
permissions. Full macOS JDK17/SDK36 quality, APK/Lint/Gradle locks
and disposable QEMU API30/33/34/36 lifecycle matrix are required.
A passing emulator matrix proves only existing public behavior,
not a real Host/Native lease or mutating action. Independent
security review and jointly accepted pairing/fencing protocol
remain prerequisites to any production activation.
