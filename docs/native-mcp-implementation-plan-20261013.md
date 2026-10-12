# Android Native MCP implementation plan — reviewed serial execution v2

**Updated:** 2026-10-13 Australia/Sydney.
**Scope:** the **Android-device Kotlin Native MCP server only**.
**Plan owner:** one dedicated Native development ChatGPT conversation, sole
implementer, tester, reviewer and Git integrator for its own worktree.
**Repository:** `grammy-jiang/android-mcp`; permanent integration branch
`main` (never create a new long-lived `master`).
**Reviewed base:** `950ff6d6430ad9a71d6d6cb269be0554aa515a21`;
**always fetch and verify current `origin/main`** before each slice.
**Status:** executable for safe N0 work; sensitive Android operations remain
disabled until the actual Android permission, identity and review gates pass.

**Required companion records:** [228 exact prospective test cases](native-mcp-serial-test-cases-20261013.md),
[self-review of v1](native-mcp-plan-review-20261013.md),
[copy-ready single-chat handoff](native-mcp-serial-session-handoff-20261013.md),
[full capability catalog](android-toolchain-capability-catalog-20261012.md),
[Native N3 foreground lifecycle](native-foreground-n3.md),
[Host/Native coordination draft](host-native-coordination.md),
and [shared integration schedule](host-native-integration-schedule-20261013.md).
The separate [Host v2 plan](host-mcp-implementation-plan-20261013.md)
has a different owner and must not be executed in the Native chat.

## 1. Review findings and corrections to v1

| v1 weakness | v2 resolution | Impact |
| --- | --- | --- |
| Roughly 20 work packages mixed permission design, MCP registration, capture or execution | **38 atomic Native packages** N0.a–N8.b, each a standalone PR | Stable test/merge boundary and rapid main integration |
| No per-package actionable test names | **6 numbered test cases per package (228 total)**, plus baseline invariants | Explicit red→green development and mandatory negative cases |
| Screenshot/recording and file exchange appeared before secure artifact lifetime | N0.e private artifact store and lifecycle/cancel model first | Retention, size and replay safety designed before sensitive capture |
| Local loopback treated as a harmless status service but future Tools need authentication | N0.b caller/Origin threat case and default-denied sensitive Tool profile before later capabilities | Same-device malicious-app access must not be overlooked |
| MediaProjection and Accessibility were bundled with enabling capabilities | Separate feasibility, consent, bounded read and action plans; denied by default until genuinely authorized | No accidental Android permissions or unreviewed capture |
| Native foreground lifecycle could be conflated with authenticated Host/Native leases | N0.c process-local lifecycle, N6 durable cross-process authenticated fencing | Distinct security layers and failure modes |
| PRs waited for 13:00/18:00 while one Chat session could keep working | **Merge each passing PR immediately**, then start next from new main | Daily windows only for cross-stream coordination |
| Human review/physical permissions could block an absent-owner session | Use deterministic fake/AVD evidence and **inert/plan-only** slices, then move forward | Never silently promote absent permission to approval |
| Android 11/13/14/16 behavior was a broad acceptance item | Explicit API30/33/34/36 emulator cases at each affected lifecycle/permission slice | Test real lifecycle, user denial, SDK behavior |
| "Implemented" could mean simulated permissions or unexecuted device features | Track `merged_verified`, `inert_merged`, `plan_only`, `blocked` independently | No false hardware/permitted-feature claims |

This Native v2 plan supersedes only the Native **implementation backlog**;
existing architecture, stable shared v1 wire schema, Host v2 and running
Native process remain unchanged until separate implementation PRs.

## 2. Current source/baseline (evidence, not assumed capabilities)

At the reviewed `main`, Native Kotlin/Ktor service exposes only
`device_status` via `LocalMcpGateway` and
`NativeLocalStatus`. The response is minimal local health data;
Accessibility observe/act and privileged capabilities remain false.
N1 Activity and N3 explicit user-started foreground service already
exist. They share `127.0.0.1:38765/mcp`, with a **process-local**
port-owner guard; the listener is **not remote-authenticated** and
there is **no implemented Host/Native distributed lease**.

