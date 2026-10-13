# Native N7.b — Android installer consent: strict preflight and honest block

**Real Android-mediated installation confirmation: BLOCKED, not passed.**
Do not treat this safety work as a genuine PackageInstaller consent UI test.
The current production APK has no `REQUEST_INSTALL_PACKAGES` permission,
no independently reviewed execution/consent Activity, no dedicated signed
trusted installer test APK, and no proven exclusively owned disposable AVD
for such an install. We must NOT enable these privileges, silently install
packages, switch to a physical phone or use `adb install` to fake user consent.

This package adds an internal Kotlin simulator for consent eligibility,
refusal, cancellation, foreground loss, process death and Stop with all real
side-effect fields hard-coded false. The Android-side entry point returns
BLOCKED and has no live registration. Fake QEMU / signed-test metadata is
never accepted as actual Android proof.

An additional **read-only actual-ADB** preflight accepts exactly four
specified emulator serials, checks QEMU, boot completeness and API 30/33/34/36
using the existing matrix guard, then emits a JSON `result=blocked` (exit 3).
It does not inspect or install an APK, grant any permission, open any app,
use package manager or start an Activity. Physical serials and mismatched
emulator/API/QEMU identities fail before any other work. The actual target
preflight is evidence of emulator identity **only** — not proof of AVD
ownership, APK authenticity, or a user-mediated install flow.

## Test status, N7.b

- T-N7B-01: fake eligibility and mandatory OS consent **PASS**;
  **real OS user-confirmation UI BLOCKED**, no claim of launch.
- T-N7B-02: simulated refusal/cancellation no install/session **PASS**;
  **actual OS refusal flow BLOCKED**, no UI launch attempted.
- T-N7B-03: adversarial physical/unowned/invalid QEMU/API/unsigned
  test artifact denial **PASS** (real serial preflight is read only).
- T-N7B-04: injected process-death, background, abandonment and Stop
  semantics **PASS**; actual PackageInstaller session **not created**.
- T-N7B-05: actual QEMU identity/API30/33/34/36 read-only preflight
  **PASS**, real install consent/unknown-sources UI **BLOCKED**.
- T-N7B-06: no public write Tool, privileged Manifest permission, silent
  install, ADB package install or real Android adapter **PASS**.

Six Kotlin test-first assertions all genuinely RED on a permissive scaffold,
then GREEN; seven Python policy/Manifest/guard tests test the exact actual
side-effect-free CLI shape and synthetic malformed inputs. The four-API
Native baseline UI/FGS suite may run on QEMU, but DOES NOT test APK installation
consent. This inert scaffold is mergeable as a truthful safety step, while the
real consent acceptance obligations stay explicitly blocked until verified
owned disposable hardware profile, dedicated signed fixture, actual
Android-mediated user action and separate independent review exist.
