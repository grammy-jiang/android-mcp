# Android Native MCP — V3 Executable Acceptance Matrix

> **SPECIFICATION ONLY:** Every V3 case starts `NOT_RUN`. These are not pass results. The original 228 T-Nxx cases also remain mandatory for exact traceability; their pre-existing green JVM/mock results cannot substitute for V3 OS evidence.

**Counts:** 20 capability families × 8 explicitly defined tests = **160** capability cases; 32 independent cross-cutting tests = **192 new named acceptance scenarios**. These supplement (not replace) the original 228 numbered specifications.

## Required evidence per executed case

Every real test receipt records `case_id`, capability, mode (positive/negative/recovery), exact Git SHA and tree, APK/AAB and fixture SHA256, known QEMU serial/API/ABI/boot identity, run time, requested `tools/list` and `tools/call` payload (secrets redacted), authenticated actor and consent event, Native framework API/callback trace, a separate Android OS/fixture oracle, pass/fail/blocked reason, cleanup and resource-leak checks. E2E means **Native actually executes or rejects the real platform operation**; host ADB is only test setup or independent observation, not the implementation under test.

## Platform scoring contract

| Situation | Result | Counts as delivered? |
| --- | --- | --- |
| Correct Native MCP + real OS effect + oracle + denials | `PASS_REAL_E2E` | Yes for applicable Android API / approved profile only |
| JVM fake, source-level check, mock, pure ADB gesture | `PASS_SYNTHETIC` / `PASS_HARNESS` | **No** |
| Real OS user consent not obtained or unresolved external safety review | `BLOCKED_EXTERNAL` | **No**; keep open |
| Android platform itself cannot provide the capability to ordinary apps | `UNSUPPORTED_BY_PLATFORM_WITH_EVIDENCE` | An explicit product exclusion **only after approved fallback/scope review** |
| Test not executed or result uncertain | `NOT_RUN` / `UNCERTAIN` | **No** |

## N01–N20 cases

### N01 — Native MCP loopback and health

Baseline evidence: `BASELINE_LOCAL_E2E`. Target: `CORE`. V3 feature acceptance: **NOT_VERIFIED_V3**.

| Test ID | Required scenario (positive/negative/recovery) | Current V3 result |
| --- | --- | --- |
| `V3-N01-01` | Real client discovers exactly the authenticated status tool; status response matches schema on a running emulator | `NOT_RUN` |
| `V3-N01-02` | Native Activity starts loopback endpoint and Android process/listener/HTTP reply are independently observed | `NOT_RUN` |
| `V3-N01-03` | Anonymous/malformed/unknown tool calls cannot enumerate sensitive tools or trigger other providers | `NOT_RUN` |
| `V3-N01-04` | Activity Home and foreground-service modes preserve their documented different lifecycle and user control | `NOT_RUN` |
| `V3-N01-05` | Notification Stop removes listener, service and ongoing notification with independent Android oracle | `NOT_RUN` |
| `V3-N01-06` | Port conflict, rapid dual start, process death, app restart and stale readiness nonce are fail-closed | `NOT_RUN` |
| `V3-N01-07` | API30/33 legacy and API34/36 FGS behavior is observed on distinct pinned QEMU instances | `NOT_RUN` |
| `V3-N01-08` | Large headers/bodies, hostile Host/Origin, log redaction, output bound and teardown verified | `NOT_RUN` |

### N02 — Build/OS/ABI/app profile

Baseline evidence: `INTERNAL_NOT_PUBLIC`. Target: `CORE`. V3 feature acceptance: **NOT_VERIFIED_V3**.

| Test ID | Required scenario (positive/negative/recovery) | Current V3 result |
| --- | --- | --- |
| `V3-N02-01` | Authenticated native_device_profile MCP call returns actual Build/API/ABI/app version | `NOT_RUN` |
| `V3-N02-02` | Compare fields with device-side Build APIs from AndroidJUnitRunner in same emulator boot | `NOT_RUN` |
| `V3-N02-03` | Unauthenticated client and foreign app on device cannot retrieve protected profile | `NOT_RUN` |
| `V3-N02-04` | Profile omits serial, IMEI, advertising ID, fingerprint and persistent tracking identifiers | `NOT_RUN` |
| `V3-N02-05` | App goes background or permission is revoked: return exact supported/denied status without fabricated values | `NOT_RUN` |
| `V3-N02-06` | Restart and repeated profile requests retain correct schema and do not leak prior sessions | `NOT_RUN` |
| `V3-N02-07` | API30/33/34/36 release/ABI/type differences mapped to exact per-OS expectations | `NOT_RUN` |
| `V3-N02-08` | Bad schema, oversized response request and failure injection yield bounded typed error | `NOT_RUN` |