Current reviewed production APK permissions (from
`android/app/src/main/AndroidManifest.xml`): INTERNET,
FOREGROUND_SERVICE, FOREGROUND_SERVICE_SPECIAL_USE and
POST_NOTIFICATIONS. `minSdk=30`, `targetSdk=36`,
Kotlin MCP SDK 0.14.0, Ktor 3.4.3, Gradle 9.6.0, AGP 9.4.0,
JDK 17. Do **not** infer that N3 has user-approved
MediaProjection, Accessibility, package-wide visibility,
silent install, Root or public network support.

`PR #39` may be concurrently owned by the Native development
stream; **read its actual state on resumption**. This planning
document makes no claim that PR #39 is merged or superseded.

## 3. Rules for the single Native ChatGPT development session

1. Only **one active Native work package** at any moment. Never
   delegate feature implementation to Codex, Claude, another ChatGPT
   agent or a concurrent local worker. Test subprocesses within
   the current package are permitted.
2. For each Nxx slice: read newest `main`, make a fresh
   **exclusive** Native worktree/branch; add six test cases first,
   record red evidence, implement the minimum safe code, pass
   targeted tests and all required Kotlin/Android/HTTP checks.
   Self-review the actual diff and package manifest; publish a
   narrow PR and **merge to `main` immediately when valid**.
   Confirm exact-head and merged Git tree, record merge SHA,
   then create the next branch from fresh main.
3. One ChatGPT developer may decide ordinary design and code choices
   without asking the sleeping user, preserving backward
   compatibility and conservative permissions. Do **not** invent
   approval or claim that self-review is independent security review.
4. If a permission, Host/shared protocol, device or external tester
   is unavailable, implement **blocked/inert/plan-only** contracts
   with real negative tests, record `EXECUTION_DEFERRED`, and
   continue to the next *independent* safe slice. Do not silently
   register sensitive working Tools on an untrusted local endpoint.
5. No user absence allows automatic granting of Accessibility,
   MediaProjection, Device Owner, PackageInstaller confirmation,
   Bootloader/Root, external port exposure, Google licenses
   or physical Android APK install/uninstall/wipe/reboot.
   Dedicated emulator APK install in a **preverified disposable
   test AVD** may be run by an explicitly scoped test script
   with installed SDK and approved licenses.
6. Preserve Native user's existing worktree, `android/**`
   ownership, and Host's `host/**` ownership. Do not
   modify a shared `contracts/**` file without a separately
   versioned, two-stream-tested contract proposal. No live Host/
   Native pairing is implied merely by being in the same monorepo.
7. If a required test fails, investigate, repair and rerun;
   if a required external gate stays unavailable, mark blocked
   with exact log/SHA and move to a disjoint safe package. Do
   **not** bypass verification to meet the time schedule.
8. The ChatGPT session works while its active tools remain
   available. The Markdown plan **does not schedule or guarantee
   background work for eight hours**. Leave durable GitHub
   checkpoints before its execution environment ends.
9. GitHub Hosted Actions are blocked by billing and user
   wants **zero paid runners**. The actual local CI evidence
   is authoritative; unstarted GitHub jobs are never green.

**Status taxonomy:** `not_started`, `red`,
`in_progress`, `test_failed`, `blocked`,
`ready_to_merge`, `merged_verified`,
`inert_merged`, `plan_only`,
`excluded_by_platform`. A disabled emulator mock
does not count as production-permitted screen capture.

## 4. Dependency order: one serial chain with safe exit paths

```text
N0: minimal v1 contract → local caller/Origin denial policy
  → Activity/FGS and port-owner lifecycle → permission model
  → private bounded artifact store
    ↓
N1: public-safe Build/ABI snapshot → system state
  → own-app/FGS health → permission-aware Tool profiles
    ↓
N2: visible package inventory → targeted PackageManager lookup
  → Intent launch planning (not execution)
    ↓
N3: MediaProjection consent feasibility → one-shot capture
  → bounded screen recording → Accessibility policy feasibility
  → opt-in, scoped UI tree read
    ↓
N4: typed UI action plans → disposable-emulator instrumentation
  → SAF grant boundary → user-selected export/import
  → optional sensor/network/notification capability
    ↓
N5: own-app crash reporting → self process performance
  → durable bounded event delivery → Host fallback health evidence
    ↓
N6: private installation identity → fake signed challenge/Origin
  → persistent Native fencing → dual-Host simulation
  → live mutation stays DISABLED
    ↓
N7: PackageInstaller consent plan → disposable emulator user flow
  → explicit approved app launch → user-visible service recovery
    ↓
N8: managed-device (Device Owner) feasibility → deny Root/ROM
  and delegate approved recovery planning to Host
```

