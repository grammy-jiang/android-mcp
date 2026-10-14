# E01.b — Android Native MCP V3 signed fixture APKs (2026-10-14)

Status: **fixture work package ready for review and merge**, **product incomplete**.
These test actors are *not* production Native MCP handlers. No V3 N01–N20
capability or `PASS_REAL_E2E` case is credited on fixture-only evidence.

## Independent fixture apps

1. `org.androidmcp.v3fixture` — signed, opt-in APK with deterministic
   RGB image blocks, a real focusable UI counter, persistent SharedPreferences,
   and exactly one fixed read-only `DocumentsProvider` SAF document:
   `ANDROID-MCP-V3-FIXTURE-DOCUMENT-v1\n`. A separate synthetic read-only
   `ContentProvider` exposes **only** that fixture's integer test counter
   for independent Android OS observation. No user data/credentials collected.
2. `org.androidmcp.v3installfixture` — separately signed, minimal installation
   target APK with its own application ID, pinned version and no permissions.
   This is only a PackageInstaller **test artifact**. Installing it via ADB
   is never admissible N16 success.
3. `org.androidmcp.v3fixture.test` — signed AndroidJUnitRunner APK with
   **9 genuine on-device instrumentation tests**. AndroidX adds the
   `android.permission.REORDER_TASKS` test-only permission; the two independently
   installable fixture apps request zero Android permissions.

The document provider is exported for the **system** picker only, protected
by `android.permission.MANAGE_DOCUMENTS`; a direct shell app without
`ACTION_OPEN_DOCUMENT` receives Android `SecurityException`, verified on all
four API versions. Reads use transient OS pipe descriptors and reject write
modes, unknown document IDs, and pre-cancelled operations. Concurrent
multi-reader requests return the identical known bytes. The synthetic oracle
cannot be inserted into, updated, or deleted from.

**Important API 36 finding:** with target SDK 36, edge-to-edge layout puts the
button underneath system bars unless Android `WindowInsets.Type.systemBars`
is applied. Android 16 real gesture tests initially failed even though the
screen drew; the fixture applied actual WindowInsets to repair tactile access.
Both real MotionEvent injection and independent ADB user taps now work on
API 30, 33, 34 and 36. No version-specific test was skipped or mocked.

## Reproducible test / build commands

```bash
export JAVA_HOME="$(/usr/libexec/java_home -v 17)"
export ANDROID_HOME="$HOME/Library/Android/sdk"
python3 -m unittest discover -s tests -p 'test_native_v3_fixture*.py' -v
bash scripts/check-native-v3-fixtures.sh
# Four AVDs below are exclusively owned by this V3 development session:
bash scripts/check-native-v3-fixtures.sh --matrix
```

Offline RED → GREEN was exercised for missing document bytes, broken persistent
UI button, pre-cancelled read, mutable synthetic observer, and malicious
counter/signer/XML parser values. Lint and Gradle locked/checksummed
dependencies are mandatory gates. Instrumentation runs **9/9 per API**, for
36 on-device test executions across the four-version matrix.

| API | Owned emulator | On-device fixture tests | External independent oracles |
| --- | --- | --- | --- |
| 30 | `emulator-5564` | 9/9 PASS | PNG pixels, touch→counter, restart, SAF refusal |
| 33 | `emulator-5566` | 9/9 PASS | PNG pixels, touch→counter, restart, SAF refusal |
| 34 | `emulator-5568` | 9/9 PASS | PNG pixels, touch→counter, restart, SAF refusal |
| 36 | `emulator-5562` | 9/9 PASS | PNG pixels, touch→counter, restart, SAF refusal |

Pinned pre-merge debug APK SHA-256 (re-verify after merge; debug signing is
test-only, not production key distribution):

- Fixture: `ab76141ff6f8309b3233f332d7aa32cb526613c76a82051bbd52da216e588561`
- Fixture AndroidJUnitRunner: `f948cf5533251615286ea0a698e6d885183f7bc50e2ac84fb270b727786ec47b`
- Installer target: `167abaf67648b82f27301cba4d29e50404aeac029af57f84cf05e096d6b6676b`
- Debug test-lab cert SHA-256:
  `165592c3901ae460b8acc387931e0353590634a9ccadc96fbede46b04cab243e`
- Fixture known document bytes SHA-256:
  `4ea8428c4dc75484e22c5832e3a564e1cc1c278cb4b1cb4fe87a3ac40d758fcf`

Local raw per-AVD receipts are under gitignored `artifacts/v3-e01/`, with
emulator boot identities, installed/test SHA hashes, signer identity, OS
denial, independent pixel screenshots, before/after touch counters,
and surviving process restart counter.

## Mandatory remaining product work / actionable gaps

- **E01.c:** genuine user-visible Android permission picker grants,
  cancellation, refusal, revocation and across-process recovery; current
  tests prove unauthorized *direct* reads deny, not authorized SAF data flows.
- **E01.d/E02:** authenticated real Native MCP client transport and rights,
  independent Host operator signing, pair/revoke/replay control.
- **E01.f:** full CI-integrated Android behavior matrix, independent
  security/approval and ChatGPT ordinary Chat connector where supported.
- **E02–E15:** production Tool handlers must call real Android APIs under
  actual OS authorization; no E01 fixture result credits N01–N20.
- Original full V3 work-package JSON and delivery summary are still unavailable
  from the user's raw ZIP. A derived 70-package index is labeled as such.

Rollback: revert this fixture-only PR or disable `enableV3Fixtures`; no
production Native runtime manifest or Host API is modified.
