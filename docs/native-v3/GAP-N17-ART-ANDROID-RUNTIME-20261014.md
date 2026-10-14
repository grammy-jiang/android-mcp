# GAP-N17 Android ART compatibility: persisted Native identity and fence

**Date:** 2026-10-14, Sydney. **Result:** real Android bug fixed in the
installed Native APK; E02.c Host public-key pairing remains **PARTIAL**.

## Behaviorally reproduced failure (compilation was green)

The already merged Native V2 identity and synthetic lease state used
`java.nio.file.Files.readString(Path, Charset)`. JVM tests using JDK17
passed. However, a genuine installed Native debug APK with the signed
AndroidJUnitRunner on API36 failed at runtime:

`NoSuchMethodError: java.nio.file.Files.readString(Path, Charset)`

and subsequent ownership attempts returned `NATIVE_ID_UNAVAILABLE`.
A Kotlin class and green build did **not** establish Android capability.

## Engineering remediation and independent device oracle

Replace both persisted private-record reads with the Android ART-supported
`Files.readAllBytes`, retain explicit upper and lower byte bounds and
`NOFOLLOW_LINKS` symlink checks, parse bounded ASCII only after the read,
and retain signed public-key/record integrity validation. No private
Keystore bytes are exported. The Native test continues to verify that
`realMutationAllowed()` is false for synthetic fence state.

Add installed Native APK real AndroidJUnitRunner tests proving:

- Android Framework AndroidKeyStore generated EC public certificate with
  nonexportable private signing material.
- The genuine Android Keystore signature verifies against the public SPKI.
  Forged one-shot challenge proof fails and cannot be replayed.
- Installation identity remains signed and identical after the independent
  test closes/reopens its exclusive owner lock.
- A second concurrent owner is rejected, and lock teardown permits reopen.
- Synthetic durable fence on Android writes the on-device record, closes,
  reloads its monotonic high-water value, denies stale replay, and remains
  incapable of authorizing a real mutation.

The existing Android package/permission/system-service baseline tests are
also preserved. All **8/8 on-device Native instrumentation tests** passed
on each exclusively owned disposable emulator:

| API | AVD/serial | Native AndroidJUnitRunner |
| --- | --- | --- |
| 30 | android_mcp_native_v3_api30_20261014 / emulator-5564 | 8/8 PASS |
| 33 | android_mcp_native_v3_api33_20261014 / emulator-5566 | 8/8 PASS |
| 34 | android_mcp_native_v3_api34_20261014 / emulator-5568 | 8/8 PASS |
| 36 | android_mcp_native_v3_api36_20261014 / emulator-5562 | 8/8 PASS |

Independent test setup uses ADB only to install signed APKs; the
Framework effect is performed inside the real Native Android package,
not a standalone JVM server. OS ownership/QEMU/API/ABI/boot identity and
exclusive emulator lock are checked before installation. Raw logs are
held outside Git under `/tmp/native-v3-gap-n17-art-android-api*.log`.

The serial test gate now requires **eight exact method names** and both
AndroidJUnitRunner start/completion callbacks for each method, rather
than trusting the reported count alone. The existing E01.f matrix
additionally exercises the installed Native MCP status client and twelve
signed fixture tests per Android API: **80 actual AndroidJUnitRunner
executions** in the updated four-API gate.

## Outstanding work — not a production pairing signoff

- N17/E02.c still lacks independently verified visible Host fingerprint
  confirmation, signed live paired MCP Tool request and replay/revocation
  evidence. No self-produced signing key can replace Android user consent.
- N18 still has only a **synthetic** Native fence, not a reviewed real
  effect arbiter; `realMutationAllowed() == false` remains mandatory.
- Android API compatibility of other unused dormant adapters requires
  instrumentation before those adapters become production Tools.
- Independent security review and complete 192 new V3 case receipts remain
  outstanding; product state is **PRODUCT_INCOMPLETE (0/20)**.

This PR fixes an actual runtime blocker and tests it on each requested
Android version; it is not sufficient for E02.c, E08 or N17/N18
product-level completion.