In practice the **authentication readiness gate may block exposure
of N1/N2/N3 sensitive data**. Continue their pure application
API services and denied public Tool contracts; do not
skip the gate or expose broader Android data merely to keep
the serial schedule moving. A stage may conclude with
`inert_merged` plus an honest deferred activation record.

## 5. Atomic package/PR schedule (38 slices / nine stages)

One row is **one independent PR merge unit**. Each one has six named
test cases in the [Native test specification](native-mcp-serial-test-cases-20261013.md).
`M-Nx.y` is the post-green merge receipt, not a suggestion to
wait for a clock. PR size should stay small (one Tool/API boundary).
The listed Tool names are candidates pending actual Kotlin SDK
`tools/list`/`tools/call` verification.

| # | Slice and priority | Owned deliverable / intended Tool or internal service | Dependency and safety boundary | Tests | Merge receipt |
| --- | --- | --- | --- | --- | --- |
| 01 | **N0.a** P0 | Freeze existing `device_status` wire v1 and N2/N3 loopback catalog | Baseline; no new permission or sensitive output | T-N0A | M-N0.a |
| 02 | **N0.b** P0 | Local caller/Origin threat model and deny-by-default sensitive Tool guard | No presumption localhost means authenticated; no new listener | T-N0B | M-N0.b |
| 03 | **N0.c** P0 | Extract or harden Activity/FGS/port-owner lifecycle state and shutdown proof | Process-local guard only, preserve notification Stop | T-N0C | M-N0.c |
| 04 | **N0.d** P0 | Typed Android permission/readiness model; current manifest fixture | Actual grants and Android API limits; no permission additions | T-N0D | M-N0.d |
| 05 | **N0.e** P0 | Private bounded Native artifact handle/store and owner-lifecycle cleanup | Before screenshots, recordings or SAF; app sandbox only | T-N0E | M-N0.e |
| 06 | **N1.a** P0 | Public-safe system Build/ABI/API snapshot service | No device serial/advertising ID; gate MCP publication | T-N1A | M-N1.a |
| 07 | **N1.b** P0 | Battery, storage, display and connectivity snapshot from allowed SDK APIs | Strict Android permissions, unavailable rather than guessed | T-N1B | M-N1.b |
| 08 | **N1.c** P0 | Own-app/FGS process health, status/error model | No app accounts/tokens/crash secret leakage | T-N1C | M-N1.c |
| 09 | **N1.d** P0 | Profile-scoped `tools/list` and typed output Schema/metadata | No sensitive visibility without N0.b authorization | T-N1D | M-N1.d |
| 10 | **N2.a** P1 | PackageManager **visible apps only** contract | Android 11+ visibility filtered; no QUERY_ALL_PACKAGES grant | T-N2A | M-N2.a |
| 11 | **N2.b** P1 | Targeted package info/permissions with explicit not-visible status | No privileged cross-user inventory | T-N2B | M-N2.b |
| 12 | **N2.c** P1 | Explicit Intent/app launch resolution **plan only** | No implicit intents, no background launch bypass | T-N2C | M-N2.c |
| 13 | **N3.a** P2 | MediaProjection consent/readiness/FGS-type design and inert adapter | No silently granted capture/permission, API34+ gates | T-N3A | M-N3.a |
| 14 | **N3.b** P2 | One-shot screen capture bounded artifact, only if legitimately consented | Else denied; private artifact, no covert capture | T-N3B | M-N3.b |
| 15 | **N3.c** P2 | Screen recording stream/duration and cancellation contract | MediaProjection user stop/revocation, no orphan session | T-N3C | M-N3.c |
| 16 | **N3.d** P2 | Accessibility eligibility/user activation policy, default-off adapter | No auto AccessibilityService enablement or sideload workaround | T-N3D | M-N3.d |
| 17 | **N3.e** P2 | Focused accessibility/UI hierarchy read via approved service | No password/secure-window leakage, deny if disabled | T-N3E | M-N3.e |
| 18 | **N4.a** P2 | Typed tap/scroll/swipe/key **plan** with window/node anchoring | No execution in production without fresh authorization | T-N4A | M-N4.a |
| 19 | **N4.b** P2 | Disposable-emulator UI Automator/instrumented action verification | Emulator-only; physical UI action remains denied | T-N4B | M-N4.b |
| 20 | **N4.c** P2 | Storage Access Framework URI grant and document-picker boundary | No all-storage file manager or forged URI grant | T-N4C | M-N4.c |
| 21 | **N4.d** P2 | User-selected SAF file export, encrypted/private artifact handle | Consent/URI TTL and size cap | T-N4D | M-N4.d |
| 22 | **N4.e** P2 | User-selected SAF file import, atomic write plan | Deny unauthorized destination, no other-app data access | T-N4E | M-N4.e |
| 23 | **N4.f** P2 | Scoped optional sensor/network/notification **status** | Separate permission matrix, no surveillance feed | T-N4F | M-N4.f |
| 24 | **N5.a** P2 | Native own-app crash/ANR self-diagnostics | No global Logcat, bounded local data only | T-N5A | M-N5.a |
| 25 | **N5.b** P2 | Native self CPU/memory/performance counters | No system-wide profiler/root claim | T-N5B | M-N5.b |
| 26 | **N5.c** P2 | Durable native diagnostic event IDs, retention and cancellation | No reliance on MCP session, bounded queues | T-N5C | M-N5.c |
| 27 | **N5.d** P2 | Host unavailable/Native unavailable fallback health matrix | Read-only, provenance and explicit uncertainty | T-N5D | M-N5.d |
| 28 | **N6.a** P3 | Private Native installation identity/key rotation model | Never expose signing private key; no live pairing | T-N6A | M-N6.a |
| 29 | **N6.b** P3 | Signed challenge/response + pairing identity **fake adapter** | No Host-identity-by-serial, replay/Origin denial | T-N6B | M-N6.b |
| 30 | **N6.c** P3 | Durable Native lease high-water mark and boot epoch | Survives FGS restart; stale fence fails closed | T-N6C | M-N6.c |
| 31 | **N6.d** P3 | Two-Host + Native lease contention/retry simulator | Shared contract additive and ACK later; no active mutation | T-N6D | M-N6.d |
| 32 | **N6.e** P3 | Sensitive mutating Tool profile **disabled** by default | Real device changes BLOCKED until audited grants/independent review | T-N6E | M-N6.e (inert) |
| 33 | **N7.a** P3 | PackageInstaller / scoped install request **plan** | User-mediated consent, no silent install | T-N7A | M-N7.a |
| 34 | **N7.b** P3 | PackageInstaller consent on owned disposable emulator | Emulator-only test, no physical device auto-install | T-N7B | M-N7.b |
| 35 | **N7.c** P3 | Explicit allowed Intent/app launch, gated execution | No arbitrary cross-package launch or background start bypass | T-N7C | M-N7.c |
| 36 | **N7.d** P3 | User-visible Native service stop/reconnect/recovery | No automatic boot receiver or hidden resurrection | T-N7D | M-N7.d |
| 37 | **N8.a** P4 | Managed-device/Device Owner feasibility and `unsupported` surface | No provisioning, admin takeover or policy changes | T-N8A | M-N8.a |
| 38 | **N8.b** P4 | Root/bootloader/ROM gap map and Host-safe fallback **plan only** | No `su`, raw shell, flashing or silent recovery | T-N8B | M-N8.b |

