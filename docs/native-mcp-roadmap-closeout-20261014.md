# Android Native MCP — N0.a through N8.b safe-roadmap closeout

**Snapshot main:** `f3c2771668fa1fe91396e77c5f507b9bf0312d64`.
The 38 distinct work-package IDs from `docs/native-mcp-implementation-plan-20261013.md`
are each represented by an actual ancestry-verified merged Native PR commit. The
228 numbered IDs in `docs/native-mcp-serial-test-cases-20261013.md` are the
**specified** tests, not a declaration that 228 real-device tests ran.

The authoritative capability-by-capability source/status/permission/test-layer/
PR/merge ledger is [`native-capability-ledger.v1.json`](native-capability-ledger.v1.json).
Its automated verification is `python3 scripts/check_native_capability_ledger.py
--strict-git`, with negative regression tests in
`android/tests/test_native_capability_ledger.py`.

## Disposition — not 20 publicly enabled Native Tools

| Current status | Capability IDs | Count |
| --- | --- | ---: |
| `merged_verified` (strictly local status/FGS emulator behavior) | N01, N16 | 2 |
| `inert_merged` (private/internal, no new public sensitive Tool) | N02, N03, N04, N05, N06, N13, N14, N18 | 8 |
| `plan_only` (synthetic or bounded non-executing policy) | N08, N11, N12 | 3 |
| `blocked` (real Android authorization/protocol/hardware prerequisite absent) | N07, N09, N10, N15, N17, N19 | 6 |
| `unsupported_by_platform` for ordinary unprivileged Native APK | N20 | 1 |

Actual Android Native MCP production entry point continues to advertise **only
`device_status`**. The real Manifest still declares exactly INTERNET,
FOREGROUND_SERVICE, FOREGROUND_SERVICE_SPECIAL_USE and POST_NOTIFICATIONS;
there is no Root, DeviceAdminReceiver, boot receiver, permission escalation,
remote unauthenticated listener, executed arbitrary shell or public UI action
endpoint. Status-only Native Android 14/16 FGS/notification Stop is tested on
owned test-only QEMU endpoints; API30/33 retain the expected legacy denial.
All device mutations remain disabled.

## What remains outside the safe roadmap merge receipts

- **N7.b real installer confirmation:** Android-mediated user approval,
  refusal and cancellation on an exclusively proven disposable test emulator
  remains **BLOCKED**. The read-only QEMU identity proof and baseline Activity
  matrix do not substitute for a dedicated signed install fixture or OS
  PackageInstaller UI consent. No silent installation is permitted.
- **Real Host/Native pairing, external caller security and leases:** N6
  Keystore/challenge/fence foundations are not a functioning authenticated
  cross-runtime mutation grant. Physical-device pairing, replay-safe live
  lease execution, external service authentication and independent threat
  model review remain release-blocking prerequisites.
- **Sensitive Android capabilities:** live MediaProjection capture/recording,
  Accessibility node/gesture use, SAF document transfer outside private
  fixtures, PackageInstaller execution, third-party app launch and enterprise
  Device Owner policies require real Android permissions, user-visible consent,
  separate reviewed enabling changes and feature-specific device acceptance.
- **Device maintenance:** ordinary Native APK has no Root/Bootloader/ROM
  flashing ability. The N8.b Host fallback is a non-executing recommendation
  for owner-confirmed investigation, never a reboot/unlock/erase/flash Tool.
- **Hardware and independent evidence:** local JDK17/SDK36, Kotlin/JVM,
  Host/Native Python, signed debug APK/Lint, Git quality hooks and real QEMU
  API30/33/34/36 Native baseline passed at the final N8.b exact source tree.
  This does not establish actual physical Android Native APK acceptance,
  full destructive reboot coverage, audited external privilege enabling,
  or GitHub-hosted Actions execution (blocked by billing).

**Final safe Native PR:** [#102](https://github.com/grammy-jiang/android-mcp/pull/102).
**Final safe-roadmap main SHA:** `f3c2771668fa1fe91396e77c5f507b9bf0312d64`.
The earlier Native N3 **draft PR #39** remains a separate unmerged historical
acceptance checkpoint; it must not be mistaken for one of the 38 merged
N0.a–N8.b work-package receipts. Review independently before closing it.

Completion here means the 38 stated safe/blocked/plan-only implementation
slices have landed, and every N01–N20 family has an auditable disposition.
It does **not** mean production feature complete, physical tablet deployment
or authorization to execute privileged Android device changes.
