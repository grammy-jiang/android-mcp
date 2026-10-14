# Android Native MCP V3 — Live implementation checklist

Check one work package only after its scoped implementation, tests and
recorded evidence pass. An engineering checkbox does NOT certify a
product capability or an independent security review.

- Baseline work packages: **70**
- Engineering packages checked: **7**
- Remaining or partially complete packages: **63**
- Required GAP tasks still open: **27**
- Real product capabilities accepted: **0/20**
- New V3 real-E2E case receipts admitted: **0/192**
- Product state: **PRODUCT_INCOMPLETE**

The initial 70 items are not the finish line. New GAP tasks must
be added to the source ledger and rendered here immediately.

## E00 — Work packages

- [ ] **E00.a — Freeze the original full-lifecycle goal, 20 capabilities, release profiles, platform exclusions and real client acceptance; carry forward all open blocks.** — PARTIAL; dependencies: none
  - Six recovered original V3 baseline source files; original work-package JSON and delivery summary in ZIP remain unmaterialized
- [x] ~~E00.b — Map all 228 legacy T-Nxx test IDs to executable test identifiers, layer, code path, real-or-mock classification and current evidence.~~ — DONE_ENGINEERING; dependencies: E00.a
  - All 228 historical IDs mapped to 257 exact executable JVM/Python test methods, with actual local test XML results; real device acceptance stays open
  - Evidence: [evidence](E00B-LEGACY-228-TRACEABILITY-EVIDENCE-20261014.md)
- [x] ~~E00.c — Define and implement product-status taxonomy, capability closure ledger, independent OS-effect receipts and unforgeable PASS_REAL_E2E admission rules.~~ — DONE_ENGINEERING; dependencies: E00.b
  - Canonical two-role Ed25519 real-Android receipt policy, exact API/boot/MCP/OS callback/recovery tests and strict case matrix; actual external roots/OS witnesses remain GAP-N01-004
  - Evidence: [evidence](E00C-EVIDENCE-ADMISSION-POLICY-20261014.md)
- [x] ~~E00.d — Classify OS consent vs operator-scoped privilege vs independent external security review; record risk owners and fallback for every family.~~ — DONE_ENGINEERING; dependencies: E00.c
  - 20-family consent/operator/Native-lease/independent-review/fallback taxonomy; 12 adversarial tests and full local CI pass; no OS grant or external security approval claimed
  - Evidence: [evidence](E00D-AUTHORITY-RISK-REVIEW-20261014.md), [evidence](v3-authority-risk-register.json)

## E01 — Work packages

- [x] ~~E01.a — Add AndroidJUnitRunner and src/androidTest, dependency-locked instrumentation tasks and fixture-only build variants.~~ — DONE_ENGINEERING; dependencies: E00.c
  - Installed Native AndroidJUnitRunner APK; real Android API30/33/34/36 instrumentation verification; separate JVM simulation is not counted
  - Evidence: [evidence](E00-E01-EXECUTION-EVIDENCE-20261014.md)
- [x] ~~E01.b — Create pinned signed deterministic fixture APK(s), UI tree/gesture counter, MediaProjection known pixels, files/provider, and APK installer target.~~ — DONE_ENGINEERING; dependencies: E01.a
  - Signed counter/pixel/SAF/install-target fixtures plus non-exported FLAG_SECURE password fixture have real 12-test matrix on API30/33/34/36; product Native privacy E2E remains GAP-N07-002
  - Evidence: [evidence](E01B-SIGNED-FIXTURE-EVIDENCE-20261014.md), [evidence](GAP-N07-002-SECURE-FIXTURE-EVIDENCE-20261014.md)
- [ ] **E01.c — Implement OS UI consent harness for ActivityResult, Settings, SAF and PackageInstaller; permit ADB only as test driver/oracle.** — IN_PROGRESS; dependencies: E01.a, E01.b
  - Another exclusive E01.c developer worktree contains uncommitted real OS-consent tests; do not interfere or claim completion
- [x] ~~E01.d — Build independent genuine MCP Streamable HTTP client test runner and wire/contract oracle.~~ — DONE_ENGINEERING; dependencies: E01.a
  - Independent FastMCP Streamable HTTP real installed Native APK status/list/call/denial/Stop/restart checks across API30/33/34/36
  - Evidence: [evidence](E00-E01-EXECUTION-EVIDENCE-20261014.md)
