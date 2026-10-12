# Native N3 local acceptance and no-cost CI evidence

**Context:** GitHub-hosted Actions on PR #16 returned `failure` after 2–6
seconds **without executing any steps**. GitHub's own annotation states that
account payments or spending limits prevented job start. These are
`not_run/billing_blocked` checks, not code/test failures and not PASS.

The feature PR remains Draft until all required release evidence is reviewed;
do not change GitHub billing limits or claim GitHub Actions executed.

## Locally verified results (2026-10-12)

- **MacBook Pro, Apple Silicon, Android API30,33,34,36 ARM64 AVDs**:
  the exact, fail-closed `scripts/verify_native_api_matrix.py` full suite
  returned PASS on all four verified emulators (duration ~116 seconds for
  the first complete run). API30/33: N2 runs and Home stops, N3 disabled.
  API34/36: N2 and N3 both run, notification permission refusal, real
  notification Stop, service + notification removal, Home keeps N3 alive,
  competing Activity launch rejected and no automatic OS restart.
- **MacBook Kotlin/JVM**: 20 Native pure lifecycle/port-owner/foreground
  support tests, plus original Native protocol tests, pass. Python↔Kotlin
  official SDK HTTP smoke and versioned response schema pass.
- **MacBook Python 3.13**: 86/86 Native safety, permission, AVD-target,
  UI and matrix preflight tests pass.
- **MacBook Gradle**: JDK 17, Gradle 9.6, AGP 9.4, Android SDK 36. APK/Lint,
  signing and four exact Android permissions pass. Four Gradle lockfiles
  and 540 SHA-256 records cover 316 resolved dependency components.
  An `--offline --dependency-verification=strict` mixed Android/JVM task
  graph passed locally.
- **Linux aarch64, sextant Raspberry Pi 5**: transferred an immutable,
  SHA-256-verified archive of committed Native Python test sources into
  its own private `/tmp` directory, and ran 86/86 Python tests plus
  static Gradle policy preflight successfully. The existing Host
  checkout was not modified; the Pi's connected OnePlus was not used.
  No Linux Kotlin/Android Gradle build was run (JDK17 absent).

## One-command repeatable local acceptance

With appropriately licensed Android SDK and JDK17 already configured:

```bash
bash scripts/check-native-local-ci.sh
```

Add `--matrix` and **all four explicit emulator mappings** only when
these disposable AVDs have already booted and their APIs can be verified:

```bash
bash scripts/check-native-local-ci.sh --matrix \
  --api30 emulator-5560 --api33 emulator-5558 \
  --api34 emulator-5556 --api36 emulator-5554
```

The matrix preflight verifies each target's QEMU identity/API and online
status **before any APK installation or UI action**. This cannot select
an attached physical phone/tablet as a fallback.

## Limitations and merge decision

- GitHub macOS/Linux Actions are still `not_run/billing_blocked`.
- Linux aarch64 Gradle/Kotlin compiler and clean Linux x86_64 Android SDK
  builds are not yet proven with the newly generated dependency verification
  metadata. Platform-specific checksum additions must be reviewed, not
  blindly regenerated.
- This prototype serves a minimal, unpaired localhost `device_status`
  only. No sensitive Android APIs, Accessibility, Root or arbitrary shell.
- No APK installed on OnePlus Pad 3, no reboot, no physical state changes.
- Release gating and the final PR #16 independent security review still
  need completion. A plan or static preflight alone never certifies this.
