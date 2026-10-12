# Native MCP implementation plan: Android device-side capabilities

**Plan status:** proposed independent execution backlog,
2026-10-13 (Australia/Sydney). **Workstream owner:** Native MCP
development Chat session, **not Host**. This file is a planning
handoff; it does not modify any Native application or grant Android
permissions. **Shared Git integration target:** `main`
(the user's "master"), at
`7c4ff1e7350b36c89a59b95a9618c471c8906f5b` as its initial
planning baseline. Always resolve fresh `origin/main` at task start.

Read together with [Native current lifecycle](native-foreground-n3.md),
[Native/Host pairing draft](host-native-coordination.md),
the [20 Native capability IDs](android-toolchain-capability-catalog-20261012.md),
the separate [Host implementation plan](host-mcp-implementation-plan-20261013.md)
and the mandatory
[daily merge schedule](host-native-integration-schedule-20261013.md).

## 1. Current Native truth: prototype, not a privileged agent

The Kotlin/Ktor Android Native MCP app currently registers **one**
real Tool, `device_status`, whose v1 result advertises minimal
local status and reports Accessibility observe/act and privileged
capabilities **false**. No real Native screenshot, tap, installed-app
list, general file reader, root, permissions editing or install Tool
has been added.

The N1 foreground Activity and N3 opt-in foreground service
lifecycle are already present in `main`, sharing the local
`127.0.0.1:38765` endpoint with a process-local port-owner
guard. They are **not authenticated remote endpoints**, and process
ownership is **not** Host/Native fencing. The current APK manifest
permission allowlist is Internet, Foreground Service,
Foreground Service specialUse and Post Notifications; adding any
permission needs a reviewed, explicit change and new manifest tests.

The existing framework uses official Kotlin MCP SDK 0.14.0,
Ktor 3.4.3, AGP 9.4.0, Gradle 9.6 and JDK 17.
`scripts/check-native-local-ci.sh` exists to avoid paid GitHub
Actions. MacBook's JDK/SDK is now configured; use the device/emulator
readiness verification commands, not simple presence checks.
Past documentation about earlier N0/N1/N2/N3 implementation is
**historical**; the **NW0–NW8** stages below are NEW future
development waves, not a replay of that work.

## 2. Native scope and hard platform constraints

Cover the catalog's **N01–N20** Native capability families,
with useful overlap against Host when permissions/purpose justify it.

A normal Android application cannot obtain arbitrary ADB shell
authority, unrestricted system Logcat, silent cross-app package
visibility, unattended screen recording or full-device root simply
because it runs an MCP endpoint. Native must use supported Android
SDK APIs and actual, user-granted permissions:

- Status/service controls: public-like metadata only until
  caller authentication and Origin/cross-app access are reviewed.
- App-specific system snapshot / own app telemetry: safe bounded
  information only after threat model and allowed caller path.
- Package enumeration: Android 11+ package visibility restrictions;
  filtered results must be reported as partial, not "all apps".
- MediaProjection: user consent and lifecycle handling, stop on
  consent revocation/screen lock, no covert capture.
- Accessibility: approved user-facing accessibility/test use case,
  user activation, least privilege and external policy review;
  **no generic unattended gesture bot**.
- Files: Storage Access Framework and app sandbox, user-selected
  documents; never a general Android filesystem browser.
- PackageInstaller: Android-mediated user approval; not a silent
  replacement for Host's trusted developer ADB installer.
- Bootloader/root/partition: Native app does not gain these
  powers. Recovery belongs to the supervised Host plan.
- Native localhost is **not** an authenticated Host client. Do not
  expose sensitive Tool outputs until identity/origin/auth checks
  exist, and never publish an unauthenticated public TCP endpoint.

## 3. Execution stages, scoped PRs and immediate merge points

A `NWx.y` row is a short-lived, single-owner Native PR.
`M-NWx.y` means merge it to `main` **at the next active
13:00 or 18:00 Australia/Sydney window once its appropriate tests
pass**. Non-privileged PR branch lifespan is targeted at
1–2 working days. A fully green PR must be merged within **one working
day** when an integrator is available; no requirement forces the merge
of an unsafe, unverified or permission-blocked change. Anything
blocked by Android permissions or security review should be split
into an independently green non-enabling PR and a later explicit
enabling PR, not accumulated on a months-old Native feature branch.

| Stage, priority | Owned PR slice (Native Kotlin/tests only unless separately ACKed) | Native Tool value and capability IDs | Mandatory gate and main merge |
| --- | --- | --- | --- |
| **NW0, P0: secure baseline and service state** | **NW0.a** characterize existing local endpoint, Origin/caller and lifecycle restart/stop limitations without new permissions | Existing `device_status`, app health, `N01,N06,N16` | **M-NW0.a:** Kotlin/JVM protocol + real ephemeral FGS and denial tests; no extra sensitive output |
| NW0 | **NW0.b** proposed local caller-authentication/Origin policy and private pairing identity contract, initially deny sensitive reads by default | Internal caller guard, `native_permission_status` only for non-sensitive readiness (`N04,N17`) | **M-NW0.b-inert:** no exposed sensitive data before approved auth POC + security review |
| **NW1, P0: permitted device snapshots** | **NW1.a** bounded OS/build/ABI/app metadata and permission readiness | `native_system_snapshot`, `native_permission_status` (`N02–N04`) | **M-NW1.a:** permission model, no persistent identifiers/secrets, actual caller gating |
| NW1 | **NW1.b** own-app health, FGS uptime/stop, strict service restart and crash diagnostics | `native_app_health`, `native_service_status` (`N01,N06,N16`) | **M-NW1.b:** process-death, orientation/notification Stop, stale-port owner and live HTTP negative tests |
| **NW2, P1: package/app read-only** | **NW2.a** filtered PackageManager query + explicit app lookup, no blanket visibility | `native_package_query` (`N05`) | **M-NW2.a:** API30/33/34/36 filter tests, privacy scoping; output declares incomplete visibility |
| NW2 | **NW2.b** self app/version/config inspection and safe explicit Intent resolution | `native_app_info`, launch planning (`N05,N12`) | **M-NW2.b:** nonexported app and implicit intent denial; no launch mutation yet |
| **NW3, P2: consented screen observation** | **NW3.a** MediaProjection permissions/consent lifecycle tests and bounded capture artifacts (default disabled) | `native_capture_screen`, optional `native_record_screen` (`N09,N10`) | **M-NW3.a-inert:** consent/UI/stop fixtures; actual sensitive Tool only after approved user consent and caller-auth tests |
| NW3 | **NW3.b** contextual accessibility tree/focus inspection, after service-specific purpose approval | `native_ui_inspect` (`N07`) | **M-NW3.b:** sensitive app/window privacy, lock screen, opt-in and permission-revocation denial |
| **NW4, P2: bounded UI/file interaction** | **NW4.a** UI Automator test harness and accessible node actions with explicit user authorization | `native_ui_action`, `native_app_launch` (`N08,N12`) | **M-NW4.a-plan:** no gesture executor until signed/consented per-action policy accepted |
| NW4 | **NW4.b** SAF user-selected import/export and explicit doc IDs | `native_file_exchange` (`N11`) | **M-NW4.b:** URI grant expiration/revocation, traversal, large payload, retention |
| NW4 | **NW4.c** explicit sensors/network/notification reads within user permission policy | Focused small permission-based Tools (`N13`) | **M-NW4.c:** scoped data retention; no background monitoring by default |
| **NW5, P2: performance and diagnostic events** | **NW5.a** own app crash/ANR/memory, bounded event/artifact capture | `native_app_telemetry` (`N14`) | **M-NW5.a:** offline/process-death, data lifecycle, safe redaction |
| NW5 | **NW5.b** cross-provider read fallback status and reliability test corpus | Provider health/diagnostic Tool, `N06,N14` | **M-NW5.b:** Native unavailable + Host ADB available is observable, not permission escalation |
| **NW6, P3: authenticated Host/Native coordination** | **NW6.a** private installation identity/pairing challenge; **no exposure of signing keys** | `native_pairing_status`, private handshake (`N17`) | **M-NW6.a-inert:** shared protocol C0 must first be merged with Host ACK; replay/identity negative cases |
| NW6 | **NW6.b** durable Native-side fencing high-water mark and lease ownership checks | Internal `native_lease_status` and fencing policy (`N18`) | **M-NW6.b-inert:** survive process death, two Host producers, stale token rejection and audit; still disabled |
| NW6 | **NW6.c** actual scoped mutating endpoint enablement | Narrow signed action executor (`N08,N15,N18`) | **BLOCKED** until independent security + explicit user authorization + hardware gates |
| **NW7, P3: user-approved app lifecycle** | **NW7.a** Android PackageInstaller request and user-visible explicit app launch | `native_install_request` (`N12,N15`) | **M-NW7.a-plan:** app/user consent and signed digest accepted before execution, never silent install |
| NW7 | **NW7.b** robust service reconnect/recovery, explicit user control | `native_service_status`, bounded user-start/stop (`N16`) | **M-NW7.b:** no boot receiver/automatic resurrection, process death and notification Stop tests |
| **NW8, P4: managed enterprise/device profiles** | **NW8.a** Device Owner/managed-device permission feasibility only | `native_managed_device_capabilities` plan (`N19`) | **M-NW8.a-plan:** no policy change without real device provisioning and org/user approval |
| NW8 | **NW8.b** bootloader/root/ROM capability gap handling | Explicit `unsupported`/Host-supervised recovery referral (`N20`) | **M-NW8.b:** no `su`, no unrestricted shell or OEM bypass |

Tool names are candidates subject to focused public Schema and
tools/list selection tests. NW0/NW1 may be implemented in smaller
readiness/checker PRs without exposing a new Tool until the local
caller threat model is accepted.

## 4. First two development weeks: independent Native merge schedule

| Target Sydney date | Native planned PR | Exact acceptance before merge | Integration checkpoint |
| --- | --- | --- | --- |
| Tue **13 Oct** | Accept this plan and Native capability responsibilities | Document/quality checks only; no Android permission changes | **M-PLAN**, same docs PR as Host |
| Wed **14 Oct** | **NW0.a** local state + FGS lifecycle baseline characterization | `check-native-local-ci.sh`, JDK 17 and SDK 36; no physical Android operations | **13:00/18:00 M-NW0.a** when green |
| Thu **15 Oct** | **NW0.b** caller/origin and permissions negative tests, disabled-first | Kotlin tests and multi-process unauthenticated loopback safety cases | **M-NW0.b-inert** green plan/tests only |
| Fri **16 Oct** | **NW1.a** safe system/permission snapshot contract proposal | Native permission matrix and no sensitive output without auth | **M-NW1.a** bounded safe slice or record blocker |
| Mon–Fri **19–23 Oct** | Complete **NW1.a/NW1.b** and prepare **NW2.a** | Emulator API30/33/34/36 as applicable; physical tablet excluded | **Separate 1–2-day PR merges**, never one Native mega-PR |

Native may progress independently of Host HW1/SDK work. Its only
cross-runtime dependency at this stage is accepted, versioned
security/identity/Tool contract terminology; no shared writer.
"Merge window" is a target for an active developer, not an
automated or guaranteed future action.

## 5. Exact ownership, Android permission policy, and test layers

**Native-owned files:** `android/**`, Android Manifest,
Native Gradle configurations, Kotlin protocol/lifecycle/application
modules and tests, `android/tests/**`, Native-specific scripts and
`docs/native-*.md`. The existing Native session owns
`~/Projects/android-mcp-native-setup`; Host must not open that
worktree for edits, reset it or rebase its branch.

**Shared work** requires an independent named integration owner
for `contracts/**`, `docs/security.md`,
`docs/host-native-coordination.md`, central build/CI and root
configuration. On shared pairing/lease changes, first merge shared
v2 contract fixtures with **both** Host and Native ACK, then merge
provider-specific consumers separately. Neither side can assume
the other has already deployed its executable services.

Every Native implementation PR must demonstrate:

1. Exact public Tool input/output schema, denied/partial errors,
   sensitive data policy, user-consent and permission posture.
2. Normal Kotlin/JVM + protocol and Python/Kotlin Streamable HTTP
   smoke via `bash scripts/check-native.sh`.
3. JDK 17 + Android SDK 36 reproducible APK build, Android Lint,
   debug APK signature, manifest permissions, strict locked Gradle
   dependencies via `bash scripts/check-native-apk.sh`.
4. Repository-wide local gate via
   `bash scripts/check-native-local-ci.sh`, never a paid
   GitHub Actions result asserted to be green.
5. If a relevant Android lifecycle/permission feature changes:
   explicit **preverified disposable emulator** API30/33/34/36
   acceptance (`check-native-local-ci.sh --matrix` with exact
   4 serial arguments); fail closed if target is physical or
   identity/Android API mismatches.
6. Hardware-install/Accessibility/MediaProjection/FGS policy tests
   separate and only after appropriate owner authorization, user
   grants and platform review. No physical test is an automatic
   part of baseline CI.
7. Main moves and PR merges require the same no-force,
   exact-head SHA and tested Git tree checks described in the
   [merge schedule](host-native-integration-schedule-20261013.md).

**Unstarted GitHub Actions because of billing are unavailable, not
test failures and not passes.** A high-impact Native feature with
missing emulator or independent security evidence remains blocked,
while unrelated safely implemented lifecycle code may merge.

## 6. Native/Host overlap and rollback

Host's existing independent USB/ADB diagnostics are intentional
resilience for when this Native process is unresponsive. Native
reads can also continue when ADB is unavailable **only** under
actual Android permissions and authenticated caller identity.

- Native dead: Host may read ADB status and approved diagnostics;
  no unannounced downgrade to Host write privileges.
- Host disconnected: Native may report its own health if its local
  service and user-approved channel remain available; it may not
  impersonate Host or assume Host signed grants still apply.
- Both healthy: assign a normal preferred backend by user goal.
  Reads can be independent; writes require signed per-action
  cross-runtime fencing before either side can act.
- Either uncertain: return explicit partial/uncertain result and
  reconcile, not blind repeat of APK install/gesture.
- Rollback: use individual Native PR revert, restore old v1
  `device_status` route, and keep new permission/Tool profiles
  disabled. Do not silently uninstall a physical device APK.

## 7. Native completion ledger and unresolved design decisions

Track `N01–N20 -> Native Tool/API or deliberately unsupported ->
Android API level/permission -> scope -> safety -> NW stage ->
branch/PR -> tests -> main merge SHA -> result`.

**Stage DONE** means each planned `M-NWx.y` has an actual
merged GitHub PR and tested main outcome, or is marked plan-only /
blocked with next authorized gate. An "implemented locally" class
cannot count as merged or device-certified.

**Open decisions before sensitive work:** caller authentication
on loopback, Android Accessibility use case/Play policy,
MediaProjection consent/retention/foreground type requirements,
package visibility declaration, stable Native identity/Host
binding, process durable fencing and device-owner enrollment.
These block affected actions, **not** status/lifecycle safety PRs.

**Immediate next Native PR:** NW0.a baseline/hardening after
current `main` is fetched in Native's own worktree. Host Stream
remains free to start HW0.a in parallel and must not touch Native
files to "help" without a contract/ownership handoff.