### N03 — Battery/storage/display/network snapshots

Baseline evidence: `INTERNAL_NOT_PUBLIC`. Target: `CORE`. V3 feature acceptance: **NOT_VERIFIED_V3**.

| Test ID | Required scenario (positive/negative/recovery) | Current V3 result |
| --- | --- | --- |
| `V3-N03-01` | Authenticated native_system_snapshot MCP call returns real battery, app storage and display measurements | `NOT_RUN` |
| `V3-N03-02` | Cross-check against BatteryManager/StatFs/DisplayMetrics on the same boot, not fake numbers | `NOT_RUN` |
| `V3-N03-03` | Caller without read scope receives typed denial without personal network identifiers | `NOT_RUN` |
| `V3-N03-04` | Unavailable battery/system service and denied network permission are represented honestly | `NOT_RUN` |
| `V3-N03-05` | Rotation changes display values; no stale data survives post-rotation refresh | `NOT_RUN` |
| `V3-N03-06` | Rapid readings and process restart have rate/size bounds and no background sampling | `NOT_RUN` |
| `V3-N03-07` | API30/33/34/36 snapshot correctness and explicitly unsupported sensor fields | `NOT_RUN` |
| `V3-N03-08` | No SSID, MAC, location or detailed device identity exposed by default | `NOT_RUN` |

### N04 — Android permission and consent readiness

Baseline evidence: `FGS_INTERNAL_REAL`. Target: `CORE`. V3 feature acceptance: **NOT_VERIFIED_V3**.

| Test ID | Required scenario (positive/negative/recovery) | Current V3 result |
| --- | --- | --- |
| `V3-N04-01` | Authenticated native_permission_status reflects actual Android grant/denial state for each reviewed capability | `NOT_RUN` |
| `V3-N04-02` | AndroidJUnitRunner independently queries PackageManager and relevant manager permission fields | `NOT_RUN` |
| `V3-N04-03` | MCP boolean/model claims cannot create OS grants or bypass user-authenticated profile | `NOT_RUN` |
| `V3-N04-04` | Real OS deny/revoke and Settings enable/disable transitions are observed through callback or fresh query | `NOT_RUN` |
| `V3-N04-05` | Activity/FGS Stop revokes effective session-ready state immediately | `NOT_RUN` |
| `V3-N04-06` | Process death/restart invalidates ephemeral user grants, projection tokens and owner proof | `NOT_RUN` |
| `V3-N04-07` | API30/33/34/36 permission and foreground-service differences checked through system UI | `NOT_RUN` |
| `V3-N04-08` | Permission responses distinguish UNAVAILABLE, DENIED, REQUIRES_USER_ACTION, GRANTED and EXPIRED | `NOT_RUN` |

### N05 — Visible packages and targeted package info

Baseline evidence: `INTERNAL_NOT_PUBLIC`. Target: `CORE`. V3 feature acceptance: **NOT_VERIFIED_V3**.

| Test ID | Required scenario (positive/negative/recovery) | Current V3 result |
| --- | --- | --- |
| `V3-N05-01` | Authenticated native_package_query returns own fixture app package/version/known signer digest | `NOT_RUN` |
| `V3-N05-02` | Cross-check Native PackageManager filtered result against fixture-package on-device ground truth | `NOT_RUN` |
| `V3-N05-03` | Hidden/unallowlisted/other-user package request denied or not-visible without data leak | `NOT_RUN` |
| `V3-N05-04` | App installation/removal and package visibility change reflected in fresh query | `NOT_RUN` |
| `V3-N05-05` | Missing package, package manager exception and app disabled are separate typed outcomes | `NOT_RUN` |
| `V3-N05-06` | Duplicate/rate-limited query and restart do not return cached sensitive metadata | `NOT_RUN` |
| `V3-N05-07` | API30/33/34/36 package visibility and manifest `<queries>` scope validated | `NOT_RUN` |
| `V3-N05-08` | No QUERY_ALL_PACKAGES, full signer key material, broad inventory or cross-profile data | `NOT_RUN` |

### N06 — Native own-app health/diagnostics

Baseline evidence: `INTERNAL_NOT_PUBLIC`. Target: `CORE`. V3 feature acceptance: **NOT_VERIFIED_V3**.