**38 ordered PR slices, 228 prospective numbered tests.**
Do not combine multiple privilege/permission boundaries into one
large PR. If a slice is blocked solely by missing real-user consent
or Android platform policy, merge only the truthful **disabled/inert**
implementation with demonstrated denial behavior; executable scope
remains deferred and must not count as granted.

## 6. Native tests required for EVERY package, not merely at stage end

Each Nxx row has six **specific numbered** cases in
[the 228-case Native test matrix](native-mcp-serial-test-cases-20261013.md).
Every PR must also preserve all current Native tests and:

1. **Test-first evidence.** A dedicated named Kotlin/JUnit or Python
   test for each relevant Nxx case. Demonstrate a meaningful failing
   behavior assertion before implementation; a syntax/import error is
   not red-phase proof. H0-like characterization tests may prove
   mutation sensitivity on a temporary fixture without weakening
   current production behavior.
2. **Kotlin + MCP contract.** Run `bash scripts/check-native.sh`:
   strict Gradle integrity/lock verification, Kotlin/JVM protocol
   and lifecycle tests, Python↔Kotlin MCP/HTTP integration and
   `android/tests` safety fixtures. New public Tool cases must
   check actual `tools/list`, `tools/call`, input/output
   schema/version, metadata and typed denial results.
3. **Actual Android APK.** Run `bash scripts/check-native-apk.sh`
   with an **installed** JDK17 + Android SDK36. Verify Gradle
   `assembleDebug`, Android Lint, APK signing and **actual
   built manifest** permissions (not just source XML).
   Any new Android permission must have a separately reviewed
   versioned allowlist and Android API/FGS-type test before
   the permission can be included in an enabled APK.
