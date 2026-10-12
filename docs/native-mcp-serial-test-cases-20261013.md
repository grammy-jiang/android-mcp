# Native MCP v2: six explicit test cases per serial work package

**Status:** proposed test specifications, NOT implemented or already
passing tests. **Target:** Native Kotlin/Android modules in
`grammy-jiang/android-mcp`, based on the
[38-package Native v2 plan](native-mcp-implementation-plan-20261013.md).
Exactly **38 packages x 6 cases = 228 new/updated behavioral tests**.
Do not represent this as 228 already executed tests.

Case IDs `T-N0A-01` through `T-N8B-06` are required PR trace
markers; create actual corresponding Kotlin JUnit/instrumentation
or Python guard test functions under the **Native-owned**
`android/**` files. Add smaller supplemental cases whenever a
platform-specific failure is discovered rather than weakening
a listed case. Existing tests and strict source/permission policies
remain in force.

## Every Native PR: common cross-cutting checks

| ID | Required verification | Proof / failure policy |
| --- | --- | --- |
| QN-01 | Pure Kotlin unit/JVM lifecycle/protocol tests, stable codec and error contract | `bash scripts/check-native.sh`, recorded commands/exit status |
| QN-02 | Actual JVM Kotlin MCP <-> Python client Streamable HTTP and metadata | `tools/list`, `tools/call`, schema/output/denial and unexpected exceptions |
| QN-03 | Real SDK 36 debug APK, dependency verification/lock, Android Lint, APK signing | `bash scripts/check-native-apk.sh`, Manifest permission diff reviewed |
| QN-04 | Local combined repository security/quality gate | `bash scripts/check-native-local-ci.sh`, no paid/unstarted GitHub Actions passes |
| QN-05 | Android emulator behavior for lifecycle/permission/API-specific changes | Exact preverified QEMU API30,33,34,36, real notification/UI/consent actions; physical serial preflight rejection |
| QN-06 | Android sensitivity/authorization | No secret/device ID leakage; no untrusted app calling sensitive Tool; permissions deny until actually granted |
| QN-07 | Concurrency/lifecycle | Process kill, FGS stop, locked/unlocked screen, Activity/FGS conflict, timeout/reconnect/restart where applicable |
| QN-08 | One-PR-at-a-time, test-first and integration | Meaningful red phase, full relevant green gate, self-review labelled, exact SHA main merge and post-merge tree equality |

The existing four API emulator matrix is **only** passed when
actual disposable AVDs and exact typed API levels were verified
before installation. If emulator execution is blocked, mark
`not_run`/`blocked` and keep affected sensitive/execution
capability disabled. A passing test in a JVM fake cannot be
substituted for permission consent or an actual Android screen.

## N0 — baseline, local caller security, foreground lifecycle and artifacts

### N0.a — suggested `android/tests/test_native_status_golden.py`

- **T-N0A-01:** existing `device_status` Tools/list has the same single Tool, no hidden sensitive Tools/Resources, and exact v1 status fields.
- **T-N0A-02:** Kotlin NativeLocalStatus JSON has runtime `android`, schema version 1, zero device IDs and false Accessibility/privileged flags.
- **T-N0A-03:** official Kotlin SDK over loopback responds to a valid Tool call with expected result and bounded response; unknown Tool is denied.
- **T-N0A-04:** N2 Activity only serves while explicitly started; Home/onStop releases its own endpoint and does not start N3.
- **T-N0A-05:** N3 foreground mode survives Home with correct notification, then actual UI/notification Stop removes listener and service.
- **T-N0A-06:** mutate an isolated golden fixture field to prove regression detection, restore it, and show no physical Android device command.

### N0.b — suggested `android/tests/test_native_local_caller_guard.py`

- **T-N0B-01:** a fake approved local caller using correct Origin/Host/context is recognized under the planned policy, without exposing new sensitive Tools.
- **T-N0B-02:** localhost connection by another process/app with no authenticated identity cannot list/call future sensitive Tools.
- **T-N0B-03:** wrong/missing Origin, attacker-controlled Host, unexpected path and preflight spoof are rejected before sensitive handlers.
- **T-N0B-04:** replayed request, cross-origin preflight, malformed headers, giant body and connection flood have bounded/typed denials.
- **T-N0B-05:** a process restart/second listener cannot inherit stale caller authorization; identity is not inferred from loopback IP.
- **T-N0B-06:** exact baseline status still works under reviewed compatibility policy; no unreviewed public bind or private key leaks.

### N0.c — suggested `android/native-lifecycle/src/test/kotlin/org/androidmcp/lifecycle/NativeServiceLifecycleTest.kt`

