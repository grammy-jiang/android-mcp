# Android Native MCP — V3 End-to-End Product and Security Architecture

**Prepared:** 2026-10-14, Sydney, Australia
**Purpose:** Correct the earlier roadmap's acceptance failure: *38 merged safe/plan-only slices* did not deliver a usable Native Android controller.
**Status:** DESIGN / PROPOSED; no implementation or device/permission changes are implied by this document.
**Repository:** [grammy-jiang/android-mcp](https://github.com/grammy-jiang/android-mcp)
**Audited Native code baseline:** `184f8c4afcffd4d49e393e14c6c08ca4ec8cb175`
**Remote `main` at the latest read-only recheck:** `e2d95a541d604e7652b5104f24a003f79e99986a`; the intervening compared changes were in the Host stream, not Native Android source. The implementing session **must re-fetch and re-audit** before starting and after any concurrent merge.

## 1. Product outcome and non-negotiable interpretation

The product is two complementary MCP runtimes: a macOS/Linux Host that owns Android build/ADB/emulator/diagnostics and an Android Kotlin Native application that handles actual permission-scoped, user-consented Android app APIs. The Native product must return **real outcomes from a real Android process**, not merely an in-memory simulation or a Host ADB command masquerading as a Native operation.

For every ordinary Android-app capability that is technically permitted and included in the product scope, `FUNCTION_DONE` means all of the following **simultaneously**:

1. A supported, versioned Tool is discoverable under the correct *authenticated, authorized* MCP session and call arguments validate against the exact declared schema.
2. The Tool reaches **a live Kotlin component inside the installed Native APK**, not a fake in a JVM test or a permanently denying boundary.
3. It either invokes the permitted Android framework API and observes a real success, or rejects a real unapproved operation with the correct reason; a **positive, approved success** is required for any supported product feature.
4. The system's state/effect is independently checked by a separate device-side fixture, AndroidJUnitRunner callback, OS PackageManager/Activity/dumpsys oracle, verifiable media bytes/hash, or similar appropriate observer. An ADB-issued gesture or install *instead of* the Native executor is **not** a positive Native feature test.
5. Actual OS consent (where required), refusal, revocation, Stop, concurrent requests, crash/restart and uncertainty/replay paths have test results on each applicable QEMU Android API 30, 33, 34 and 36; exceptions require a documented platform fact, not a guessed skip.
6. The production capability is truly wired and permitted under its reviewed profile. A debug-fixture-only success is recorded **as emulator-debug evidence**, never automatically promoted to an ordinary user production capability.
7. The required independent privilege/security approval and physically scoped owner authorization (where applicable) have actually been provided; no developer can certify their own independent security review.
8. Exact commit/tree, built APK and fixture hashes, emitted Tool responses, OS-side evidence and clean teardown are retained. Merge and local CI alone are never a product feature certificate.

**No downgrade rule:** `PASS_JVM`, `PASS_MOCK`, `PASS_ADB_HARNESS`, `APP_BUILD_GREEN`, `INERT_MERGED`, `PLAN_ONLY`, `DENIED_AS_DESIGNED`, `BLOCKED`, and `UNSUPPORTED` never imply `FUNCTION_DONE`. A PR may merge as a verified engineering increment while the owning feature remains `NOT_DONE` with a required follow-up task. No work package or capability disappears from the ledger.

## 2. What exists today; do not reinvent the working pieces

- Kotlin SDK 0.14.0 with Ktor 3.4.3, Android API `minSdk=30`, `targetSdk=36`, JDK 17 and Android Gradle Plugin 9.4.0.
- A local loopback `127.0.0.1:38765/mcp` with **only** public `device_status` Tool, backed by user-started Activity and (on supported APIs) visible foreground service. App stops/notifications/lifecycle have genuine emulator regression evidence.
- App manifest only INTERNET, FOREGROUND_SERVICE, FOREGROUND_SERVICE_SPECIAL_USE and POST_NOTIFICATIONS. No active AccessibilityService, MediaProjection FGS type, admin receiver or installer permission. Android app has no existing `src/androidTest` or runner.
- Multiple real Android SDK *reader classes* and many `Android*Boundary` classes that cannot be reached from normal Gateway/Activity/Service execution paths. Some are fully synthetic and hard-return deny/blocked; do not count them as API implementations.
- Reusable private artifact stores, fencing/identity, state-machine code and negative security tests. Treat as building blocks to integrate and challenge, not blindly reuse as production grant verifiers.
- Verified QEMU ARM64 API30/33/34/36 on MacBook with existing Native debug APK; original default matrix covers status/Activity/FGS, and separately N4.b performed **real ADB/UIAutomator input to the app under test**, not Native Accessibility-based input.
- Host is a separate active writer. Some recent Host H3.x features are synthetic-only (including debug deployment/screenshot planning); their existence does not prove a usable Host test orchestrator or real Host↔Native authorization.

Baseline assurance is **not** complete Android functionality; the previous 38 PR receipts remain historical safe-foundation evidence and must not be rewritten to claim E2E success.

## 3. Release profiles and scope boundary

| Profile | Purpose | Success condition | Must NOT be claimed |
| --- | --- | --- | --- |
| `native-status` | Minimal own-app and service status for unpaired local user | Current genuine loopback/FGS OS smoke | Caller authentication, third-party app control or privacy reads |
| `native-paired-read` | Allowed OS/build/ABI/permission/package/own health observations | Authenticated real tools/list/call, actual Android API and privacy enforcement | User-granted unrestricted device info or global Logcat |
| `native-user-consented` | SAF, capture, recording and other user-mediated API sessions | Local Activity UI, authentic Android grant/callback, independent oracle, paired caller | Persistent blanket user permission or covert/unattended capture |
| `native-approved-control` | Explicit allowlisted app launch, approved UI gesture and installation | Real scoped per-action approval + durable native fencing + OS effect E2E + security review | Arbitrary shell, off-screen userless gestures, unapproved cross-app actions |
| `test-disposable-avd` | Instrumented fixture and deliberate consent-flow tests | HMAC-owned/verified *exclusive disposable* AVD and pinned fixtures; real OS test E2E | Production grant/security review equivalence |
| `managed-enterprise-lab` | Test DPC / Device Owner only on a **fresh separate account-free disposable AVD** | Actual DevicePolicyManager owner check and carefully reversible policy probe | Ordinary Native APK receiving Device Owner or physical device admin takeover |
| `host-maintenance` | Authorized independent Host diagnostics for off-line Native/boot states | Host read-only ADB/Fastboot mode/identity probes and manual owner-controlled runbooks | Root/ROM/bootloader control as an ordinary Native Tool |

At the beginning of implementation, create a signed-off **capability product roster** for N01–N20: required core, opt-in feature, managed extension, or structurally impossible in a regular APK with approved Host fallback. *Only* a documented, conscious product-scope decision can exclude a family. The developer cannot remove a requested capability by calling it blocked. If unavailable, retain `BLOCKED_EXTERNAL` with a complete outstanding feature backlog and a release-blocking status for the affected profile.

## 4. Target component graph and control boundaries

```text
                                Mac/Linux
                     ┌────────────────────────┐
                     │ Real MCP client/Host   │
                     │ exact Tool + operation │
                     └────────────┬───────────┘
                                  │ authenticated transport
                     ┌────────────▼───────────┐
                     │ Pairing + grant proof  │   <─ operator/user out-of-band
                     │ session replay checks  │      pairing on Android UI
                     └────────────┬───────────┘
                   ADB USB-forwarding / reviewed relay
          transport selection never substitutes for identity
                                  │
          Android                 ▼
                     ┌──────────────────────────────┐
                     │ NativeMcpGateway + registry  │
                     │  status-only before pairing  │
                     └──────────────┬───────────────┘
                                    │ session / Tool / action guards
                     ┌──────────────▼───────────────┐
                     │ Authorization + profile     │
                     │ OS permission fresh check   │
                     │ signed exact-action grant   │
                     │ durable lease/fence/audit   │
                     └──────┬─────────────┬─────────┘
                            │             │
                ┌───────────▼────┐  ┌────▼──────────────────┐
                │ Read providers │  │ User-consent Activity │
                │ OS/Build/batt  │  │ picker / Projection  │
                │ packages/own  │  │ Accessibility Settings│
                └───────────┬────┘  └────┬──────────────────┘
                            │            │ OS callback/checked grant
                     ┌──────▼────────────▼───────┐
                     │ Real Android executors   │
                     │ SAF/VirtualDisplay/UI    │
                     │ explicit Intent/Installer│
                     └──────────┬───────────────┘
                                │ bounded typed receipts/artifacts
                     ┌──────────▼───────────────┐
                     │ Persistent journal /    │
                     │ app-private artifacts   │
                     │ cleanup / retention     │
                     └──────────────────────────┘

    Separate AndroidJUnitRunner + fixture app + UIAutomator + OS dumpsys
    verifies the actual Android state; it does not perform the Native
    operation being tested on behalf of the Native application.
```

### 4.1 Real Gateway and Tool registration

Keep the existing `device_status` wire/schema compatible. Add a reviewed Native Tool registry with startup and session-aware exposure (or per-call guards if Kotlin SDK session-specific `tools/list` cannot be safely implemented). Tool names below are **proposals, not claimed existing production registrations**:

`native_device_profile`, `native_system_snapshot`, `native_permission_status`, `native_package_query`, `native_app_health`, `native_service_diagnostics`, `native_optional_status`, `native_telemetry`, `native_ui_inspect`, `native_ui_action`, `native_capture_screen`, `native_record_screen`, `native_file_exchange`, `native_app_launch`, `native_install_request`, `native_pairing_status`, `native_lease_status`.

For each Tool: exact JSON Schema, `readOnlyHint`/`destructiveHint` truth, audience/profile, Android permission, per-app data scope, output size, error codes, request/operation IDs, timeout semantics, tested dynamic visibility and a rollback feature flag. `tools/list` must not advertise enabled sensitive functionality before authenticated policy is satisfied; even if it lists a disabled descriptor, `tools/call` must independently enforce authorization. The correct public registry must be proven using the **real deployed Kotlin MCP HTTP server**, not the stand-alone JVM prototype.

### 4.1.1 Intended ChatGPT/client access path — validate before feature implementation

The user's actual consumer may be ChatGPT ordinary Chat through an explicitly installed/connected authorized MCP/plugin workflow. **The Android emulator's `127.0.0.1` cannot be presumed reachable by ChatGPT servers.** At G05 test a real target Chat-mode connected path (either a supported securely authenticated Host relay/provider or another explicitly approved connector topology): live tool discovery, one status call, one unauthorized call, reconnect and revocation. A standalone Python MCP SDK connection is necessary engineering evidence but does **not** prove the user's actual ChatGPT interface can reach it. If product UI/connectors are unavailable or require the user's explicit connection, label the required end-user integration `BLOCKED_EXTERNAL` immediately, keep working on independent emulator E2E, and do not mark overall product Done. Never expose a raw public Native loopback socket just to satisfy a connection test.

### 4.2 Trusted communication and identity — security blocker critical path

1. The Android app has a private per-install Keystore identity and a user-visible pairing panel displaying the correct short fingerprint. The Host has a separately pinned signing identity; no Android serial, Host name, forwarded TCP port or model-supplied `approved=true` is authority.
2. Pairing uses a real *user-triggered* bootstrap bound to the exact Host public key, Native installation ID, test device and session epoch, then mutual fresh challenge/response with strict replay/clock limits. Host↔Native uses an authenticated **confidential** channel. The implementation team must choose a mature, reviewed TLS 1.3 mutual-authentication solution or equivalent vetted library through a compatibility POC; **do not invent custom cryptography** or assume that plain USB/ADB forwarding provides app-level authentication. ADB forward can be routing only.
3. Privileges are scoped to a trusted session (`status`, `read`, `user_consented`, `approved_control`) and per-action grants bound to exact target, input digest, expiry, consent event, Host identity, Native identity and boot epoch. Ordinary read-only Tools can be enabled once the real authenticated-read path is proven, without waiting for privileged control rollout.
4. Localhost requests from another Android app are hostile until authenticated. Browser Origins, forwarding, duplicate headers and localhost loopback are not proof of trusted caller. Avoid replayable bearer secrets in Android logs/UI/MCP responses.
5. Host and Native revocation, key rotation, reinstall, service restart, app update and reboot invalidate correct credentials; blocked client errors never expose identity secrets.
6. A shared `contracts/v2` PR is built and tested by both dedicated Host and Native writers. Protocol and transport POC failures create first-class blockers and new tasks; no fake signed model is silently promoted.

### 4.3 Lease/fencing/uncertain side effect — no dual writer

A single Native authoritative per-device/per-user action arbiter coordinates all Native UI/installer/app-launch effects with multiple independent Host processes. Host durable SQLite job state is not itself an Android Native lease. State progression includes `UNPAIRED → PAIRED → IDLE → HELD → RELEASING → IDLE`, with `EXPIRED/STOPPED/UNCERTAIN` recovery paths. Persist monotonically increasing native fence, operation digest, owner and boot epoch; validate immediately before effect, not only when planning. Ensure no two producers can run the same fixture mutation at the same time. For an effect that may have happened before an ACK or crash, return `UNCERTAIN`, reconcile via independent oracle, **never blind retry**.

Operations remain non-idempotent unless proved otherwise. User Stop/unpair/permission revocation releases OS resources and prohibits new commits; it cannot falsely claim that an already dispatched irreversible OS operation was rolled back. Installer/SAF provider commits can be only partially reversible; receipts must tell the truth.

### 4.4 Android permission and consent broker

The Android app (not the MCP caller and not the test harness masquerading as it) starts permitted ActivityResult flows. Consent and foreground/UI state must be verified fresh for each operation. OS permission ≠ pairing; pairing ≠ user approval; and neither grants Device Owner/Root.

- **MediaProjection:** use actual `createScreenCaptureIntent()` Activity result, proper Android 14+ `FOREGROUND_SERVICE_MEDIA_PROJECTION` and `mediaProjection` FGS type, `MediaProjection.Callback.onStop`, one grant/session and one VirtualDisplay creation as platform requires. Do not reuse a projection token for new capture or recording session. A noninteractive OS prompt cannot be assumed accepted. Track capture/recording artifact owner, stop, surface, memory and retention.
- **AccessibilityService:** declare purpose-specific `<service>` + `BIND_ACCESSIBILITY_SERVICE` and `canPerformGestures` only in a separately reviewed profile. The operator explicitly enables it in Android Settings; the app only accepts connected callbacks and real window/node state. Limit actual gestures to explicit approved targets, starting with own fixture. Reject secure/password windows, stale trees, lockscreen, background/origin mismatch, invalid coordinates. Assess Android/Play accessibility policies separately before any general third-party app automation claim.
- **SAF:** use real `ACTION_OPEN_DOCUMENT` / `ACTION_CREATE_DOCUMENT` and OS-delivered URI grants. Validate actual read/write flags and provider; use bounded `ContentResolver` I/O, hash and app-private staging. A provider write is **not inherently atomic**; after timeout/crash report partial/uncertain and reconcile. `CREATE_DOCUMENT` may create a new numbered filename instead of overwriting; do not claim arbitrary-file writes or unrestricted `/sdcard`.
- **PackageInstaller:** create only a pinned signed fixture APK session on an exclusively owned disposable AVD. Handle `STATUS_PENDING_USER_ACTION`, live OS user approval/refusal and final `PackageManager` oracle. Never use `adb install` as proof of Native install. API-specific `REQUEST_INSTALL_PACKAGES`/unknown sources settings are reviewed as a scoped, permission-declared separate configuration. Do not use silent install/update exemptions. Reboot/timeout/cancel can lead to an unknown outcome; inspect state instead of retrying blindly.
- **Launch/UI:** foreground user action, fixed allowlist and explicit exported fixture component. Respect Android background-activity-start restrictions. Native invokes `startActivity` and tests prove the fixture resumed; direct `adb shell am start` is only setup/independent observation, never the success path for the feature.
- **Device Owner/Root:** no administrative provisioning in ordinary production flavor. Test DPC may be used on a **new disposable account-free AVD** with explicit test ownership. Native Root/Bootloader/ROM remains platform-unsupported; a separately approved Host maintenance profile supplies read-only detection/manual diagnostics, not an unsupervised flash/erase executor.

### 4.5 Artifacts and diagnostic handling

All APKs, screenshots, recordings, SAF files, crash traces, installer sessions, pairing diagnostics and operation receipts have app-private owner, exact content hash, MIME/size/retention and bounded access. No raw arbitrary private device file path or credential is accepted as a model argument. Store encrypted where sensitive; delete on user Stop/TTL where appropriate. Avoid exposing binary media in unbounded JSON; MCP returns opaque authorized artifact handles and the client retrieves bounded verified bytes. Per-session replay log, audit and cleanup must survive process death only as appropriate; credential/token grants do not silently resurrect.

### 4.6 Service state and background execution

Keep real N2 Activity and N3 user-started notification/FGS guarantees. Add capture-specific service type rather than mislabeling all use as `specialUse`. Background action and permission restrictions are per API and respected. No boot receiver automatic resurrection or invisible model-initiated FGS start. User Stop also cancels sensitive operations, wipes effective session grants and informs the Host. Reboot/force-stop/user permission revocation tests are QEMU-only on exclusively owned test devices; do not operate a physical tablet.

## 5. Test environment architecture and AVD isolation

Current tested QEMU resources: API 30 (`emulator-5560`), API 33 (`emulator-5558`), API 34 (`emulator-5556`), API 36 (`emulator-5554`), all ARM64 Mac. These are a **baseline observation, not a permanent reservation**; Host development may own them. Require an exclusive AVD lease and preflight all test target serials and QEMU/API/ABI/boot identity. A runner must refuse any device whose identity or ownership cannot be established. Do not reset, wipe, run Device Owner tests, install uncontrolled apps or change global permissions on another session's AVD.

Add dedicated `src/androidTest` AndroidJUnitRunner device-side tests, built and installed with a debug test APK. Add separately signed own fixture APK(s): deterministic UI controls/counters, secure/password window, SAF content provider with injected failures, media test pattern, package-install target, separate unpaired-client/Host identities, and only opt-in dedicated Device Owner lab AVD. Test Orchestrator can isolate destructive fixture state where compatible; account for cases where clearing app data would break consent flows. Keep system UI interactions under test automation visible and logged as simulated test-user gestures, never fabricated OS grants. UIAutomator can tap Android dialog prompts on disposable emulators, but the actual feature must run **inside the Native APK**. Runtime logs must prove framework callbacks; independent OS/fixture state proves effects.

### Test evidence grades — no equivalence by naming

| Grade | What ran | What it proves | Can close a real feature? |
| --- | --- | --- | --- |
| `STATIC` | lint, manifest, source search, schema, secret checks | Source/packaging policy | No |
| `UNIT` | JVM/Python state models and negative rules | Deterministic logic | No |
| `JVM_WIRE` | Stand-alone Kotlin server ↔ Python SDK | Wire contract for a prototype | No |
| `EMULATOR_ADB_HARNESS` | ADB/UIAutomator operates fixture | Environment/harness/OS input | No for Native executor |
| `ANDROID_INSTRUMENTATION` | JUnit on real installed Android API calls | Android framework behavior | Necessary, not sufficient |
| `NATIVE_MCP_E2E` | Paired live client → Native Tool → real Android API → separate oracle | Full Native feature path | Yes with negatives, API matrix and policy gates |
| `HOST_NATIVE_E2E` | Two real Host processes + Android Native coordination → effect | Real distributed authorization/lease | Required for coordinated writes |
| `AUTHORIZED_PHYSICAL` | Separately approved physical device & actual owner consent | Hardware/OEM compatibility | Required only for expressly approved physical release |

### Outcome codes

`NOT_RUN`, `RUNNING`, `PASS_REAL_E2E`, `FAIL_REAL_E2E`, `BLOCKED_EXTERNAL`, `UNSUPPORTED_BY_PLATFORM_WITH_EVIDENCE`, `PASS_SYNTHETIC`, `PASS_ADB_HARNESS`, `UNCERTAIN`, `DEFERRED_NOT_DONE`. All V3 tests begin as `NOT_RUN`. A product release is not done while an in-scope item remains failed/uncertain/blocked/not-run. Never coerce `UNSUPPORTED` to a test pass without the approved product exception and actual fallback evidence.

### Acceptance artifact (required per case)

```json
{
  "case_id": "V3-N09-02",
  "result": "NOT_RUN",
  "git_head_sha": "<exact at execution>",
  "git_tree_sha": "<exact at execution>",
  "apk_sha256": "<exact at execution>",
  "fixture_apk_sha256": "<exact at execution>",
  "android_api": 34,
  "avd_serial_and_proven_identity": "<exact at execution>",
  "client_auth_profile": "<verified role and grant>",
  "android_consent": "<real OS callback/UI event, when applicable>",
  "native_tool_wire_result": "<redacted path to bounded result>",
  "android_framework_call_trace": "<real API and callback evidence>",
  "independent_oracle": "<fixture or OS state proof>",
  "negative_and_recovery_evidence": "<linked run IDs>",
  "cleanup_verified": false,
  "open_gap_ids": [],
  "review_class": "self_review_or_independent_review_pending"
}
```

The schema is illustrative; implementation must produce a validated versioned machine-readable result, avoid logging secrets, sign/hash provenance as appropriate and distinguish invalid evidence from valid passed tests. A `NOT_RUN` example is **not** a claimed execution receipt.

## 6. Continuous completion algorithm — the missing invariant from V1/V2

At *every* PR, task, and milestone, the agent must perform the **Capability Closure Review**:

1. List which N01–N20 requirements were targeted, which runtime Kotlin adapters they should traverse, and which actual public Tools are callable.
2. Diff current source against the target live call graph: no orphan provider, no permanent DENIED stub for a feature scheduled as runnable, and no new permission or sensitive Tool without reviewed auth/consent.
3. Run targeted `UNIT`, `JVM_WIRE`, actual `ANDROID_INSTRUMENTATION` and `NATIVE_MCP_E2E`; for shared writes also real `HOST_NATIVE_E2E`, including positive and negative scenarios.
4. For each applicable API 30/33/34/36, find the independent OS success oracle; flag an ADB substitute/missing consent/API mismatch as **not done**.
5. Reconcile all original `T-Nxx-01..06` tests, the V3 Nxx matrix and project requirements. A green source-name test cannot fulfill an unexecuted OS-case requirement.
6. Review failure modes that became visible: actual OS permission decline, failed stream/half-install, process crash, foreground loss, concurrency, replay, timeout, secure UI/data scope, cleanup and session release.
7. **Ask explicitly:** “Which requested behavior cannot the user actually invoke from a real MCP client now?” “What real Android API effect has not been proved?” “Which new gap appeared while integrating?” “Has a stub remained in a live feature path?” “Have we added a real feature without real denial/recovery tests?”
8. For each missing behavior **create a new required gap ticket immediately** (`GAP-Nxx-###`), including failure reproduction, risk, dependency, owner, expected executable output, positive/negative/SDK test IDs, target implementation work package, acceptance evidence and why release remains blocked. Insert a new work package ahead of the appropriate dependent stage; do not wait for a postmortem and do not silently reduce scope.
9. Merge an honest incremental PR only after *its explicitly scoped tests* pass, but never mark the owner feature as `FUNCTION_DONE` until complete E2E evidence. Continue into the added gap task where dependencies allow. External authorization absent → `BLOCKED_EXTERNAL`, keep the blocker open, continue independent tasks.
10. At every wave/release compare the original product scope to V3; if even one in-scope real feature is unverified, the honest final status is `PRODUCT_INCOMPLETE` regardless of green unit tests, number of PRs or simulated cases.

**Invariant:** `FEATURE_DONE => REAL_POSITIVE_OS_EFFECT + MCP_E2E + NEGATIVE_CASES + RECOVERY_CASES + SDK_MATRIX + APPROVED_SECURITY_SCOPE + EXACT_PROVENANCE`. This implication must be enforced by an automated gate, not merely stated in prose.

## 7. Security and client release gates

- **S0:** locally tested status-only legacy compatibility and privacy.
- **S1:** mutually authenticated read-only sessions with 2-Host / same-device hostile peer tests.
- **S2:** actual Android consented read flows (SAF/capture/Accessibility observation) on disposable AVDs; debug-only approval; separate privacy/retention review.
- **S3:** signed per-action scoped write approvals + durable lease + independent security review + complete real emulator positive/negative/uncertain flows; only approved product scopes may enable Control profile.
- **S4:** release candidate full four-API E2E matrix, migration/cancellation/teardown, permissions and exported components, client UX, no high-priority open gaps.
- **S5:** explicitly approved physical-device compatibility tests, if requested and authorized. No implicit OnePlus Pad 3 install, permission change, Root, reboot, provisioning or flash.

A safe read-only emulator PR may merge at S1 without waiting for production Control S3. This is how the workflow remains productive while preserving product truth. **Do not equate absent independent review with permission to fabricate a review; do not equate it with a reason to mark the Control feature completed.**

## 8. Open design decisions to resolve in specific implementation POCs

| Decision / uncertainty | Evidence-producing task | Safe resolution rule |
| --- | --- | --- |
| Kotlin SDK session-specific Tool visibility | G05/G08 real tools/list POC | If not supportable, enforce per-call deny and segregate authorized profiles; do not expose callable sensitive Tool unauthenticated |
| TLS 1.3 mTLS / secure USB bridge viability | G05–G07 Host↔Native round-trip POC | Use vetted TLS/crypto library; fail closed; add follow-up if incompatible |
| Accessibility policy/permitted target scope | G18–G19 and G23 Android service/gesture POC and independent review | Keep test restricted to owned fixture; production unattended generic automation cannot be assumed permitted |
| Android MediaProjection FGS type on each API | G15–G17 actual OS consent tests | Follow official platform type and single-session restrictions; unknown device behavior is a blocker |
| Installer app-source permission, OS verifier, SDK differences | G25–G27 actual PackageInstaller test | Use pinned signed fixture + actual pending-user UI; never silent exemption |
| File-provider partial writes | G13–G14 faulted document provider | Return PARTIAL/UNCERTAIN, not a fictional atomic write guarantee |
| Main Host ownership / shared contract changes | G05–G09 three-PR contract train | One named writer per path, compatible v2 schema, both consumer tests |
| Device Owner and OEM support | G30 dedicated managed AVD; G31 Host-only mode probe | Enterprise lab separate, Root Native unsupported with real Host diagnostic fallback |
| End-user ChatGPT MCP access | **G05 initial feasibility and G33 final complete consumer test** | Validate early actual transport/plugin/tool discovery in the intended Chat surface; if external app connection is unavailable record an immediate blocker rather than discovering it at release |

## 9. Official platform references and source anchors

- [Android instrumentation](https://developer.android.com/training/testing/instrumented-tests), [AndroidJUnitRunner](https://developer.android.com/training/testing/instrumented-tests/androidx-test-libraries/runner), [UIAutomator](https://developer.android.com/training/testing/other-components/ui-automator)
- [MediaProjection](https://developer.android.com/media/grow/media-projection), [Android 14 projection session rules](https://developer.android.com/about/versions/14/behavior-changes-14), [Foreground service types](https://developer.android.com/develop/background-work/services/fgs/service-types)
- [AccessibilityService and dispatchGesture](https://developer.android.com/reference/android/accessibilityservice/AccessibilityService)
- [Storage Access Framework](https://developer.android.com/training/data-storage/shared/documents-files)
- [PackageInstaller](https://developer.android.com/reference/android/content/pm/PackageInstaller), [Installer Session](https://developer.android.com/reference/android/content/pm/PackageInstaller.Session), [SessionParams](https://developer.android.com/reference/android/content/pm/PackageInstaller.SessionParams)
- [Package visibility restrictions](https://developer.android.com/training/package-visibility/declaring), [Background activity launch](https://developer.android.com/guide/components/activities/secure-bal)
- [Android Enterprise/Test DPC](https://developer.android.com/work/guide.html)
- Existing repo: `docs/android-host-native-full-lifecycle-design-20261012.md`, `docs/native-mcp-implementation-plan-20261013.md`, `docs/native-mcp-serial-test-cases-20261013.md`, `docs/host-native-coordination.md`, `docs/native-capability-ledger.v1.json` and current Kotlin Gateway/Manifest.

**This is a corrective design. Actual positive consented Android execution, independent security approval and cross-runtime transport are **not** certified by writing it.**
