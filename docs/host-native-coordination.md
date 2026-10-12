# Host ↔ Android Native MCP coordination — design gate

**Status: draft, unimplemented.** This is a security boundary for the two
runtimes in one repository, not an additional public MCP Server.

## Goals and threat assumptions

A USB-connected Host MCP can issue ADB commands while the tablet's Native MCP
can concurrently interact with the same apps and settings. Host-level SQLite
leases protect only concurrent processes *on the same Host installation*. They
cannot arbitrate against a Native runtime or a second Host computer.

The Native bridge must not accept caller-provided claims of root privilege, a
device ID string, or a model-authored `approved=true` as authority.

## Pairing and identity

1. Host discovers the tablet using ADB and an explicitly selected transport ID
   or serial; the Native instance exposes a separately generated installation
   identity and public key via an authenticated pairing channel.
2. A trusted local setup step binds the selected ADB transport and the Native
   instance identity. The native identity is not inferred from its package name,
   Android serial, network hostname or MAC address.
3. Persist the pairing in a private Host state directory and on the Native side;
   require explicit re-pairing when the Android install identity changes.
4. Before every joint lease, mutually authenticate with short-lived challenges.
   Use the USB/ADB channel only as an explicitly configured transport; never
   expose an unauthenticated root IPC endpoint over TCP.
5. An Android reboot or ROM upgrade must invalidate transient leases. Device
   state after a reconnect is not trusted merely because ADB reports `device`.

## Planned lease state machine

```text
UNPAIRED -> PAIRED -> IDLE -> ACQUIRING -> HELD -> RELEASING -> IDLE
                                  |         |
                                 DENIED    EXPIRED/UNKNOWN -> RECOVERY
```

- Native is authoritative for normal UI/mutating-operation arbitration.
- Host SQLite assigns monotonically increasing fencing tokens to Host leases.
  Native must persist a corresponding per-pairing high-water mark and reject
  stale tokens, **including after service restarts**.
- A lease binds device identity, Host installation/owner identity, an exact
  canonical action digest, nonce, fencing token and expiry.
- Acquisition is atomic and idempotent for a request ID, and should have
  narrow TTLs. Renewals require the same authenticated lease identity and
  cannot silently extend an expired operation.
- The executor must check ownership immediately before mutations, and the
  Native service must prevent competing UI operations until release/expiry.
  If Native becomes unresponsive or loses the lease, Host returns uncertain /
  partial status rather than silently taking control.
- Diagnostic reads may run concurrently only if they do not perturb the
  device; Logcat may itself contain sensitive information.
- When Android fails to boot, Host emergency recovery is a **separate
  audited, human-approved mode**, not a normal lease bypass.

## Minimal protocol fields (design, not frozen JSON Schema)

`pairing_id`, `protocol_version`, `native_instance_id`,
`host_identity`, `device_boot_epoch`, `request_id`, `plan_digest`,
`fence`, `expires_at`, `challenge_nonce`, authenticated response.

No raw operator-signing private key may be transmitted to the tablet,
embedded in a model-visible request or stored alongside ADB credentials.

## Required pre-hardware and hardware verification

- Deterministic model tests for acquire/renew/release/expiry/retry.
- Replay, duplicate request, stale fencing token and clock rollback denial.
- Two Host MCP processes targeting the same ADB device.
- Concurrent Native UI action versus Host APK deployment.
- USB disconnect, Native process death, tablet reboot and recovered pairing.
- Pairing replacement, stolen-token attempt and inconsistent device identity.
- Receipt/audit durability before and after both successful and ambiguous
  operations, with no model-initiated privilege escalation.
- End-to-end real tablet tests on macOS and Linux.

Until these checks pass, `SecureMutationCoordinator` remains an injected,
non-default prototype and no public MCP tool can execute APK installations,
instrumentation tests, device reboots or privileged commands.