- **T-N0C-01:** Activity start/stop and N3 opt-in FGS start/stop follow distinct explicit state transitions with a single port owner.
- **T-N0C-02:** second Activity or FGS listener fails closed while the first owns the endpoint, with truthful user-facing error.
- **T-N0C-03:** Ktor shutdown exception plus still-bound socket leaves port-owner state UNKNOWN and blocks a second startup.
- **T-N0C-04:** port closure/readiness marker mismatch or timeout never releases ownership or falsely reports service healthy.
- **T-N0C-05:** Android API30/33/34/36 emulator Home, orientation, notification denial, actual Stop and process death never auto-resurrect.
- **T-N0C-06:** Activity/FGS contention, rapid Stop/Start and retry produce at most one listener, no orphan notification/port.

### N0.d — suggested `android/native-protocol/src/test/kotlin/org/androidmcp/protocol/NativePermissionStateTest.kt`

- **T-N0D-01:** known Android API+permission tuples map to explicit granted/denied/unknown/not-applicable states without inventing a grant.
- **T-N0D-02:** no Accessibility, MediaProjection, QUERY_ALL_PACKAGES, device admin, Root or storage permission appears in current actual manifest.
- **T-N0D-03:** Android 11 lacks Android 13 runtime notification grant semantics while API33+ refusal prevents current FGS start.
- **T-N0D-04:** user revokes notification/app permission while service runs; readiness updates and sensitive operations deny after recheck.
- **T-N0D-05:** missing Android system service/API or OEM exception returns unsupported/unknown with no permission prompt loop.
- **T-N0D-06:** native permission-status output discloses no secrets, private settings or full package list and is versioned.

### N0.e — suggested `android/native-lifecycle/src/test/kotlin/org/androidmcp/lifecycle/NativeArtifactStoreTest.kt`

- **T-N0E-01:** an app-owned synthetic binary becomes an opaque handle with MIME, size, SHA-256 and bounded expiry.
- **T-N0E-02:** a guessed handle, caller-forged URI, symlink/path traversal or another-app private file is denied.
- **T-N0E-03:** oversized artifact/disk-full/private-directory permission error leaves no trusted partial file or sensitive log.
- **T-N0E-04:** concurrent duplicate IDs and crash during atomic commit cannot overwrite another artifact or publish partial content.
- **T-N0E-05:** FGS Stop/process restart/expiry destroys or reconciles artifacts according to explicit retention; no orphan.
- **T-N0E-06:** raw screenshots, tokens, account data and capture frames never appear in MCP JSON, normal logcat or audit.

## N1 — safe Android system and self-service observability

### N1.a — suggested `android/app/src/test/java/org/androidmcp/nativeapp/NativeBuildSnapshotTest.kt`

- **T-N1A-01:** representative Build.VERSION/SDK/ABI/app Build values normalize to a versioned typed snapshot.
- **T-N1A-02:** hardware/device serial, advertising ID, Android ID, network MAC and other persistent IDs are absent.
- **T-N1A-03:** missing/unexpected OEM Build fields or unusual ABI lists return partial/unavailable, not invented defaults.
- **T-N1A-04:** API30/33/34/36 snapshot adapter respects actual API availability and supported type/units.
- **T-N1A-05:** malformed Kotlin codec, oversized model/version string and unsupported UTF-8 are bounded/redacted.
- **T-N1A-06:** public sensitive profile stays denied without N0.b gate, even if a synthetic service can read Build locally.

### N1.b — suggested `android/app/src/test/java/org/androidmcp/nativeapp/NativeSystemSnapshotTest.kt`

- **T-N1B-01:** fake BatteryManager, storage free bytes, display metrics and connectivity report consistent units/timestamps.
- **T-N1B-02:** permission-denied network/location data, offline connectivity and missing service return explicit partial/unavailable.
- **T-N1B-03:** very large/negative battery/storage counters and OEM missing fields never overflow or become plausible readings.
- **T-N1B-04:** Android API30/33/34/36 tests check the correct availability of display/storage/network APIs without using privileged stats.
- **T-N1B-05:** event/refresh on FGS Stop does not retain old device state or start background subscriptions automatically.
- **T-N1B-06:** MCP denied/safe responses omit SSIDs, nearby device IDs, precise location and other unrelated sensitive state.

### N1.c — suggested `android/app/src/test/java/org/androidmcp/nativeapp/NativeAppHealthTest.kt`