- [ ] **E01.e — Implement AVD exclusive lease/preflight, exact boot/API/ABI/owner/nonce proof, fault injection, teardown and sanitized evidence.** — PARTIAL; dependencies: E01.a, E01.c, E01.d
  - Exclusive owned AVD markers, PID/ABI/boot checks and OS lock present; nonce, fault-injection and full teardown beyond E01.f remain unverified
- [ ] **E01.f — Add independent Android instrumentation and full MCP E2E runs to each affected PR CI; prove failures block the gate.** — PARTIAL; dependencies: E01.b, E01.c, E01.d, E01.e
  - Optional full local --v3-matrix passed with 48 on-device tests; affected PR CI enforcement and E01.c actual consent failure gates not yet all integrated

## E02 — Work packages

- [x] ~~E02.a — Run vetted transport library POC for confidential mutually authenticated Host↔Native session over explicit ADB forward/approved relay.~~ — DONE_ENGINEERING; dependencies: E01.d, E00.d
  - Separate installed Android Keystore test fixture verified real Host OpenSSL TLS mTLS in both directions on API36, with correct/anonymous/wrong certs; production N17 still NOT_DONE
  - Evidence: [evidence](E02A-ANDROID-KEYSTORE-MTLS-POC-20261014.md)
- [ ] **E02.b — Freeze versioned shared v2 pairing/auth/permission/grant/lease schema and compatibility; coordinate C0→Host→Native PR train with named writers.** — IN_PROGRESS; dependencies: E02.a
  - Another exclusive worktree has strict additive shared pairing/grant/lease schema candidate and active local quality checks; no unreviewed shared contracts changed here
- [ ] **E02.c — Wire AndroidKeyStore installation identity to user-visible local pairing UI and persistent owner binding with explicit fingerprint confirmation.** — OPEN; dependencies: E02.b
- [ ] **E02.d — Implement Native and Host mutually authenticated session lifecycle with key rotation, expiry, replay cache, revoke/unpair, OS boot/install epoch validation.** — OPEN; dependencies: E02.c
- [ ] **E02.e — Register real Kotlin MCP tools/list and tools/call with session-scoped read profile + request authorization on every call.** — OPEN; dependencies: E02.d, E01.d
- [ ] **E02.f — Run second Mac/Linux Host and same-Android-hostile-peer tests, certificate replacement, disconnect/reconnect, boot/key epoch and malformed HTTP.** — OPEN; dependencies: E02.d, E02.e
- [ ] **E02.g — Close N17 eight-case registry and XR01–XR08 security acceptance; record reviewed release scope S1.** — OPEN; dependencies: E02.a, E02.b, E02.c, E02.d, E02.e, E02.f

## E03 — Work packages

- [ ] **E03.a — Wire real Build/ABI/version and permission state Tool handlers from Android readers through safe authenticated Kotlin Gateway.** — OPEN; dependencies: E02.e, E01.f
- [ ] **E03.b — Implement real bounded BatteryManager, StatFs, DisplayMetrics and permitted connectivity snapshots as MCP Tool.** — OPEN; dependencies: E03.a
- [ ] **E03.c — Complete PackageManager current-user filtered visible-package & exact signer info Tool for only allowlisted fixture targets.** — OPEN; dependencies: E03.a, E01.b
- [ ] **E03.d — Connect genuine own-process and Service state/error diagnostics to paired MCP read profile.** — OPEN; dependencies: E03.a
- [ ] **E03.e — Implement optional permission-scoped sensor/system connectivity/notification status with capability discovery, not surveillance.** — OPEN; dependencies: E03.a
- [ ] **E03.f — Implement actual own-process CPU/memory/jank/crash metrics and bounded durable redacted diagnostic event exporter.** — OPEN; dependencies: E03.d
- [ ] **E03.g — Complete actual default status/service (Activity, FGS/permission/reboot/Stop) real MCP regression and legacy compatibility.** — OPEN; dependencies: E03.a, E03.d
- [ ] **E03.h — Close seven read-only feature families: full 8-case suite per capability with no orphaned Android adapter or fixed-deny fake.** — OPEN; dependencies: E03.a, E03.b, E03.c, E03.d, E03.e, E03.f, E03.g