| Test ID | Required scenario (positive/negative/recovery) | Current V3 result |
| --- | --- | --- |
| `V3-N06-01` | Authenticated native_app_health returns real own-process/service counters and last error state | `NOT_RUN` |
| `V3-N06-02` | Cross-check process/FGS health from Android dumpsys and bounded own-app counters | `NOT_RUN` |
| `V3-N06-03` | Another app/unauthenticated client cannot query diagnostic traces | `NOT_RUN` |
| `V3-N06-04` | Synthetic app exception is recorded without reading system-wide logcat | `NOT_RUN` |
| `V3-N06-05` | User stops service: status is stopped and no background collection continues | `NOT_RUN` |
| `V3-N06-06` | Kill/restart retention and dedupe are actually observed; no stale active session claims | `NOT_RUN` |
| `V3-N06-07` | API30/33/34/36 own-process APIs and foreground constraints tested | `NOT_RUN` |
| `V3-N06-08` | Secrets, raw stack personal paths and large diagnostic payloads are redacted/bounded | `NOT_RUN` |

### N07 — Accessibility focus and real UI tree

Baseline evidence: `NO_ACCESSIBILITY_SERVICE`. Target: `SENSITIVE_USER_CONSENT`. V3 feature acceptance: **NOT_VERIFIED_V3**.

| Test ID | Required scenario (positive/negative/recovery) | Current V3 result |
| --- | --- | --- |
| `V3-N07-01` | User enables declared purpose-limited AccessibilityService using actual Android Settings UI | `NOT_RUN` |
| `V3-N07-02` | Native native_ui_inspect through MCP returns a real node from own deterministic fixture Activity | `NOT_RUN` |
| `V3-N07-03` | Other app/window without scoped consent and secure input nodes yield no sensitive data | `NOT_RUN` |
| `V3-N07-04` | Real Settings disable/revoke disconnects Service and immediately forbids a UI-tree read | `NOT_RUN` |
| `V3-N07-05` | Locked screen, Home and window switch invalidate focused-window scope | `NOT_RUN` |
| `V3-N07-06` | Process death/restart or stale node epoch never reuses old UI snapshot authorization | `NOT_RUN` |
| `V3-N07-07` | API30/33/34/36 accessibility enable/visibility/gesture capability behavior observed | `NOT_RUN` |
| `V3-N07-08` | Redaction of password/notification content and bound on tree depth/bytes verified | `NOT_RUN` |

### N08 — Native Accessibility gesture/node actions

Baseline evidence: `ADB_HARNESS_ONLY`. Target: `SENSITIVE_USER_CONSENT`. V3 feature acceptance: **NOT_VERIFIED_V3**.

| Test ID | Required scenario (positive/negative/recovery) | Current V3 result |
| --- | --- | --- |
| `V3-N08-01` | Native MCP native_ui_action calls real dispatchGesture/node action on own authorized fixture | `NOT_RUN` |
| `V3-N08-02` | Android gesture callback and fixture Activity state counter independently prove actual effect | `NOT_RUN` |
| `V3-N08-03` | Raw model coordinate, foreign package/window, secure field and wrong auth denied | `NOT_RUN` |
| `V3-N08-04` | Real user disables Accessibility during action: no further effects or silent repeat | `NOT_RUN` |
| `V3-N08-05` | User Stop, rotation or foreground change invalidate node and gesture grants | `NOT_RUN` |
| `V3-N08-06` | Two concurrent Host clients contend for one action fence; at most one fixture mutation | `NOT_RUN` |
| `V3-N08-07` | API30/33/34/36 actual service-dispatched gesture behavior, not ADB input substitute | `NOT_RUN` |
| `V3-N08-08` | Timeout-after-dispatch returns UNCERTAIN, never retries tap/swipe automatically | `NOT_RUN` |

### N09 — One-shot consented screen capture

Baseline evidence: `INERT_CONSENT_MODEL`. Target: `SENSITIVE_USER_CONSENT`. V3 feature acceptance: **NOT_VERIFIED_V3**.

| Test ID | Required scenario (positive/negative/recovery) | Current V3 result |
| --- | --- | --- |
| `V3-N09-01` | Native MCP capture request initiates actual Android MediaProjection consent Activity | `NOT_RUN` |
| `V3-N09-02` | User accepts; Native creates single VirtualDisplay and receives real frame matching fixture pixels/hash | `NOT_RUN` |
| `V3-N09-03` | Unpaired or unrelated app capture request cannot present/consume another clients grant | `NOT_RUN` |
| `V3-N09-04` | User denies consent and Android projection onStop triggers typed denied/stopped, no frame | `NOT_RUN` |
| `V3-N09-05` | Foreground capture service stops and buffers/virtual display are released promptly | `NOT_RUN` |
| `V3-N09-06` | Expired/reused token, process death, rotation and duplicate capture require new session consent | `NOT_RUN` |
| `V3-N09-07` | API30/33/34/36 consent/FGS type/session behavior observed and versioned | `NOT_RUN` |
| `V3-N09-08` | Secure windows, clip bounds, frame size/MIME/retention, artifact redaction enforced | `NOT_RUN` |