- **T-N1C-01:** running Activity or FGS reports correct application/process service mode, uptime and permitted readiness.
- **T-N1C-02:** process crash/FGS kill, notification Stop and explicit user Stop are distinguished; stopped never reports healthy.
- **T-N1C-03:** failed bind, cancelled start and readiness-oracle collision yield typed error with no second port owner.
- **T-N1C-04:** retry after process death/Android reboot never automatically starts a background service (START_NOT_STICKY).
- **T-N1C-05:** remote/unpaired clients cannot obtain detailed stacktrace, PID list, private filesystem or app credentials.
- **T-N1C-06:** HTTP Tool call with fake lifecycle states preserves baseline status/v1 errors and bounded JSON.

### N1.d — suggested `android/tests/test_native_tool_profile_contract.py`

- **T-N1D-01:** unauthenticated default tools/list only advertises approved minimal status, with no screenshot/package/UI Tool.
- **T-N1D-02:** a fake authorized capability profile exposes only explicitly allowed focused Tools with correct Kotlin SDK JSON Schemas.
- **T-N1D-03:** unsupported Android API or revoked permission hides/denies Tool independently of model-supplied `approved=true`.
- **T-N1D-04:** caller profile switch, reconnect and process restart cannot reuse stale permission/Origin context.
- **T-N1D-05:** tools/call errors and structuredContent map consistent success/partial/denial; metadata never mislabels mutating actions read-only.
- **T-N1D-06:** baseline three Host Tools are untouched; Native only changes its own registry and v1 compatibility is preserved.

## N2 — PackageManager visibility and bounded app intents

### N2.a — suggested `android/app/src/test/java/org/androidmcp/nativeapp/NativePackageVisibilityTest.kt`

- **T-N2A-01:** known PackageManager visible packages return bounded, sorted permitted subset with explicit filter notes.
- **T-N2A-02:** hidden packages are not silently treated as nonexistent; report visibility restrictions on API30/33/34/36.
- **T-N2A-03:** unexpected broad QUERY_ALL_PACKAGES permission or privileged cross-user enumeration is denied by policy.
- **T-N2A-04:** malformed package metadata, huge app lists and slow PackageManager calls produce bounded partial/error results.
- **T-N2A-05:** unpaired local callers cannot enumerate visible application packages via MCP despite service-local access.
- **T-N2A-06:** package results contain no account tokens/signature private keys or unrelated other-app permissions.

### N2.b — suggested `android/app/src/test/java/org/androidmcp/nativeapp/NativePackageQueryTest.kt`

- **T-N2B-01:** explicit visible package ID resolves versionName/versionCode, certificate digest and exported metadata allowed by API.
- **T-N2B-02:** unknown, hidden, disabled, uninstalled and wrong-user packages yield distinct typed not-found/visibility errors.
- **T-N2B-03:** invalid package names, control characters, huge labels and model-provided filesystem paths denied.
- **T-N2B-04:** API30/33/34/36 PackageManager field behavior checked without broad visibility/hidden-API bypass.
- **T-N2B-05:** request after package uninstall/disable or lost caller grant is revalidated, no stale cached elevation.
- **T-N2B-06:** tools/call output versioned, capped and protected from unauthorized local/remote origins.

### N2.c — suggested `android/app/src/test/java/org/androidmcp/nativeapp/NativeIntentPlanTest.kt`

- **T-N2C-01:** allowlisted explicit app/activity Intent resolves a visible/exported target to a deterministic launch **plan**.
- **T-N2C-02:** implicit/broadcast/deep-link unknown Intent, nonexported component and wrong user are denied before launch.
- **T-N2C-03:** arbitrary extras/URI tricks, oversized payload, intent flags/selector escalation and shell text are rejected.
- **T-N2C-04:** foreground/background launch restrictions and API30/33/34/36 support accurately reported.
- **T-N2C-05:** duplicate plan is idempotent, but actual launch still requires separate user grant and cannot auto-repeat.
- **T-N2C-06:** mocked ActivityManager/PackageManager asserts zero launches, permission changes or task switches.

## N3 — MediaProjection and Accessibility consented capabilities

### N3.a — suggested `android/tests/test_native_capture_consent_policy.py`

- **T-N3A-01:** MediaProjection unavailable/no user consent yields denied and a truthful user-visible consent **plan**.
- **T-N3A-02:** Android API34/36 per-session MediaProjection token cannot be reused, forged or treated as a durable credential.
- **T-N3A-03:** API30/33 versus API34/36 foreground-service type and Android manifest requirements checked; no automatic manifest permission expansion.
- **T-N3A-04:** user refusal, lock/screen-off, activity destruction and FGS Stop revoke capture readiness immediately.
- **T-N3A-05:** unrelated process/Origin/caller cannot invoke a future sensitive capture Tool via loopback.
- **T-N3A-06:** default built APK remains within approved current Manifest permission allowlist, no capture started by synthetic consent flag.