## E04 — Work packages

- [ ] **E04.a — Wire user-launched ACTION_OPEN_DOCUMENT ActivityResult from native UI, opaque exact read-permission URI token and cancellation.** — OPEN; dependencies: E02.e, E01.c
- [ ] **E04.b — Implement bounded ContentResolver read from user-selected provider into checksum-verified app-private artifact.** — OPEN; dependencies: E04.a, E01.b
- [ ] **E04.c — Implement ACTION_CREATE_DOCUMENT WRITE grant path, bounded stream and honest provider non-atomic completion semantics.** — OPEN; dependencies: E04.b
- [ ] **E04.d — Close N11 eight cases + crosscut picker/revocation scenarios on four APIs, including Stop, restart and duplicate writes.** — OPEN; dependencies: E04.a, E04.b, E04.c

## E05 — Work packages

- [ ] **E05.a — Add purpose-scoped MediaProjection ActivityResult user consent broker and API34+ projection FGS type/profile.** — OPEN; dependencies: E02.e, E01.c
- [ ] **E05.b — Implement real VirtualDisplay/ImageReader bounded one-shot frame capture to opaque private artifact.** — OPEN; dependencies: E05.a, E01.b
- [ ] **E05.c — Handle MediaProjection onStop, screen lock, rotation, background restrictions, secure windows, buffer/FGS teardown and retention.** — OPEN; dependencies: E05.b
- [ ] **E05.d — Close N09 eight cases and crosscut projection cases across four APIs.** — OPEN; dependencies: E05.a, E05.b, E05.c

## E06 — Work packages

- [ ] **E06.a — Implement actual MediaProjection MediaCodec/MediaRecorder bounded recording pipeline and one-session grant.** — OPEN; dependencies: E05.c
- [ ] **E06.b — Add start/poll/stop/cancel recording Tool state and artifact caps, DRM/secure UI/privacy and resource cleanup.** — OPEN; dependencies: E06.a
- [ ] **E06.c — Close N10 eight cases with OS consent + actual decoder oracle across API matrix.** — OPEN; dependencies: E06.a, E06.b

## E07 — Work packages

- [ ] **E07.a — Resolve legitimate accessibility purpose, service declaration scope and independently reviewed user-consent constraints for debug and production profiles.** — OPEN; dependencies: E02.g, E00.d
- [ ] **E07.b — Add actual purpose-scoped AccessibilityService metadata and onServiceConnected/disabled lifecycle with real Settings enable UI.** — OPEN; dependencies: E07.a, E01.c
- [ ] **E07.c — Wire Android getRootInActiveWindow scoped authorized own fixture UI tree through paired Native Tool with secure-node redaction.** — OPEN; dependencies: E07.b, E01.b
- [ ] **E07.d — Close N07 eight cases and Settings disable/Stop/window-switch/restart paths on four APIs.** — OPEN; dependencies: E07.a, E07.b, E07.c

## E08 — Work packages

- [ ] **E08.a — Freeze Host↔Native action/grant/lease/fencing contract with exact digest/owner/boot epoch and durable acknowledgment states.** — OPEN; dependencies: E02.g, E00.d
- [ ] **E08.b — Persist Native OS-exclusive owner, monotonic fencing journal, prepared/dispatched/result uncertainty and bounded recovery.** — OPEN; dependencies: E08.a
- [ ] **E08.c — Integrate Host durable operation store and actual two independent Host processes with Native arbiter, no fake injected lease.** — OPEN; dependencies: E08.a, E08.b
- [ ] **E08.d — Close N18 eight cases and XR09–XR16 with two Host processes, FGS Stop, timeout-after-dispatch, reboot and recovery.** — OPEN; dependencies: E08.a, E08.b, E08.c

## E09 — Work packages

- [ ] **E09.a — Implement real Native Accessibility dispatchGesture and allowlisted node action executor; enforce current-window/gesture consent and signed action scope.** — OPEN; dependencies: E07.d, E08.d
- [ ] **E09.b — Implement UI node/window epoch, rotation/foreground checking and crash/Stop/uncertain dispatch fencing before effects.** — OPEN; dependencies: E09.a
- [ ] **E09.c — Close N08 eight cases including real OS gestures, two-Host contentions, user disable and rotation on all APIs.** — OPEN; dependencies: E09.a, E09.b