### N10 — Short bounded screen recording

Baseline evidence: `SYNTHETIC_RECORDING`. Target: `SENSITIVE_USER_CONSENT`. V3 feature acceptance: **NOT_VERIFIED_V3**.

| Test ID | Required scenario (positive/negative/recovery) | Current V3 result |
| --- | --- | --- |
| `V3-N10-01` | MCP start_recording with actual user projection consent captures bounded fixture video | `NOT_RUN` |
| `V3-N10-02` | Media extractor decodes expected frames and monotonic duration from recorded artifact | `NOT_RUN` |
| `V3-N10-03` | Unauthenticated or foreign client cannot start/stop/extend another client recording | `NOT_RUN` |
| `V3-N10-04` | User denies/OS revokes consent; session stops, no extra frames recorded | `NOT_RUN` |
| `V3-N10-05` | Native notification/user Stop releases VirtualDisplay, encoder, surface and artifact handles | `NOT_RUN` |
| `V3-N10-06` | Crash/restart and duplicate operation yield uncertain/stop, not covert resumption | `NOT_RUN` |
| `V3-N10-07` | API30/33/34/36 Android mediaProjection FGS/type/user-consent behavior validated | `NOT_RUN` |
| `V3-N10-08` | Max duration, size, frame rate, privacy and artifact encryption/retention verified | `NOT_RUN` |

### N11 — SAF authorized file import/export

Baseline evidence: `INERT_SAF_MODEL`. Target: `SENSITIVE_USER_CONSENT`. V3 feature acceptance: **NOT_VERIFIED_V3**.

| Test ID | Required scenario (positive/negative/recovery) | Current V3 result |
| --- | --- | --- |
| `V3-N11-01` | MCP authorized request opens actual ACTION_OPEN_DOCUMENT and returns selected URI-bound opaque handle | `NOT_RUN` |
| `V3-N11-02` | Real ContentResolver stream reads fixture bytes; exported private artifact SHA-256 equals independent source hash | `NOT_RUN` |
| `V3-N11-03` | URI string forgery/path traversal and foreign providers without OS grants are denied | `NOT_RUN` |
| `V3-N11-04` | User cancels picker, revokes URI grant or provider raises IOException: truthful denied/partial | `NOT_RUN` |
| `V3-N11-05` | ACTION_CREATE_DOCUMENT writes a new fixture destination after explicit user selection | `NOT_RUN` |
| `V3-N11-06` | Stop/process death/duplicate write cannot overwrite unrelated doc or falsely claim atomic write | `NOT_RUN` |
| `V3-N11-07` | API30/33/34/36 picker, persisted vs transient grant, and provider behavior independently observed | `NOT_RUN` |
| `V3-N11-08` | Read/write mode, MIME/bytes, hash, content-disclosure, cleanup and size/retention caps validated | `NOT_RUN` |

### N12 — Explicit allowlisted app launch

Baseline evidence: `PLAN_ONLY_INTENT`. Target: `AUTHORIZED_WRITE`. V3 feature acceptance: **NOT_VERIFIED_V3**.

| Test ID | Required scenario (positive/negative/recovery) | Current V3 result |
| --- | --- | --- |
| `V3-N12-01` | Foreground Native app with explicit approval calls startActivity on allowlisted fixture component | `NOT_RUN` |
| `V3-N12-02` | Independent fixture Activity resumed event and Android task manager agree on target component | `NOT_RUN` |
| `V3-N12-03` | Implicit deep link, non-exported component, wrong user and foreign package are rejected | `NOT_RUN` |
| `V3-N12-04` | User/Host grant revoked before launch: no Activity transition occurs | `NOT_RUN` |
| `V3-N12-05` | Background FGS cannot bypass Android background activity launch restrictions | `NOT_RUN` |
| `V3-N12-06` | Duplicate/timeout/restart launch fences prevent second task start without fresh grant | `NOT_RUN` |
| `V3-N12-07` | API30/33/34/36 launch and PendingIntent background restrictions tested | `NOT_RUN` |
| `V3-N12-08` | MCP receipt includes specific executed/rejected effect and no arbitrary shell/force-stop | `NOT_RUN` |