4. **Repository-wide local runner.** Run
   `bash scripts/check-native-local-ci.sh` on the MacBook
   at the **exact PR HEAD**, with `pre-commit` and Android
   dependency integrity; run Host baseline as required for
   shared interface changes. Never upgrade/downgrade dependencies
   to hide test failures or pay for GitHub Actions.
5. **Disposable Android emulator.** For lifecycle, permissions,
   PackageManager, FGS, MediaProjection, Accessibility, SAF, UI,
   intents and PackageInstaller, run explicit **API30, API33,
   API34, API36** emulator acceptance when a verified AVD is
   available, using `verify_native_api_matrix.py` or
   per-feature instrumentation after validating **every device is
   an exact QEMU emulator, booted and the expected API**. The
   runner must abort before installing any APK if it sees
   a physical target. If the four-API matrix is required but
   unavailable, mark execution **blocked**, do not claim it passed.
6. **Permission and privacy negative cases.** Hostile local
   caller/Origin, other-app process, missing notification consent,
   denied Android runtime grant, process/Activity/FGS death,
   second listener, port binding, stale permission, locked screen,
   sensitive output, oversized file, replay and duplicated Tool
   requests have explicit fail-closed assertions where relevant.
   Never use real user/device secrets in fixtures.
7. **Resource/concurrency cases.** Timeouts, stopped FGS, revoked
   capture session, Android process kill, duplicate request IDs,
   restart/port ownership race, slow subscriber/backpressure,
   disk full and cleanup must leave no leaked listener, artifact,
   unbounded queue or child process.
8. **Truthful limitations.** Kotlin/JVM and synthetic tests are not
   a real APK/AVD/physical tablet certification. Report each
   test layer separately as `passed`/`failed`/`blocked`/
   `not_run`. Root/Bootloader, Accessibility and
   MediaProjection permission gates must not be called passed
   without actual approved APIs and consent.
9. **Self-review and merge.** Review actual PR diff, Manifest,
   permission descriptions, network binding, Native/Host
   ownership, public Tool compatibility and audit/cleanup.
   Genuine **independent security review** remains a separate
   requirement for privilege-enabling changes. Safe
   non-enabling code can merge after real configured gates
   pass and a truthful review labelled `self_review`.
10. **Exact Git integration.** Recheck remote `main` and PR
    head/base, merge small **owned** PR immediately after green;
    verify post-merge Git tree equals the tested integrated tree,
    rerun selected Native/Host smoke and record merged SHA.
    Native and Host do not force-push/rebase each other's work.
    Clock windows in shared docs are communication checkpoints,
    never a hard wait for one serial Chat.

### Hard fail-closed gates (no owner replies during routine work)