### N3.b — suggested `android/app/src/androidTest/java/org/androidmcp/nativeapp/NativeCaptureScreenTest.kt`

- **T-N3B-01:** with real disposable-emulator user consent and authenticated fake caller, one accepted projection frame becomes private hashed artifact.
- **T-N3B-02:** missing/refused/revoked consent, locked/secure window and unpaired caller result in denial, no image artifact.
- **T-N3B-03:** frame dimensions, pixel buffer, MIME, file size and timeout are strictly capped; malformed frame is rejected.
- **T-N3B-04:** Android API30/33/34/36 projection grant lifecycle tested under actual emulator only when permission-gated test APK available.
- **T-N3B-05:** Stop/projection callback/process death immediately stops capture and releases image readers, buffers and handles.
- **T-N3B-06:** no frame bytes in normal Tool JSON, logs or status; absent required permission keeps production Tool disabled.

### N3.c — suggested `android/app/src/androidTest/java/org/androidmcp/nativeapp/NativeScreenRecordTest.kt`

- **T-N3C-01:** a user-consented disposable-emulator capture starts finite recording with explicit duration/resolution/size limits.
- **T-N3C-02:** unauthenticated caller, stale/reused consent, API34/36 token reuse and background-only request are denied.
- **T-N3C-03:** cancellation, user Stop, MediaProjection.onStop and FGS process death release encoder/surface and delete partial file.
- **T-N3C-04:** repeated start or two overlapping captures cannot reuse one MediaProjection token or create silent background recording.
- **T-N3C-05:** disk full, dropped frames, oversized output and codec failure return partial/uncertain, never forged complete video.
- **T-N3C-06:** recording artifacts have short private TTL and hash; Android permission Manifest does not silently expand.

### N3.d — suggested `android/tests/test_native_accessibility_policy.py`

- **T-N3D-01:** Accessibility disabled by default with accurate permission/use-case status; no hidden service activation.
- **T-N3D-02:** user denying Accessibility enablement keeps UI inspection/action functions unavailable; no direct Settings grant.
- **T-N3D-03:** an absent Android service declaration cannot be interpreted as permitted from fabricated model args.
- **T-N3D-04:** API30/33/34/36 Accessibility restrictions and applicability of user-facing purpose are explicitly tested/fail closed.
- **T-N3D-05:** service revocation/stop/lock-screen and fake hostile caller clear capabilities; no stale approved UI nodes.
- **T-N3D-06:** production Manifest and default tools/list show no privileged Accessibility Tool/permission without reviewed feature gate.

### N3.e — suggested `android/app/src/test/java/org/androidmcp/nativeapp/NativeUiTreeReadTest.kt`

- **T-N3E-01:** approved fake Accessibility tree emits bounded node roles/visible structure, focus and stable ephemeral handles only.
- **T-N3E-02:** password fields, secure/locked screen, other-app private text and hidden window are masked or inaccessible.
- **T-N3E-03:** no service, revoked grant, stale node epoch and unrelated caller return typed denial without returning old tree.
- **T-N3E-04:** enormous/deep/cyclic node hierarchy is capped by size/depth/node count with partial annotation.
- **T-N3E-05:** Android API30/33/34/36 scoped hierarchy reading checked on user-consented disposable emulator where available.
- **T-N3E-06:** read Tree Tool never dispatches gestures, changes UI state or exposes broader Accessibility actions.

## N4 — scoped UI operations, Storage Access Framework and optional reads

### N4.a — suggested `android/native-protocol/src/test/kotlin/org/androidmcp/protocol/NativeUiActionPlanTest.kt`

- **T-N4A-01:** typed tap/swipe/scroll/key intent creates a deterministic plan bound to current focused window and ephemeral node epoch.
- **T-N4A-02:** out-of-range coordinates, wrong display rotation, unknown key/gesture and arbitrary shell text are denied.
- **T-N4A-03:** stale node/window, unavailable Accessibility, locked screen and no caller authentication deny dispatch.
- **T-N4A-04:** duplicate plan has stable digest but actual UI gesture is marked non-idempotent and cannot auto-replay after timeout.
- **T-N4A-05:** cancellation before dispatch causes zero injected events; cancellation after dispatch reports uncertain rather than undoing input.
- **T-N4A-06:** default Native Tool never executes a gesture or broad Accessibility action from an `approved=true` model field.