## E10 — Work packages

- [ ] **E10.a — Implement real Context/Activity-safe explicit Intent launch with exported component allowlist and foreground launch restrictions.** — OPEN; dependencies: E08.d, E02.g
- [ ] **E10.b — Protect duplicate launch and ambiguous state, onStop/revoke/locked screen, Android API 30–36 background differences.** — OPEN; dependencies: E10.a
- [ ] **E10.c — Close N12 eight cases and permission background launch crosscut with actual native startActivity.** — OPEN; dependencies: E10.a, E10.b

## E11 — Work packages

- [ ] **E11.a — Create separately signed pinned APK fixture and reviewed installer-only Android component/permission/flavor with real user action.** — OPEN; dependencies: E08.d, E01.b, E01.c
- [ ] **E11.b — Implement real PackageInstaller Session, pending-user-action intent, user-visible Android confirmation and final callback.** — OPEN; dependencies: E11.a
- [ ] **E11.c — Implement cancel/deny/uninstall fixture cleanup, failed stream, session abandonment, crash, foreground loss and ambiguous commit reconciliation.** — OPEN; dependencies: E11.b
- [ ] **E11.d — Close N15 eight cases and OS pending-user-action crosscut on API30/33/34/36.** — OPEN; dependencies: E11.a, E11.b, E11.c

## E12 — Work packages

- [ ] **E12.a — Audit persisted diagnostic/artefact retention, MIME/digest/quotas, redaction, crash logs and full cleanup across feature classes.** — OPEN; dependencies: E03.f, E04.d
- [ ] **E12.b — Prove revocations of notification, projection, accessibility, SAF and pairings during live calls stop operations and update capability status.** — OPEN; dependencies: E03.g, E05.d, E07.d
- [ ] **E12.c — Exercise Host alive / Native dead, Native alive / Host dead, both alive, both unavailable, airplane/USB disconnect and crash recovery.** — OPEN; dependencies: E02.g, E03.h, E08.d
- [ ] **E12.d — Close N01/N16 eight-case lifecycle/health evidence, Stop/port release, reboot and 24-hour controlled idle soak.** — OPEN; dependencies: E03.g, E12.a, E12.b, E12.c

## E13 — Work packages

- [ ] **E13.a — Produce separate fresh owner-proven account-free enterprise AVD and Test DPC experiment design with explicit controlled grant.** — OPEN; dependencies: E01.e, E00.d
- [ ] **E13.b — Close N19 eight-case DeviceOwner feasibility/unsupported behavior on dedicated lab AVD; optional reversible policy only if separately reviewed.** — OPEN; dependencies: E13.a
- [ ] **E13.c — Close N20 eight cases: ordinary APK unsupported, real authenticated Host read-only ADB/Fastboot mode detection when available, owner-supervised recovery runbook.** — OPEN; dependencies: E00.d, E12.c

## E14 — Work packages

- [ ] **E14.a — Execute all 160 feature scenario IDs with per-API positive/negative/Stop/crash/consent/cleanup evidence, or documented approved platform exclusion.** — OPEN; dependencies: E13.c, E13.b, E12.d, E11.d, E10.c, E09.c, E06.c
- [ ] **E14.b — Finish mapping all original 228 T-Nxx IDs to real executable test and evidence, plus 160 new cases.** — OPEN; dependencies: E00.b, E14.a
- [ ] **E14.c — Execute XR17–XR24 permission, user-consent, DPM and background limitations; independent OS denial and cleanup.** — OPEN; dependencies: E14.a, E12.b
- [ ] **E14.d — Run resource/concurrency soak, reboot/force-stop, two Hosts, duplicate requests, token expiration, binary output and redaction attacks.** — OPEN; dependencies: E14.a, E12.d
- [ ] **E14.e — Execute XR25–XR32 delivery, signed artifact, exact-tree, old-case mapping, gap closure and complete product comparison gates.** — OPEN; dependencies: E14.a, E14.b, E14.c, E14.d
- [ ] **E14.f — Run real intended ChatGPT MCP consumer (ordinary Chat if target) and independent Host clients with production transport and Tool schemas; certify per-profile release.** — OPEN; dependencies: E14.e