### N13 — Scoped optional sensors/notifications

Baseline evidence: `PRIVATE_OPTIONAL_POLICY`. Target: `OPTIONAL_CONSENT`. V3 feature acceptance: **NOT_VERIFIED_V3**.

| Test ID | Required scenario (positive/negative/recovery) | Current V3 result |
| --- | --- | --- |
| `V3-N13-01` | MCP opt-in native_optional_status reads supported emulator sensor/notification values | `NOT_RUN` |
| `V3-N13-02` | Android SensorManager/system notification APIs confirm values or UNSUPPORTED | `NOT_RUN` |
| `V3-N13-03` | Unpaired caller cannot read location, notification content or sensor data | `NOT_RUN` |
| `V3-N13-04` | User permission denied/revoked yields exact permission-required status | `NOT_RUN` |
| `V3-N13-05` | Stop/foreground loss terminates any optional sampling session | `NOT_RUN` |
| `V3-N13-06` | Process death/rate limit prevents silent restart of monitors | `NOT_RUN` |
| `V3-N13-07` | API30/33/34/36 available vs absent simulated hardware logged | `NOT_RUN` |
| `V3-N13-08` | No background surveillance, identifiers or notification texts without scoped consent | `NOT_RUN` |

### N14 — Own performance/crash diagnostics retention

Baseline evidence: `PRIVATE_TELEMETRY_MODEL`. Target: `CORE`. V3 feature acceptance: **NOT_VERIFIED_V3**.

| Test ID | Required scenario (positive/negative/recovery) | Current V3 result |
| --- | --- | --- |
| `V3-N14-01` | MCP own_telemetry gets actual own-process memory, startup and bounded error counters | `NOT_RUN` |
| `V3-N14-02` | Independent instrumentation injects benign own-process fault and confirms resulting record | `NOT_RUN` |
| `V3-N14-03` | Cross-app logcat/system profiler/data is never readable from Native diagnostic tool | `NOT_RUN` |
| `V3-N14-04` | Opt-out/revoke disables collection and wipes/retains exactly per configured policy | `NOT_RUN` |
| `V3-N14-05` | Foreground service Stop leaves no diagnostic sampling worker alive | `NOT_RUN` |
| `V3-N14-06` | Crash/restart journal integrity and event ordering/retention are verified | `NOT_RUN` |
| `V3-N14-07` | API30/33/34/36 memory/perf APIs and unavailable paths tested | `NOT_RUN` |
| `V3-N14-08` | PII/secret redaction, bounded file capacity and export approval validated | `NOT_RUN` |

### N15 — PackageInstaller user-approved install

Baseline evidence: `CONSENT_PRECHECK_BLOCKED`. Target: `SENSITIVE_USER_CONSENT`. V3 feature acceptance: **NOT_VERIFIED_V3**.

| Test ID | Required scenario (positive/negative/recovery) | Current V3 result |
| --- | --- | --- |
| `V3-N15-01` | MCP native_install_request stages pinned signed fixture APK and opens real system install UI | `NOT_RUN` |
| `V3-N15-02` | User approves; PackageManager independently confirms installed fixture version and signer | `NOT_RUN` |
| `V3-N15-03` | Unsigned/wrong-digest/off-allowlist APK and unpaired caller cannot create install session | `NOT_RUN` |
| `V3-N15-04` | User declines/unknown-app-source setting denied: no package installed | `NOT_RUN` |
| `V3-N15-05` | Cancel before/after session commit cleans owned session or reports UNCERTAIN truthfully | `NOT_RUN` |
| `V3-N15-06` | Process crash/timeout/retry does not install second time or bypass OS user action | `NOT_RUN` |
| `V3-N15-07` | API30/33/34/36 STATUS_PENDING_USER_ACTION, source-permission and OS verifier differences | `NOT_RUN` |
| `V3-N15-08` | No physical device installs, no silent-update path; report installed package and session cleanup | `NOT_RUN` |

### N16 — User visible Native service lifecycle

Baseline evidence: `FGS_EMULATOR_BASELINE`. Target: `CORE`. V3 feature acceptance: **NOT_VERIFIED_V3**.