### N4.b — suggested `android/tests/test_native_emulator_ui_automation_guard.py`

- **T-N4B-01:** test runner confirms exact known emulator serial, `ro.kernel.qemu=1`, expected API/ABI and boot completion **before** any input.
- **T-N4B-02:** connected physical USB tablet, mismatched SDK API and unknown emulator serial are rejected with zero tap/key dispatch.
- **T-N4B-03:** genuine disposable API30/33/34/36 instrumentation test sends bounded tap/swipe/key and verifies expected UI state only on its own test app.
- **T-N4B-04:** stale UI hierarchy after rotation, app restart or dialog transition causes reinspection, never blind repeat.
- **T-N4B-05:** timeout, ADB disconnect and test runner kill produce an uncertain operation with no fallback to real Android.
- **T-N4B-06:** test cleanup stops only owned test Activity/AVD state, not another AVD or physical Native service.

### N4.c — suggested `android/app/src/test/java/org/androidmcp/nativeapp/NativeSafPermissionTest.kt`

- **T-N4C-01:** actual user-provided ACTION_OPEN_DOCUMENT URI grant is represented by an opaque scoped handle with exact access mode.
- **T-N4C-02:** model-forged content URI, wrong authority/provider, revoked/expired grant and unchecked file paths are denied.
- **T-N4C-03:** permissions for read versus write and persistable versus one-time URI grants are kept distinct.
- **T-N4C-04:** Activity result absent/cancelled/invalid, provider kill or provider throwing returns typed denied/partial.
- **T-N4C-05:** API30/33/34/36 SAF picker/grant behavior is checked without requesting MANAGE_EXTERNAL_STORAGE.
- **T-N4C-06:** no other app's files or broad `/sdcard` directory becomes accessible merely by loading a document URI string.

### N4.d — suggested `android/app/src/test/java/org/androidmcp/nativeapp/NativeSafExportTest.kt`

- **T-N4D-01:** user-chosen readable SAF source is copied as a bounded private artifact with correct MIME/size/SHA-256.
- **T-N4D-02:** URI without READ grant, revoked permissions, symbolic provider alias and wrong ContentProvider process fail closed.
- **T-N4D-03:** cancellation, disk full, oversized content and broken provider stream leave no trusted partial file.
- **T-N4D-04:** duplicate export request has one stable artifact handle; process death/restart never restores stale grant implicitly.
- **T-N4D-05:** API30/33/34/36 picker result and denied/cancelled user choice produce accurate code paths in disposable emulator.
- **T-N4D-06:** no raw document bytes, sensitive file path, account identifier or personally identifying content in public MCP errors/logs.

### N4.e — suggested `android/app/src/test/java/org/androidmcp/nativeapp/NativeSafImportTest.kt`

- **T-N4E-01:** authorized user-selected WRITE URI and trusted hash-matching artifact produce an atomic/import **plan**.
- **T-N4E-02:** read-only/revoked URI, wrong provider, outside-scope destination or forged write grant are denied.
- **T-N4E-03:** oversized payload/stream failure/provider crash cleans partial content or reports uncertainty without falsely claiming atomicity.
- **T-N4E-04:** duplicate import request or stale artifact digest never silently overwrites another document.
- **T-N4E-05:** emulator user cancellation at picker and process death before/after dispatch are separately classified.
- **T-N4E-06:** default public Tool is disabled until real user URI grant/caller auth, and never writes an arbitrary local/system path.

### N4.f — suggested `android/app/src/test/java/org/androidmcp/nativeapp/NativeOptionalSensorsTest.kt`

- **T-N4F-01:** allowed non-sensitive battery/display/connectivity status is read with exact Android API and permission metadata.
- **T-N4F-02:** location, microphone, contacts and notification content remain unavailable without specific actual runtime consent.
- **T-N4F-03:** model-requested background polling/continuous sensor tracking cannot enable a persistent surveillance loop.
- **T-N4F-04:** API30/33/34/36 permission changes, sensor unsupported, disabled location provider and revoked grant return typed unavailable.
- **T-N4F-05:** high-rate sensor events are bounded and unsubscribed on FGS Stop, Activity destruction and client disconnect.
- **T-N4F-06:** public JSON omits nearby IDs, precise coordinates, notification text and unrelated sensitive platform data.

## N5 — app-owned diagnostics, bounded event delivery and Host fallback

### N5.a — suggested `android/app/src/test/java/org/androidmcp/nativeapp/NativeCrashReportTest.kt`

