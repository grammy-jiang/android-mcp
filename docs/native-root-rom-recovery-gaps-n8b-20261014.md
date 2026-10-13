# Native N8.b — Root/Bootloader/ROM gap map and manual Host fallback

**Status: safe planning only.** An ordinary, non-root Android APK cannot
root a device, unlock its bootloader, flash its ROM or repair an unbootable
Android OS. The Android Native MCP production server still advertises only
`device_status` and has no privileged process, shell, ADB/Fastboot/raw
partition transport, boot receiver, device-admin provisioning or elevated
network listener. The N8.b Android boundary always returns UNSUPPORTED.

The private JVM-only NativeRootRecoveryGap maps `ROOT`, `BOOTLOADER` and
`ROM_FLASH` to UNSUPPORTED; raw shell, unlock, erasure and lockscreen bypass
requests to DENIED; and a limited Host-supervised diagnostic handoff to
PLAN_ONLY **only under injected fake owner/Host/device authorization**.
These fake booleans are not a real signed Host identity or Android privilege.
No model approval or untrusted command can authorize Root, flash or wipe.

If Native crashes or the OS does not boot, its local listener is not
reachable; the fake model reports UNAVAILABLE, never claims it can reboot
or remotely repair itself. Any future Host investigation requires a
**separately authenticated** Host connection, separately established ADB or
Fastboot ownership, device-specific manufacturer recovery instructions,
explicit physical-owner presence and a new operation-specific authorization.
This model only produces three non-executable human-readable suggestions:
verify device ownership, use authorized **read-only** Host diagnostics,
and consult official manufacturer recovery instructions. It never prints
literal shell commands, device IDs, pairing secrets, unlock instructions,
or a programmatically executable recovery plan.

One-use synthetic requests are bounded to 32 and never evicted into an
unsafe replay window. User Stop is terminal. JSON diagnostics are redacted
and always report `operation_executed=false`, `automatic_retry=false` and
`host_supervised_only=true`. Privilege enabling would require independent
security review, genuine Android/Host authorization, operator approval,
physical device controls and separate engineering milestones.

Six T-N8B-01..06 Kotlin tests were RED (meaningful behavioral failures)
against a permissive local-only scaffold before GREEN. Three extra tests
verify bounded replay/Stop, redaction of Host tokens and API30/33/34/36
simulated denial. Seven Python source/Manifest/public-Tool security checks
assert no real OS side effects. Actual QEMU API30/33/34/36 baseline smoke
preserves app lifecycle/permissions; **it is not root, bootloader, unbootable
OS or ROM acceptance**. No real rooted hardware is targeted or changed.
