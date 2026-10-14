# E01.f — mandatory actual Android infrastructure matrix gate

**Scope:** E01.f engineering CI/PR gate, not N01–N20 product-feature
certification. **Status:** runnable on four exclusively owned disposable AVDs.
This increment deliberately leaves E01.c Android consent flows as a separate
unresolved prerequisite; all authenticated/sensitive Native capability
families remain NOT_DONE.

## PR gate

Invoke both from the active Native branch, with a verified JDK 17, SDK 36,
locked Python 3.13, exact clean Git tree, and four exclusively owned QEMU AVDs:

~~~bash
bash scripts/check-native-local-ci.sh
bash scripts/check-native-local-ci.sh --v3-matrix
~~~

The first command runs Host/Native unit, security and quality checks. The
second repeats those gates and **additionally** builds, signs and installs
the real Native APK and AndroidJUnitRunner; runs the real Streamable HTTP
client from Python against the installed Native APK; builds/runs the
independently signed deterministic UI/SAF fixture; verifies external OS
state, color pixels, counter increments, process-restart persistence and
unapproved SAF denial. Every API 30/33/34/36 is mandatory. No
one-version shortcut, mock-only pass or ADB-generated Native side effect
is accepted.

A successful E01.f receipt contains a single narrow
PASS_E01_INFRASTRUCTURE_ONLY status; the actual V3 Native device-control
product remains PRODUCT_INCOMPLETE. The four AVDs are not shared Host
emulators 5554–5560:

| Android API | Exclusive disposable AVD | Serial |
| --- | --- | --- |
| 30 | android_mcp_native_v3_api30_20261014 | emulator-5564 |
| 33 | android_mcp_native_v3_api33_20261014 | emulator-5566 |
| 34 | android_mcp_native_v3_api34_20261014 | emulator-5568 |
| 36 | android_mcp_native_v3_api36_20261014 | emulator-5562 |

AVD owner marker, QEMU process PID and arguments, API/ABI, current kernel boot
epoch and kernel QEMU flag are validated by both Android executors. Each run
takes an exclusive OS file lock. A physical Android serial is never eligible.
ADB installs a test APK and drives the fixture's visible UI; Native status
responses come only through the installed Native MCP APK.

## Exact validation rules

- All four Android API results must be present, distinct and complete.
- For every API, three real Native AndroidJUnitRunner tests and nine signed
  fixture instrumentation tests must succeed, **48 real Android tests**.
- Native FastMCP must call exactly the one approved status Tool and verify
  discovery, on-device schema/result, unknown Tool rejection, Home Stop and
  Activity restart. JVM prototype HTTP responses never qualify.
- APK hashes, fixture signing digests, source Git SHA/tree, boot identity,
  process identity and selected emulator must match across both observers
  and all applicable APIs.
- The fixture side effect must be +1, survive process death and be independently
  queried from its own process; known-pixel screenshot and SAF permission
  refusal cannot be inferred from an unrelated ADB action.
- Missing, duplicated, stale, wrong-version, tampered or synthetic receipts
  fail closed. Test results stay under gitignored artifacts/v3-e01 with
  bounded output and no captured private user data.
- The negative harness tests intentionally corrupt the above conditions
  and assert the gate rejects them. A full passing CI result is impossible
  from a single emulator or compilation alone.
- This is a **local** gate; it does not request paid GitHub-hosted Actions.

## Explicit remaining gaps

E01.c genuine system consent and refusal/cancellation/revocation, complete
per-version Android permission dialogs, and E02 authenticated Host–Native
pairing are **not supplied by this infrastructure gate**. E01.f should not be
certified as a complete product release stage until those required tests,
independently trusted OS-effect receipts and ChatGPT ordinary Chat client
surface are integrated and reviewed.

N01–N20 remain NOT_DONE; the initial twenty GAP-Nxx-001 items remain open.
Future V3 PRs must extend the matrix with their feature-specific real
positive and negative Android API tests, not call the existing status-only
smoke a test of screenshot, Accessibility gesture, import/export or installer.
A distinct release-signoff from an independent security reviewer is required
before production privileged enablement.

**Rollback:** revert the two new E01.f scripts, small local-ci wiring and
adversarial tests. No Host code, Native app manifest, Android permissions or
shared wire protocol change.