- **T-N5A-01:** synthetic app-owned exception/ANR produces a bounded structured report with Native app version, uptime and code.
- **T-N5A-02:** failure in a different app's process cannot be read through unrestricted system Logcat or hidden privileged APIs.
- **T-N5A-03:** exception message containing user tokens, addresses and secrets is redacted from public MCP response and ordinary logs.
- **T-N5A-04:** crash of FGS while report is being recorded leaves accurate incomplete/restart state, not retroactive success.
- **T-N5A-05:** report/artifact retention expiry and deletion are enforced after reboot/process restart without leaking orphan files.
- **T-N5A-06:** no sensitive diagnostics become accessible to unauthenticated localhost process/Origin.

### N5.b — suggested `android/app/src/test/java/org/androidmcp/nativeapp/NativeOwnAppPerformanceTest.kt`

- **T-N5B-01:** sampled own-process memory/cpu/event latency values use stable units, time and app process identity.
- **T-N5B-02:** attempting global kernel/perfetto/root/systemwide profiling from a regular app returns explicit unsupported/denied.
- **T-N5B-03:** API30/33/34/36 process API and permission availability yield truthful partial/unsupported values.
- **T-N5B-04:** background FGS Stop, app sleep and process restart clear stale counters rather than reporting healthy sample streams.
- **T-N5B-05:** long/high-frequency sample requests are rate/buffer capped and cancelled on demand.
- **T-N5B-06:** no ungranted app/process identifiers or raw private backtraces are returned in model-visible status.

### N5.c — suggested `android/native-lifecycle/src/test/kotlin/org/androidmcp/lifecycle/NativeEventStoreTest.kt`

- **T-N5C-01:** bounded diagnostic event is stored with monotonic ID/timestamp, origin and allowed sensitivity classification.
- **T-N5C-02:** duplicate request/late ack cannot insert a second event or advance cursor incorrectly; slow consumer receives bounded pages.
- **T-N5C-03:** process death and FGS restart reopen/reconcile pending event state without inventing a completed subscriber delivery.
- **T-N5C-04:** expiry, capacity overflow and backpressure drop events honestly with counters; no unbounded in-memory queue.
- **T-N5C-05:** invalid/foreign cursor, revoked caller and invalid owner cannot access a prior user's diagnostics.
- **T-N5C-06:** Stop/unsubscribe closes listeners/threads/files and erases sensitive expired artifacts per policy.

### N5.d — suggested `android/tests/test_native_host_fallback_state.py`

- **T-N5D-01:** Host ADB alive and Native service dead returns a read-only Host fallback suggestion with distinct provider identity.
- **T-N5D-02:** Host offline but Native user-started service alive provides only capabilities actually permitted to Native.
- **T-N5D-03:** both available and both unavailable cases report distinct status/provenance without silently choosing first provider.
- **T-N5D-04:** native instance reinstall, boot-epoch change, USB disconnect and serial reuse invalidate stale pairing/fallback refs.
- **T-N5D-05:** loss of Native write lease cannot enable Host APK install, root, Accessibility or fallback UI write.
- **T-N5D-06:** fake Host/Native MCP interaction has typed unknown/denied errors, no real USB/physical device operation.

## N6 — authenticated Native identity and inert Host/Native concurrency

### N6.a — suggested `android/native-protocol/src/test/kotlin/org/androidmcp/protocol/NativeInstallationIdentityTest.kt`

- **T-N6A-01:** fresh installation creates a private instance identity and public verification key independent of Android serial/MAC.
- **T-N6A-02:** uninstall/reinstall or app data clear rotates install identity and invalidates old Host binding.
- **T-N6A-03:** private key material cannot be returned by Tools/list, tools/call, status or logcat and is stored under app sandbox protections.
- **T-N6A-04:** device reboot/FGS restart does not silently change install identity, but invalidates transient auth challenges.
- **T-N6A-05:** corrupted/denied key storage and concurrent first-start identity creation fail closed without duplicating ownership.
- **T-N6A-06:** a model-provided identity string or ADB serial cannot impersonate a signed, registered installation.

### N6.b — suggested `android/native-protocol/src/test/kotlin/org/androidmcp/protocol/NativePairingChallengeTest.kt`

- **T-N6B-01:** deterministic fake signed nonce challenge binds versioned Host identity, exact Native instance and boot epoch.
- **T-N6B-02:** replay, wrong key, tampered digest, stale timestamp, mismatched Origin/Host and cross-device challenge are denied.
- **T-N6B-03:** unauthenticated 127.0.0.1 caller may receive minimal status but no device data/capture/action through mock authorization.
- **T-N6B-04:** service restart/USB reconnect cannot reuse previous transient challenge or treat tunnel presence as identity.
- **T-N6B-05:** malformed/oversized packet, 100 concurrent challenge attempts and clock rollback remain bounded.
- **T-N6B-06:** absent jointly accepted shared protocol leaves Native pairing production route disabled, not guessed compatible.

