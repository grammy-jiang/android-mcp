# Android Native MCP V3 — E00/E01 baseline execution evidence (14 October 2026)

## Status — not product completion

**PRODUCT_INCOMPLETE.** Implemented in this increment: first E00 truthful-admission
checker, 20-family explicit GAP registry, E01.a on-device AndroidJUnitRunner,
E01.d reused real FastMCP over installed Native APK, and E01.e exclusive disposable
AVD preflight. E00.b per-case historical executable attribution and independent
signed-oracle release verification remain **not complete**. E01.b–c and E01.f
fixture/permission/full CI tests are next; no protected Native write Tool is enabled.

This is an engineering increment, not an attested N01–N20 feature completion
certificate or an independent security-review sign-off.

### Source inputs and recovery

- Original V3 zip is in the owner's ChatGPT project Library but raw materialization
  returned *no authorized raw-byte materialization path*.
- The V3 architecture, plan, acceptance matrix, JSON acceptance registry, 228-row
  traceability CSV and execution handoff were separately recovered from project
  Library, with original filenames preserved in this repository.
- **Two originals not obtained:** work-package machine JSON and delivery summary
  (ZIP-only). Do not claim these originals were read or reconstructed identically.
- Machine-readable `v3-execution-status.json` contains a **derived** 70-package
  dependency index from the approved prose, clearly labeled as derived.
- The original 228 CSV case IDs were verified unique; existing executable test
  attribution remains `NOT_REVIEWED_V3`, not falsely upgraded.
- Requirements N01–N20 remain 20/20 `NOT_DONE`; 20 opening GAP tasks document
  missing authenticated live Android effects, independent OS oracles and release
  approvals. N19 managed device lab is external-gated; N20 Native Root/ROM is
  unsupported by ordinary APK, with a separate Host read-only fallback requirement.

### Verified commands and outputs (pre-merge baseline)

Baseline source: `7c1d86e44e4f4500d6c5d8b4cca54660628d8b31`.
The first source tree was uncommitted when tests started; pre-merge evidence
must never be misrepresented as testing an identical committed Git tree.

```text
python3 -m unittest discover -s tests -p 'test_native_v3*.py' -q
  16/16 PASS; original intentional RED assertions failed on insecure stubs
python3 scripts/native_v3_gate.py ...
  20 capabilities; 192 new specs; 228 old specs; 70 packages; PRODUCT_INCOMPLETE
python3 scripts/native_v3_reconcile.py ...
  20 OPEN GAP tasks; one source-registered Native Tool; zero verified features
python3 scripts/audit_native_gradle_policy.py --strict
  PASS; all AndroidX test dependencies locked and SHA-256 verified
bash scripts/check-native.sh
  PASS: Kotlin/JVM tests; Python <-> Kotlin SDK, 317 Android safety tests
bash scripts/check-native-apk.sh
  PASS: compiled, Android lint, signed debug APK, exact allowed permissions
```

APKs created from this pre-merge source (SHA256):

- Application: `56b784b071f470acf82e0f7e9bdc55244adb16e5b78b9035611f03f51120e1ae`
- Instrumentation: `e3738f44910acebb3a20ecb19894855ba34532e24e76d17cfc0899088dc6a041`

Exclusive new AVDs created for V3 on Mac only; preexisting Host/Native
worktrees and emulator serials 5554–5560 were not used or reset:

| API | AVD/ADB serial | On-device AndroidJUnitRunner | Actual FastMCP → APK |
| --- | --- | --- | --- |
| 30 | `android_mcp_native_v3_api30_20261014` / `emulator-5564` | 3/3 PASS | status/list/denial/Stop/restart PASS |
| 33 | `android_mcp_native_v3_api33_20261014` / `emulator-5566` | 3/3 PASS | status/list/denial/Stop/restart PASS |
| 34 | `android_mcp_native_v3_api34_20261014` / `emulator-5568` | 3/3 PASS | status/list/denial/Stop/restart PASS |
| 36 | `android_mcp_native_v3_api36_20261014` / `emulator-5562` | 3/3 PASS | status/list/denial/Stop/restart PASS |

The AndroidTest fixture calls PackageManager and real Android services; OS
`dumpsys package` independently confirms the installed debug APK. FastMCP calls
the `device_status` Tool through a forwarded loopback connection to the installed
APK—not the standalone Kotlin JVM server. The ADB harness **only installs**
the test APK, opens/presses the existing visible UI and inspects OS state; it
never manufactures the MCP return value.

Locally retained `artifacts/v3-e01/native-v3-e01-api*-*.json` evidence includes
boot identity, SHA, source baseline, test counts and environment. These files
are excluded by `.gitignore` to avoid exposing device-specific identifiers.

### Required next gaps — do not treat this increment as a milestone exit

1. **E00.b:** map 228 old IDs to actual executable test methods, distinguish mock
   from Android evidence; fix unverified entries or create named test cases.
2. **E00.c/d:** add real separately operated oracle key/trust provisioning,
   genuine approval and role segregation; self-review cannot sign off security.
3. **E01.b:** dedicated signed app fixtures with deterministic UI and file provider,
   plus a signed PackageInstaller fixture.
4. **E01.c:** real Android OS consent, denial, revocation and cancellation paths.
5. **E01.f:** integrate genuine instrumentation + real MCP into opt-in local
   four-API PR gate; broken tests must block.
6. **E02:** real authenticated pairing/transport before exposing any additional
   Tool or Android-sensitive data.

There are also 20 explicitly generated product GAPs in `v3-execution-status.json`.
No `PASS_REAL_E2E` case in the V3 registry has been credited.