## E15 — Work packages

- [ ] **E15.a — Obtain explicit physical-device selection/owner consent, non-destructive test scope, exact model and no credential/data collection outside bounds.** — OPEN; dependencies: E14.f
- [ ] **E15.b — Execute only authorized physical read-only status/permission/FGS/connection compatibility matrix with operator supervising.** — OPEN; dependencies: E15.a
- [ ] **E15.c — Accept/deny each opt-in physical capability by feature-specific human OS consent and external security review; issue final signed release scope.** — OPEN; dependencies: E15.a, E15.b

## Mandatory GAP remediation tasks

- [ ] **GAP-N01-001** — OPEN: No attested complete real Native MCP → authorized Android API → independent OS effect path
  - Next: Implement real authenticated Native MCP tool and OS side effect; pass positive, refusal, Stop, crash, retry and per-API tests
- [ ] **GAP-N02-001** — OPEN: No attested complete real Native MCP → authorized Android API → independent OS effect path
  - Next: Implement real authenticated Native MCP tool and OS side effect; pass positive, refusal, Stop, crash, retry and per-API tests
- [ ] **GAP-N03-001** — OPEN: No attested complete real Native MCP → authorized Android API → independent OS effect path
  - Next: Implement real authenticated Native MCP tool and OS side effect; pass positive, refusal, Stop, crash, retry and per-API tests
- [ ] **GAP-N04-001** — OPEN: No attested complete real Native MCP → authorized Android API → independent OS effect path
  - Next: Implement real authenticated Native MCP tool and OS side effect; pass positive, refusal, Stop, crash, retry and per-API tests
- [ ] **GAP-N05-001** — OPEN: No attested complete real Native MCP → authorized Android API → independent OS effect path
  - Next: Implement real authenticated Native MCP tool and OS side effect; pass positive, refusal, Stop, crash, retry and per-API tests
- [ ] **GAP-N06-001** — OPEN: No attested complete real Native MCP → authorized Android API → independent OS effect path
  - Next: Implement real authenticated Native MCP tool and OS side effect; pass positive, refusal, Stop, crash, retry and per-API tests
- [ ] **GAP-N07-001** — OPEN: No attested complete real Native MCP → authorized Android API → independent OS effect path
  - Next: Implement real authenticated Native MCP tool and OS side effect; pass positive, refusal, Stop, crash, retry and per-API tests
- [ ] **GAP-N08-001** — OPEN: No attested complete real Native MCP → authorized Android API → independent OS effect path
  - Next: Implement real authenticated Native MCP tool and OS side effect; pass positive, refusal, Stop, crash, retry and per-API tests
- [ ] **GAP-N09-001** — OPEN: No attested complete real Native MCP → authorized Android API → independent OS effect path
  - Next: Implement real authenticated Native MCP tool and OS side effect; pass positive, refusal, Stop, crash, retry and per-API tests
- [ ] **GAP-N10-001** — OPEN: No attested complete real Native MCP → authorized Android API → independent OS effect path
  - Next: Implement real authenticated Native MCP tool and OS side effect; pass positive, refusal, Stop, crash, retry and per-API tests
- [ ] **GAP-N11-001** — OPEN: No attested complete real Native MCP → authorized Android API → independent OS effect path
  - Next: Implement real authenticated Native MCP tool and OS side effect; pass positive, refusal, Stop, crash, retry and per-API tests
- [ ] **GAP-N12-001** — OPEN: No attested complete real Native MCP → authorized Android API → independent OS effect path
  - Next: Implement real authenticated Native MCP tool and OS side effect; pass positive, refusal, Stop, crash, retry and per-API tests
- [ ] **GAP-N13-001** — OPEN: No attested complete real Native MCP → authorized Android API → independent OS effect path
  - Next: Implement real authenticated Native MCP tool and OS side effect; pass positive, refusal, Stop, crash, retry and per-API tests
- [ ] **GAP-N14-001** — OPEN: No attested complete real Native MCP → authorized Android API → independent OS effect path
  - Next: Implement real authenticated Native MCP tool and OS side effect; pass positive, refusal, Stop, crash, retry and per-API tests