| Scenario | Autonomous safe continuation | Missing evidence must not enable |
| --- | --- | --- |
| Normal Kotlin contract question | Choose conservative compatible schema, record tests and commit | Inventing Native policy approval |
| Unauthenticated localhost loopback and sensitive read planned | Create denied Tool fixture, local caller-guard test and inert adapter | Registering public screenshot/PackageManager/capture Tools |
| Android 11–16 API-specific behavior uncertain | Write fake/AVD-version tests; target supported API or return unsupported | Ignoring user consent/Platform restrictions |
| Missing Emulator image/AVD or required OS permission | Record blocked matrix step; proceed to independent non-enabling package | Calling JVM mock a real Android permission test |
| Permission review/MediaProjection/Accessibility confirmation absent | Keep feature disabled or opt-in manual design, test denials | Programmatic permission grant or userless capture |
| Host pairing/shared Schema absent | Build fake signed handshake and fencing simulator, no live bridge | Treating ADB serial as installation identity |
| Native crashed or user stopped FGS | Return unavailable/uncertain, honor explicit user stop | Silent restart, boot receiver, promotion to privileged Host fallback |
| Physical app install/erase, root/bootloader, managed Device Owner | Plan, simulate and mark deferred | Executing irreversible real-device action |
| GitHub Actions unavailable from user budget | Run local authenticated Mac/JVM/SDK and gated AVD tests | Paying for hosted runners or marking unstarted jobs green |
| Session/tool access ends | Push a safely isolated checkpoint/PR with exact SHA and next action | Promising to continue indefinitely in background |

## 7. Git and test evidence chain: serial, immediate and reversible

```text
READ latest main / Native PR #39 / Native-owned worktree state
  ↓
SELECT next Nxx with no verified merge receipt
  ↓
CREATE exclusive short-lived Native worktree/branch from current main
  ↓
WRITE six named negative+positive tests → prove RED → implement GREEN
  ↓
RUN JVM/Kotlin/Python baseline, actual signed APK/Lint/permissions,
     relevant preverified API30/33/34/36 emulator cases, safety gates
  ↓
SELF-REVIEW actual Tool registration, Origin, Android grants, effect scope
  ↓
If safe & green → PR at exact HEAD → immediate merge main
                    ↓
           Verify merged source Git tree and smoke
                    ↓
               Fetch main and NEXT package
If blocked → checkpoint exact code/evidence without enabling,
             choose next independent safe package; do not merge unsafe code
```

The worktree `~/Projects/android-mcp-native-setup` is owned by a
separate Native session and **must be inspected but never reset or
edited by the Host reviewer**. For a new Native developer chat, choose
an exclusive unused worktree from latest main. A merged old branch
may remain as historical evidence; do not call it a pending merge.

Per-package PR receipt must record: Nxx ID, N01–N20 IDs, exact base/HEAD,
owned files, public Tool and permission/Origin state, test IDs and red
evidence, Kotlin/JVM results, actual APK/Lint/manifest evidence,
four-API matrix results or honest blocked reason, whether any physical
Android device was touched, self-review versus actual independent
security approval, merged main SHA/tree and rollback path.

Do not keep one large long-lived `feature/native-*` branch.
Do not change `host/**` in the Native workstream. Shared v2
contract design requires **independently named writer** and Host/Native
test agreement. Inactive ChatGPT sessions cannot automatically
attend 09:00/13:00/18:00 merge windows; successful test completion
is the immediate merge trigger.

## 8. Early execution milestones, not guaranteed calendar promises

| Serial order | Work goal | PR result and merge condition |
| --- | --- | --- |
| N0.a | Freeze existing Native `device_status`, Activity/FGS HTTP and denial behavior | Test-first, merge into current main immediately after gates |
| N0.b | Show insecure caller/Origin cannot access any new sensitive capability | Default denied; merge as inert security foundation |
| N0.c | Strengthen process-local port owner, notification stop and shutdown verification | Must pass emulator lifecycle cases before merge |
| N0.d | Define granted/denied/unknown Android permissions across API levels | Read-only, no new Manifest permission |
| N0.e | Private artifact state, bounded storage/retention | Required before screen capture and SAF transfer |
| N1+ | Safe system data and self-health if auth gate permits, otherwise internal/denied status | Each short PR merged independently; no hard human checkpoint |
| N2–N5 | Package visibility, UI/media permission plans, SAF and app telemetry | Separate consented emulator evidence and blocked execution states |
| N6–N8 | Inert pairing/lease, PackageInstaller consent plans, managed-device gap | No physical mutation, Root, remote listener or flash enabled |