| Test ID | Required scenario (positive/negative/recovery) | Current V3 result |
| --- | --- | --- |
| `V3-N16-01` | Explicit Activity user Start yields Native MCP HTTP readiness and correct service notification | `NOT_RUN` |
| `V3-N16-02` | Android dumpsys independently confirms app FGS/loopback transport and correct owner | `NOT_RUN` |
| `V3-N16-03` | Anonymous/malformed stop and foreign owner cannot silently start/restart service | `NOT_RUN` |
| `V3-N16-04` | Notification permission denied/revoked: start blocked or live service stops as platform requires | `NOT_RUN` |
| `V3-N16-05` | Notification Stop and Activity Stop close listener, notification and pending capture/tool sessions | `NOT_RUN` |
| `V3-N16-06` | Rapid start/stop, device reboot test AVD, service crash and stale port do not auto-resurrect | `NOT_RUN` |
| `V3-N16-07` | API30/33 legacy vs API34/36 user-visible FGS modes checked at real OS level | `NOT_RUN` |
| `V3-N16-08` | Teardown leaves zero listener, background job, auth grants or lingering notification | `NOT_RUN` |

### N17 — Real authenticated Host/Native pairing

Baseline evidence: `SYNTHETIC_SIGNATURE_ONLY`. Target: `SECURITY_FOUNDATION`. V3 feature acceptance: **NOT_VERIFIED_V3**.

| Test ID | Required scenario (positive/negative/recovery) | Current V3 result |
| --- | --- | --- |
| `V3-N17-01` | Real Host process pairs with Native Keystore installation key via explicit on-device bootstrap approval | `NOT_RUN` |
| `V3-N17-02` | Host and Native validate mutual fresh challenge signatures/public-key pin with stable bound identity | `NOT_RUN` |
| `V3-N17-03` | Second unpaired Host and unrelated Android app fail authenticating, despite ADB/localhost access | `NOT_RUN` |
| `V3-N17-04` | User unpairs/revokes Host; all sessions immediately fail and trust store updates | `NOT_RUN` |
| `V3-N17-05` | Role-scoped read/write grants cannot be minted from model approved=true or ADB serial | `NOT_RUN` |
| `V3-N17-06` | Reinstall/reboot/Host key rotation, clock skew, nonce replay and restart produce correct re-pairing | `NOT_RUN` |
| `V3-N17-07` | Pairing and session E2E on each API30/33/34/36 with two independent Host processes | `NOT_RUN` |
| `V3-N17-08` | No private-key export, nonce leak, plaintext token logging, unauthenticated sensitive Tools | `NOT_RUN` |

### N18 — Cross-runtime durable lease and fencing

Baseline evidence: `SYNTHETIC_LEASE_ONLY`. Target: `SECURITY_FOUNDATION`. V3 feature acceptance: **NOT_VERIFIED_V3**.

| Test ID | Required scenario (positive/negative/recovery) | Current V3 result |
| --- | --- | --- |
| `V3-N18-01` | Authenticated Host A reserves lease at Native; Host B cannot perform competing fixture mutation | `NOT_RUN` |
| `V3-N18-02` | Independent OS fixture mutation audit shows only one authorized signed action executed | `NOT_RUN` |
| `V3-N18-03` | Wrong Host/boot/device/plan digest/fencing signature refused before executor | `NOT_RUN` |
| `V3-N18-04` | Owner cancels or loses lease, callback immediately rejects new actions | `NOT_RUN` |
| `V3-N18-05` | FGS Stop invalidates active leases and blocks stale Host retry | `NOT_RUN` |
| `V3-N18-06` | Crash/restart/dual process race and uncertain remote result preserve persisted high water | `NOT_RUN` |
| `V3-N18-07` | API30/33/34/36 concurrent Host processes and test fixture effect oracle exercised | `NOT_RUN` |
| `V3-N18-08` | Bounded TTL, durable journal/fsync, audit action IDs, no orphaned or duplicate write | `NOT_RUN` |

### N19 — Managed Android Device Owner extension

Baseline evidence: `ORDINARY_APK_UNSUPPORTED`. Target: `MANAGED_PROFILE_OPTIONAL`. V3 feature acceptance: **NOT_VERIFIED_V3**.