### N6.c — suggested `android/native-protocol/src/test/kotlin/org/androidmcp/protocol/NativeFenceStateTest.kt`

- **T-N6C-01:** monotonic fenced lease token/high-water mark persists across Native FGS process restart and app lifecycle.
- **T-N6C-02:** stale token/duplicate action digest/wrong Host identity and reused nonce are rejected prior to mutation.
- **T-N6C-03:** boot epoch/reinstall/clock rollback invalidate existing lease and cannot reset high-water mark without new pairing.
- **T-N6C-04:** crash or disk-full during persistence results in denied/uncertain state, not a valid unpersisted grant.
- **T-N6C-05:** two concurrent accessors to persistent lease record have one atomic winner and no high-water regression.
- **T-N6C-06:** default Native MCP status remains nonprivileged; no real device-mutation executor is connected to fake fencing logic.

### N6.d — suggested `android/native-protocol/src/test/kotlin/org/androidmcp/protocol/NativeMultiHostLeaseTest.kt`

- **T-N6D-01:** synthetic Host A vs Host B concurrent acquire for same target/plan yields only one active authorized lease.
- **T-N6D-02:** wrong Host renewal, expired TTL, stale fence, repeated release and out-of-order request fail closed.
- **T-N6D-03:** user stops Native FGS while lease held; Host receives uncertain/unavailable and cannot force device action.
- **T-N6D-04:** Native app process death during an action leaves durable ambiguous receipt, no blind replay after restart.
- **T-N6D-05:** mismatched Host/Native package or future schema version fails compatibility gate without ignoring unknown required fields.
- **T-N6D-06:** fake dual runtime tests prove no real Host CLI process, physical ADB mutation or public unauthenticated listener is used.

### N6.e — suggested `android/tests/test_native_mutation_profile_denials.py`

- **T-N6E-01:** default actual Kotlin tools/list exposes no installation/gesture/system-setting write Tool to unpaired caller.
- **T-N6E-02:** fake model-supplied `approved=true` or stale signed action does not bypass caller/permission/lease checks.
- **T-N6E-03:** even with a synthetic lease, missing true Android runtime consent denies Accessibility/MediaProjection/PackageInstaller actions.
- **T-N6E-04:** mutation Tool metadata accurately describes non-idempotent, potentially destructive effects and honest disabled state.
- **T-N6E-05:** replay after uncertain result cannot execute duplicate UI gesture/install, and no action runs after user Stop.
- **T-N6E-06:** APK Manifest contains no extra privileged service/permission; all real mutating handlers remain inactive until independent reviewed enabling PR.

## N7 — user-mediated install, explicit app launch and service recovery

### N7.a — suggested `android/app/src/test/java/org/androidmcp/nativeapp/NativePackageInstallerPlanTest.kt`

- **T-N7A-01:** a validated trusted APK artifact digest/package/ABI yields a deterministic user-mediated PackageInstaller **plan**.
- **T-N7A-02:** unsigned/bad certificate, wrong target SDK, missing artifact and arbitrary file URI inputs are rejected.
- **T-N7A-03:** caller claims of `installWithoutPrompt`, `approved=true` or broad installation permission fail closed.
- **T-N7A-04:** API30/33/34/36 user consent/unknown-sources policy is represented accurately, never treated as granted.
- **T-N7A-05:** cancel/replay of a plan never initiates installation or leaves a trusted open install session.
- **T-N7A-06:** default Native public Tool remains disabled for install, even when mock installer service is available.

### N7.b — suggested `android/app/src/androidTest/java/org/androidmcp/nativeapp/NativePackageInstallerConsentTest.kt`

- **T-N7B-01:** a verified disposable emulator can open an Android-mediated user-confirmation flow for a signed test APK only.
- **T-N7B-02:** user refusal or canceled installer UI causes no installed package and accurately reports denied/cancelled.
- **T-N7B-03:** physical ADB serial, unrelated emulator, invalid qemu/API and unapproved app package are rejected **before** install.
- **T-N7B-04:** process death, lost foreground and installer session abandonment clean up test session artifacts without silent retry.
- **T-N7B-05:** Android API30/33/34/36 emulator paths verify platform consent/unknown-sources differences when relevant; unavailable matrix is blocked.
- **T-N7B-06:** test harness never enables silent privileged physical APK installation or broad REQUEST_INSTALL_PACKAGES without independent policy gate.