- [ ] **GAP-N15-001** — OPEN: No attested complete real Native MCP → authorized Android API → independent OS effect path
  - Next: Implement real authenticated Native MCP tool and OS side effect; pass positive, refusal, Stop, crash, retry and per-API tests
- [ ] **GAP-N16-001** — OPEN: No attested complete real Native MCP → authorized Android API → independent OS effect path
  - Next: Implement real authenticated Native MCP tool and OS side effect; pass positive, refusal, Stop, crash, retry and per-API tests
- [ ] **GAP-N17-001** — OPEN: No attested complete real Native MCP → authorized Android API → independent OS effect path
  - Next: Implement real authenticated Native MCP tool and OS side effect; pass positive, refusal, Stop, crash, retry and per-API tests
- [ ] **GAP-N18-001** — OPEN: No attested complete real Native MCP → authorized Android API → independent OS effect path
  - Next: Implement real authenticated Native MCP tool and OS side effect; pass positive, refusal, Stop, crash, retry and per-API tests
- [ ] **GAP-N19-001** — OPEN: No attested complete real Native MCP → authorized Android API → independent OS effect path
  - Next: Implement real authenticated Native MCP tool and OS side effect; pass positive, refusal, Stop, crash, retry and per-API tests
- [ ] **GAP-N20-001** — OPEN: No attested complete real Native MCP → authorized Android API → independent OS effect path
  - Next: Demonstrate scoped read-only Host fallback without Root or ROM commands
- [ ] **GAP-N17-002** — OPEN: Real mutual TLS POC is confined to AndroidJUnitRunner test fixture; actual installed Native MCP listener remains unauthenticated local-status-only
  - Next: Integrate reviewed mTLS with live Native MCP tools/list/call, mandatory per-session scope rechecks and independent Host process test
- [ ] **GAP-N17-003** — OPEN: TLS 1.2 EC signing tested only API36 test-only AVD; four-API TLS 1.3/rotation/replay/crash-recovery evidence absent
  - Next: Prove TLS1.2/1.3 applicability, lifecycle, cleanup, rotation, revoked/replayed credentials and independent APK effects on API30/33/34/36
- [ ] **GAP-N17-004** — OPEN: Short-lived one-test pinned identities provisioned by instrumentation arguments are not genuine operator-enrolled Host pairing
  - Next: Implement Android user-visible Host public-key fingerprint confirmation, secure owner identity storage, revoke/unpair, and independent production security review
- [ ] **GAP-N01-002** — OPEN: 228 test selectors are mapped to files and JVM/Python XML, but every test body is not yet independently checked for asserting all original requirement semantics
  - Next: Review each of 228 original historical specifications against executable assertions; flag fake/missing semantics and add dedicated behavioral tests per uncovered case
- [ ] **GAP-N01-003** — OPEN: Original machine-readable 70-work-package registry and V3 delivery summary inside approved ZIP remain unavailable as original bytes; derived prose index is not the missing original
  - Next: Recover and hash the two original documents from authorized Library/ZIP; reconcile approved dependencies and acceptance metadata against the derived 70-package index without manufacturing originals
- [ ] **GAP-N07-002** — OPEN: Secure/password fixture exists and 4-API instrumentation passes; independent OS accessibility/screenshot exclusion plus actual Native MCP secure-node refusal and privacy recovery remain missing
  - Next: Complete independent 4-API secure/password UI tree oracle and real paired Native AccessibilityService/MediaProjection refusal; verify Stop, revocation, crash and no password or secure pixel leak
- [ ] **GAP-N01-004** — OPEN: External oracle/reviewer signing identities, actual Android OS-effect receipt collection, verified trusted key rotation and replay database are not yet integrated into an independently operated release gate
  - Next: Provision externally approved pinned witness/reviewer public keys through a reviewed configuration; instrument true Native MCP→Android callback→independent fixture receipt; test exact source/APK/boot, expiry, revoked signer and replay across all four API levels

## Repeatable completion workflow

Investigate; write behavioral RED tests; implement actual Android API;
run real MCP plus independent OS oracle; check denial, Stop, death,
retry and cleanup; add GAP tasks for anything missing; integrate a
passing PR; rerun post-merge checks; tick the package only when
its scoped acceptance conditions are satisfied; then select the
next dependency-ready package.

Regenerate with python3 scripts/native_v3_todo.py --repo .