| Test ID | Required scenario (positive/negative/recovery) | Current V3 result |
| --- | --- | --- |
| `V3-N19-01` | Separate fresh account-free owned disposable AVD has DeviceOwner provisioned with test DPC under explicit test authority | `NOT_RUN` |
| `V3-N19-02` | DevicePolicyManager on same dedicated AVD independently verifies owner identity and supported policy probes | `NOT_RUN` |
| `V3-N19-03` | Normal Native APK without DeviceAdminReceiver or genuine owner role cannot self-provision | `NOT_RUN` |
| `V3-N19-04` | User/organization policy denial gives UNSUPPORTED and does not change existing owner | `NOT_RUN` |
| `V3-N19-05` | Managed test removes non-destructive scoped policy or resets exact ephemeral AVD in controlled cleanup | `NOT_RUN` |
| `V3-N19-06` | No user accounts, unrelated AVD, or device-admin takeover survives test rollback | `NOT_RUN` |
| `V3-N19-07` | API30/33/34/36 OEM/profile differences recorded on dedicated independent managed fixture when feasible | `NOT_RUN` |
| `V3-N19-08` | No wipeData/lockNow/silent package admin operation in ordinary Native flavor; release gate separated | `NOT_RUN` |

### N20 — Root/Bootloader/ROM lifecycle fallback

Baseline evidence: `ORDINARY_APK_UNSUPPORTED`. Target: `HOST_FALLBACK_PLATFORM_LIMIT`. V3 feature acceptance: **NOT_VERIFIED_V3**.

| Test ID | Required scenario (positive/negative/recovery) | Current V3 result |
| --- | --- | --- |
| `V3-N20-01` | Native reports platform-unsupported root/flash in production and offers verified Host read-only fallback status | `NOT_RUN` |
| `V3-N20-02` | Host independently detects authorized emulator boot/ADB identity and safe non-destructive maintenance probes | `NOT_RUN` |
| `V3-N20-03` | Unknown Host/serial and non-consented hardware cannot select device maintenance backend | `NOT_RUN` |
| `V3-N20-04` | Root/unlock/erase/flash user request returns explicit blocked and physical-owner approval requirement | `NOT_RUN` |
| `V3-N20-05` | Native offline/unbootable simulation switches status to UNAVAILABLE; no fantasy local recovery | `NOT_RUN` |
| `V3-N20-06` | Reconnect/reboot and stale Host response cannot reuse privileged approval across boot epoch | `NOT_RUN` |
| `V3-N20-07` | API30/33/34/36 emulator boot-state/Host read-only presence tested; OEM Fastboot remains hardware-only | `NOT_RUN` |
| `V3-N20-08` | No unrestricted su/fastboot-oem/shell Tool, raw partitions or physical device mutation performed | `NOT_RUN` |

## Cross-cutting real-world scenarios