### N7.c — suggested `android/app/src/test/java/org/androidmcp/nativeapp/NativeAppLaunchTest.kt`

- **T-N7C-01:** an exact exported Activity explicitly approved by user/authorized caller can be launched in safe disposable emulator.
- **T-N7C-02:** non-exported, unknown, off-user, locked-screen or implicit Intent to another app is denied.
- **T-N7C-03:** background-start restrictions and Android API30/33/34/36 are respected; no hidden start-from-FGS bypass.
- **T-N7C-04:** duplicate launch/non-idempotent task transition records action ID, no blind rerun after ambiguous timeout.
- **T-N7C-05:** user/Origin revocation or FGS Stop between authorization and dispatch prevents execution.
- **T-N7C-06:** initial status-only app retains unchanged behavior, no foreign package force-stop or broad shell command added.

### N7.d — suggested `android/tests/test_native_service_recovery.py`

- **T-N7D-01:** explicit user Start after legitimate Stop reclaims the port only after verified shutdown and fresh readiness proof.
- **T-N7D-02:** Android process kill, reboot and START_NOT_STICKY do not silently resurrect N3 or open its endpoint.
- **T-N7D-03:** unreleased port, stale owner, failed notification stop and second owner collision fail closed with accurate UI status.
- **T-N7D-04:** API30/33/34/36 notification permission refusal and foreground-service restrictions tested on verified AVDs.
- **T-N7D-05:** service restart invalidates outstanding sensitive capture sessions, caller challenges and active leases.
- **T-N7D-06:** no wake-lock/battery exemption, boot receiver, always-on background agent or external port introduced by recovery.

## N8 — managed-device feasibility and prohibited privilege boundaries

### N8.a — suggested `android/tests/test_native_managed_device_policy.py`

- **T-N8A-01:** non-DeviceOwner ordinary Native app reports managed device features unsupported without provisioning.
- **T-N8A-02:** fake verified DeviceOwner state reports supported capability names but defaults to **plan-only** for policy changes.
- **T-N8A-03:** model-controlled Device Admin/Owner role string cannot self-provision, elevate privileges or install admin policies.
- **T-N8A-04:** API30/33/34/36 DevicePolicyManager restrictions are reflected accurately; OEM differences yield unsupported.
- **T-N8A-05:** attempts to wipe, lock, change account/policy or silent install are rejected with zero OS side effects.
- **T-N8A-06:** Default Manifest/registered Tools remain nonadministrative and no real enterprise provisioning is performed.

### N8.b — suggested `android/tests/test_native_root_recovery_gaps.py`

- **T-N8B-01:** ordinary Native APK reports root/Bootloader/ROM flashing unavailable and explains Host-supervised alternative.
- **T-N8B-02:** no unrestricted `su`, ADB shell, OEM Fastboot or raw partition Tool appears in Native tools/list.
- **T-N8B-03:** fake Android crash/unbootable mode correctly marks Native service unavailable, not remotely recoverable via local APK.
- **T-N8B-04:** invalid Host identity or missing ADB/Fastboot authorization never triggers new elevated privileges as a fallback.
- **T-N8B-05:** model attempts to bypass lockscreen/integrity, erase data or unlock Bootloader yield typed denied/unsupported.
- **T-N8B-06:** safe recovery **plan** includes physical-owner confirmation requirements and no actual device/reboot/flash command executed.

## Execution checklist and evidence schema

For every Nxx PR, record the **six listed T-Nxx-01..06**
as implemented/failed/blocked with specific Kotlin/Python test
paths. Use actual SDK/emulator permission tests when the feature
needs them, not just a hypothetical protocol fake.

Mandatory receipt: `package_id`, Native capability IDs
N01–N20, `base_sha`, `feature_sha`, changed-file
ownership, new test IDs and red/green execution logs, Kotlin/
protocol tests, signed APK/manifest/API evidence, four-API AVD
matrix results (or honest blocked reason), no physical Android
write claim unless separately permitted, self-review vs actual
independent security review, PR, `main_merge_sha` and
post-merge tree. Move to the next package **after** a verified
merge rather than piling up stacked, drifting Native branches.

A test that expects `denied` or `unavailable` is a
valuable positive safety result for a deferred capability.
It does **not** establish authorization to enable the real
operation. No unattended physical Android changes, public
network listener, Root, Bootloader, Drive/File browser bypass
or app-store publishing are authorized by this specification.