**A new Native session should begin N0.a immediately after this
v2 planning PR merges,** not replan indefinitely or ask the sleeping
user to choose routine details.

## 9. Completion accounting and catalog coverage

Every Native ID `N01–N20` must appear exactly once in the
capability ledger with assigned package(s), real source/API,
required Android manifest/runtime permission, API version,
public Tool or private adapter, sensitive data scope,
safety classification, current test layer (JVM/APK/AVD/device),
PR and main SHA, and one of:

`merged_verified`, `inert_merged`, `plan_only`,
`blocked`, `unsupported_by_platform`.

**Completion for safe roadmap slices** means tested code merged and
post-merge evidence recorded, or an honestly documented plan-only/
platform-unsupported outcome. It **does not** mean the Native MCP is
a full privileged device controller. Final release of actual sensitive
capabilities requires authenticated callers, appropriate Android
permission consent and independently reviewed real-device tests.

## 10. Native N01–N20 capability coverage mapping

This is a **design coverage mapping**, not implementation completion.
The eventual automated state ledger must track capability→Native
provider→permission/API version→test case→branch/PR/merged SHA and
truthful supported/disabled status. An ID being listed below
does **not** imply a working or permitted Android Tool.

| Catalog | Native feature | Work packages / safe disposition |
| --- | --- | --- |
| N01 | Native-local MCP service and health | N0.a, N0.c, N1.c; existing minimal endpoint |
| N02 | Android Build / OS / ABI | N1.a; safe internal snapshot, sensitive access gated |
| N03 | Battery, storage, display, network | N1.b; Android API-permitted reads only |
| N04 | Android permission and capability readiness | N0.d, N1.d; status only, never grant |
| N05 | Filtered PackageManager queries | N2.a, N2.b; API30+ visibility restrictions |
| N06 | Native self diagnostics / service health | N1.c, N5.a, N5.d; app-owned data only |
| N07 | Accessibility node inspection | N3.d, N3.e; explicit service purpose/consent, default-off |
| N08 | UI gestures / key events | N4.a, N4.b, N6.e; plan-only or preverified AVD until approved |
| N09 | User-consented screenshot | N3.a, N3.b; MediaProjection gate |
| N10 | User-consented screen recording | N3.a, N3.c; MediaProjection and FGS lifecycle gate |
| N11 | User-picked SAF file import/export | N4.c, N4.d, N4.e; exact URI grants |
| N12 | Explicit Android app Intent launch | N2.c, N7.c; no arbitrary/background bypass |
| N13 | Optional permitted sensors/location/notifications | N4.f; narrowly scoped, no default monitoring |
| N14 | Native own-app performance / crash telemetry | N5.a, N5.b, N5.c; not global Logcat or profiler |
| N15 | PackageInstaller user-mediated install | N7.a, N7.b; never silent physical-device install |
| N16 | User-visible Native FGS lifecycle | N0.c, N7.d; current opt-in N3, no auto-restart |
| N17 | Authenticated Host/Native pairing | N0.b, N6.a, N6.b; fake/inert until approved live transport |
| N18 | Durable cross-runtime action lease/fencing | N6.c, N6.d, N6.e; never equate process-local port lock |
| N19 | Device Owner / enterprise policy | N8.a; feasibility/unsupported only without provisioning |
| N20 | Root, bootloader and ROM device control | N8.b; unsupported in ordinary APK, Host-supervised plans |

**Public Tool distinction:** at this plan's checked source, Native
still has **one real public status Tool**. The 20 entries above are
catalog families, not a promise to register 20 new Native Tools.
Sensitive functionality stays denied until Android permits it,
the user has genuinely consented and independent security review
has approved any privilege-enabling protocol.