| Test ID | Area | Required independent proof | Current result |
| --- | --- | --- | --- |
| `V3-XR-01` | SECURITY | Anonymous same-Android-app localhost client denied all sensitive tools, even if Origin/Host resembles trusted client | `NOT_RUN` |
| `V3-XR-02` | SECURITY | Host client identity must be mutually proved; ADB serial and USB forwarding alone confer no authorization | `NOT_RUN` |
| `V3-XR-03` | SECURITY | Pairing proof binds Native installation ID, Host key, OS boot epoch, exact user-selected target | `NOT_RUN` |
| `V3-XR-04` | SECURITY | Challenge nonce replay, expired timestamp, forged signer, wrong audience and clock rollback fail closed | `NOT_RUN` |
| `V3-XR-05` | SECURITY | Native Keystore signing private keys never exported or persisted in plaintext | `NOT_RUN` |
| `V3-XR-06` | SECURITY | Device and Host trust store deletion invalidates all sessions and must not auto-accept new key | `NOT_RUN` |
| `V3-XR-07` | SECURITY | Unexpected MCP Origin/Host/Forwarded headers and duplicate security headers denied | `NOT_RUN` |
| `V3-XR-08` | SECURITY | MCP tools/list and tools/call have consistent permission filtering, including race with revoke | `NOT_RUN` |
| `V3-XR-09` | CONCURRENCY | Two real Host processes compete for same Native write, exactly one fixture effect | `NOT_RUN` |
| `V3-XR-10` | CONCURRENCY | Host and Native own UI pipelines share one real lease and cannot write concurrently | `NOT_RUN` |
| `V3-XR-11` | CONCURRENCY | Action digest, request ID, nonce, fence and owner are checked immediately before Android operation | `NOT_RUN` |
| `V3-XR-12` | CONCURRENCY | Operation timeout after possible side effect reports UNCERTAIN and requires reconciliation | `NOT_RUN` |
| `V3-XR-13` | CONCURRENCY | Native process death between intent acceptance and effect preserves write-ahead journal semantics | `NOT_RUN` |
| `V3-XR-14` | CONCURRENCY | Host process death between commit and ACK does not silently replay a non-idempotent action | `NOT_RUN` |
| `V3-XR-15` | CONCURRENCY | User Stop/disable/unpair immediately fences all in-flight actions and sessions | `NOT_RUN` |
| `V3-XR-16` | CONCURRENCY | OS reboot invalidates ephemeral consent/session state and does not cause autostart | `NOT_RUN` |
| `V3-XR-17` | PERMISSION | MediaProjection positive and denied OS dialog results tested independently of mock status | `NOT_RUN` |
| `V3-XR-18` | PERMISSION | Android 14+ projection one-session consent/token re-use rejected by actual API | `NOT_RUN` |
| `V3-XR-19` | PERMISSION | Accessibility enabled through Settings UI with intended declared capability; disabling revokes promptly | `NOT_RUN` |
| `V3-XR-20` | PERMISSION | SAF selected provider READ vs WRITE grant, cancellation and process death observed | `NOT_RUN` |
| `V3-XR-21` | PERMISSION | PackageInstaller pending user action, approve/deny/cleanup observed with pinned APK | `NOT_RUN` |
| `V3-XR-22` | PERMISSION | Android foreground and background Activity launch policies enforced by OS not synthetic flags | `NOT_RUN` |
| `V3-XR-23` | PERMISSION | Other user/secure-window/password node remains protected in scope-limited UI operations | `NOT_RUN` |
| `V3-XR-24` | PERMISSION | Dangerous policy, device admin or OEM-maintenance grants never inferred from user prompt | `NOT_RUN` |
| `V3-XR-25` | DELIVERY | Four QEMU API30/33/34/36 devices identity-pinned and exclusively leased before mutable test | `NOT_RUN` |
| `V3-XR-26` | DELIVERY | Evidence includes exact Git commit/tree, signed APK hash, fixture hash and real API-level OS oracle | `NOT_RUN` |
| `V3-XR-27` | DELIVERY | Original 228 test case IDs mapped to exact executed test IDs and evidence, with no assumed pass | `NOT_RUN` |
| `V3-XR-28` | DELIVERY | Cross-runtime Host shared contract compatibility tested by both Host and Native consumers | `NOT_RUN` |
| `V3-XR-29` | DELIVERY | Real native MCP Java/Kotlin SDK wire contract Tools/list/Call verified before and after grants | `NOT_RUN` |
| `V3-XR-30` | DELIVERY | Non-E2E or not-run test cannot set PRODUCT_DONE; dynamic missing work creates traced blocker | `NOT_RUN` |
| `V3-XR-31` | DELIVERY | Unattended session interruption must preserve durable task state; no false background-completion claim | `NOT_RUN` |
| `V3-XR-32` | DELIVERY | Final product sign-off compares requested original feature list, runtime registry, ledger and evidence; zero silent exclusions | `NOT_RUN` |

## Mandatory original-suite reconciliation

At implementation stage G00 every one of the original `T-N0A-01` through `T-N8B-06` must have an immutable mapping to source test(s), execution layer (JVM/mock, Python static, real emulator harness, AndroidJUnitRunner, Native MCP E2E, Host↔Native E2E, physical authorized), exact run evidence and status. It is not enough that the file name or the Kotlin class exists. Currently many old tests validate precisely the disabled synthetic model. Keep their negative security checks, add positive V3 E2E. Any missing or blocked original requirement becomes an extra scheduled task with a reproducible failure and a designated closure test.

## Continuous gap/coverage loop

At the end of **every** implementation slice compare requested N01–N20 feature behaviors, code call graph, public `tools/list`, manifests, OS permissions, fixture effects, evidence matrix and open blockers. Every mismatch becomes `GAP-YYYYMMDD-Nxx-counter` with owner, severity, prerequisite, added implementation slice, named positive+negative tests, target API versions and release impact. Missing required E2E cannot be declared closed by an unrelated green test. Add slices dynamically; the initial G00–G35 backlog is a starting plan, not a maximum number of packages.

## Primary current evidence references

- [Previous Native capability ledger](https://github.com/grammy-jiang/android-mcp/blob/main/docs/native-capability-ledger.v1.json)
- [Original 228 cases](https://github.com/grammy-jiang/android-mcp/blob/main/docs/native-mcp-serial-test-cases-20261013.md)
- [Android instrumented tests (official)](https://developer.android.com/training/testing/instrumented-tests)
- [MediaProjection official](https://developer.android.com/media/grow/media-projection)
- [Accessibility official](https://developer.android.com/reference/android/accessibilityservice/AccessibilityService)
- [SAF official](https://developer.android.com/training/data-storage/shared/documents-files)
- [PackageInstaller official](https://developer.android.com/reference/android/content/pm/PackageInstaller)
