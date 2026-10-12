# Android Host MCP implementation plan — reviewed serial execution v2

**Updated:** 2026-10-13 (Australia/Sydney).
**Review outcome:** reworked from the 2026-10-13 v1 plan into smaller,
dependency-ordered, test-defined and independently mergeable work packages.
**Owner:** one ChatGPT development conversation, one active Host work package
at a time; do not delegate implementation to a second AI worker/agent.
**Repository:** grammy-jiang/android-mcp; **only permanent integration branch:
`main`** (not a separate `master`/Host branch).
**Reviewed base:** `ac5e62f929b00cd53fd40403c450bf2ff327f7e2`, refresh from
`origin/main` before each implementation slice.
**Status:** ready to start *safe Stage H0 work*, **not** an approval to enable
physical writes, unauthenticated remote transport, root, flashing or releases.

**Required reading and companion specifications:**
[95-family Host inventory](android-toolchain-capability-catalog-20261012.md),
[step-specific executable test cases](host-mcp-serial-test-cases-20261013.md),
[one-chat startup/handoff](host-mcp-serial-session-handoff-20261013.md),
[zero-paid merge gates](host-merge-gates.md),
[Host/Native file ownership](parallel-workstreams.md) and
[the common integration calendar](host-native-integration-schedule-20261013.md).
The earlier [full-lifecycle overview](android-host-native-full-lifecycle-design-20261012.md)
is a shared **reference**, not a second executable plan. Native owns its
[separate workstream](native-mcp-implementation-plan-20261013.md).

## 1. Review: what was wrong with v1 and how this fixes it

| v1 risk | v2 correction | Required evidence |
| --- | --- | --- |
| HW1.b combined unrelated system probes, package inspection, network state and Logcat | Split H1.c, H1.d, H1.e | One focused Tool/adapter contract per PR, separate targeted negative tests |
| HW2 build jobs arrived before an explicit artifact/job state model | H2.c artifact store and H2.d durable job store precede H2.f Gradle builds, H3 emulator jobs, H4 media and H5 profiling | Restart/replay/cancel/retention tests first |
| HW3.a combined AVD inventory, create/start/stop and snapshot changes | H3.a/b/c/d separate read, provision, lifecycle and snapshot slices | Real disposable-emulator isolation tests only after synthetic test gates |
| HW4 and HW5 mixed sensitive reads with write-capable operations | Separate screenshot, UI tree, recording, pull, push and emulator input; profiling in discrete slices | Permission/path/secure-display/size/cancel denials |
| HW6/HW7/HW9 depended on Native sign-off, real hardware, human response or external accounts | Deliver local fake/plan-only/inert code, default-denied routes and traceable deferred state; proceed to next independent slice | No privileged behavior enabled by a self-review or absent approval |
| Fixed 13:00/18:00 merge windows could idle a single session | **Merge immediately after exact-SHA gates**, do not wait for a clock; time windows are for cross-session synchronization if active | GitHub merged PR and verified `main` tree before the next slice |
| “Tests” were topics rather than concrete cases | Companion spec lists positive, denied, malformed, timeout, privacy, replay/cleanup tests **for every Hx.y slice** | Named pytest files/test IDs and actual red→green proof |
| 95 catalog families risk being mistaken for 95 public Tools | Full coverage ledger, focused Tool registry and explicit plan-only/excluded states | Catalog audit catches missing/unsupported capabilities |

**Important distinction:** v1's HW0–HW9 labels were only proposed work.
This document is the controlling v2 plan. None of the work packages below
has been implemented merely because historical FastMCP Wave 0–3 passed.

## 2. Operating mode for an eight-hour absent owner

The owner has requested **no interactive human checkpoints during routine
Host development**. The single ChatGPT session shall:

1. Resolve normal engineering alternatives itself using existing contracts,
   official CLI help, conservative backward compatibility, synthetic evidence
   and this plan; record a short decision rationale in each PR. No repeated
   questions for facts already recorded.
2. Develop **serially**: at most one package in implementation/test/merge
   at a time. Do not schedule Codex/Claude/secondary workers or create
   competing branches for parallel features. Read-only repository inspection
   and a test subprocess inside the current package are not parallel work.
3. Start from current `origin/main`, create **one new exclusive Host
   worktree/branch**, write a failing test, implement, test all gates,
   self-review honestly, open a scoped PR, **merge to main immediately** when
   non-privileged admission checks pass, verify the merged Git tree, and
   only then start the next package from the new main.
4. If normal design is underspecified, choose the safer nonbreaking
   interpretation, add tests, document it and continue. If a required
   external machine/package/account is absent, implement **adapter/fixture
   and truthful `unavailable` handling** without manufacturing evidence.
   Continue to the next independent work package; do not wait for a reply.
5. **Never treat lack of human presence as consent** for Google license
   acceptance, account connection, actual physical APK install,
   Android settings changes, root, recovery/flash/unlock, production
   signing/release, sensitive-data capture or insecure listener startup.
   Implement *disabled* or *plan-only* contracts with denial tests, record
   `EXECUTION_DEFERRED` and keep advancing safely.
6. ChatGPT can perform its own code review and run all automated checks;
   label the result **self-reviewed**, never fabricate independent review.
   A privileged enabling change remains disabled and outside automatic
   merge until authentic required authorization/independent review exists.
   The inert tests/contract may merge on their own merits.
7. If tests fail, fix and rerun without asking; if an essential gate remains
   unavailable, push/checkpoint the exclusive branch as **blocked**
   (not green), record exact SHA/logs, and select a new independent
   non-overlapping slice from latest main. Never merge failed code.
8. Keep working while the ChatGPT execution session and tools are actually
   active; **there is no guaranteed background execution for eight hours**
   after a chat turn ends or tools disconnect. Always leave a durable
   GitHub commit/PR and resume marker so a later session can continue.
   A schedule in Markdown is not an automation.

### Status vocabulary (never conflate)

`not_started`, `in_progress`, `test_failed`,
`blocked_dependency`, `ready_to_merge`, `merged_verified`,
`implemented_disabled`, `plan_only` and
`excluded_by_security`. Only `merged_verified` means executable
scope is complete; disabled/plan-only work is honestly distinct.

## 3. Existing stable baseline and requirements

- Host Python/FastMCP 4.1.0 has exactly three currently public Tools:
  `device_status`, `adb_observe`, `adb_develop`; their v1
  wire schemas/typed domain errors remain backward compatible.
  Existing default mutating actions remain DENIED.
- At the reviewed baseline, 366 Host tests passed with all gates on
  macOS ARM64 and sextant Linux ARM64 for Python 3.11–3.14.
- MacBook has JDK 17, SDK Build Tools 36 and ADB/Fastboot 37.0.1;
  both Pi nodes have ADB/Fastboot 34.0.5. macOS GUI launchd does
  **not** automatically inherit the terminal `JAVA_HOME`.
- Host code changes belong to `host/**` plus Host-only docs/scripts.
  **DO NOT MODIFY** Native's `android/**` or its exclusive worktree
  `~/Projects/android-mcp-native-setup`. Shared `contracts/**`
  must remain versioned/additive; propose an optional contract and
  keep Host execution independent when the Native owner is unavailable.
- Do not introduce generic public `run_shell`, `adb_exec`,
  `fastboot_oem`, free-form Gradle task execution, or direct
  unconstrained absolute host paths. Tool visibility must reflect
  installed/runnable **and** authorized state, not merely executable
  presence.
- The repository is on a zero-paid-Runner policy. Do **not** purchase
  GitHub Actions minutes or count billing-blocked workflows as passed.

## 4. Strict serial dependency graph

```text
H0: baseline/CLI truth → profiles → target identity
  ↓
H1: ADB discovery → transport → bounded diagnosis → package → logcat
  → Fastboot discovery (read-only only)
  ↓
H2: SDK/project introspection → artifact store → durable job store
  → offline APK analysis → bounded build/signing verification
  ↓
H3: AVD inventory → AVD creation → emulator lifecycle → snapshots
  → instrumentation → emulator-only deployment
  ↓
H4: screenshots → UI hierarchy → screen recording → file pull
  → safe file push (emulator/plan-only) → UI actions (emulator/plan-only)
  ↓
H5: bugreports → bounded stream → Perfetto → Simpleperf → symbolization
  ↓
H6: pairing mock/inert → durable fencing fake → denied mutation plans
  → transport/pairing plans (no real privileges)
  ↓
H7: Fastboot safe inspection → image preflight → recovery plan-only
  ↓
H8: eligible AOSP worker inventory → Repo/build preflight
  → simulated bounded source/image/test job
  ↓
H9: local release readiness → optional provider read-only capability
  → signed release-plan/dry-run (no live release change)
```

This is **one active work package at a time**. If a package is
technically blocked (unavailable SDK/worker or required security
authorization), complete its deterministic disabled/unavailable cases
and move on; do not open a second concurrent implementation task.
Each stage is composed of short-lived PRs, NOT a permanent stage branch.
Read-only Fastboot discovery is in H1 even though physical recovery
design lives in H7. Full AOSP and release publishing remain
capability-covered even when unavailable on the present machines.

## 5. Atomic Host work package / PR sequence

One row = one test-first PR, using the exact test IDs in the
[companion test specification](host-mcp-serial-test-cases-20261013.md).
Each row lists the **minimum source contract**, not a promise that the
suggested public Tool name is frozen before actual FastMCP tools/list
compatibility tests. One working use case, one safety class and an
explicit merge receipt per row.

| Order | Package (priority) | Input → output / planned Tool or application service | Dependency / safe implementation scope | Required tests | Merge receipt |
| --- | --- | --- | --- | --- | --- |
| 01 | **H0.a** (P0) baseline/golden contract | Existing tools/list + v1 examples → frozen snapshot/denials | Use current baseline; no new device Tool | T-H0A | M-H0.a |
| 02 | **H0.b** (P0) CLI/toolchain availability | Fixed executable IDs → version/runnable/unsupported, separate JDK/SDK/ADB/Fastboot | No install, help/version only; Pi/Mac differences | T-H0B | M-H0.b |
| 03 | **H0.c** (P0) capability and target model | Safe profile + discovered refs → typed capability state/target lease hint | No guessed ID, no Native auth claims | T-H0C | M-H0.c |
| 04 | **H1.a** (P0) ADB discovery | No target → bounded named devices, state, transport IDs | Reuse AdbClient; exactly one list Tool if useful | T-H1A | M-H1.a |
| 05 | **H1.b** (P0) transport and wait | Exact target/state → bounded wait, mDNS/forwarding **inspection** | Never auto-pair, reconnect or open a port | T-H1B | M-H1.b |
| 06 | **H1.c** (P0) system probes | Device + selected group → typed fixed `dumpsys`/build/battery/network fields | Extend ProbeService, no raw service names | T-H1C | M-H1.c |
| 07 | **H1.d** (P0) app package reads | Device + package/filter → visible package/details/permissions | Bounded allowlisted package manager calls | T-H1D | M-H1.d |
| 08 | **H1.e** (P0) Logcat read | Device + exact filters/time/lines → bounded redacted snapshot | Preserve current logcat behavior and limits | T-H1E | M-H1.e |
| 09 | **H1.f** (P0) Fastboot discovery | No target or exact bootloader target → devices and mode **read-only** | Fake CLI tests; do not reboot a physical device | T-H1F | M-H1.f |
| 10 | **H2.a** (P1) SDK/NDK inventory | Host directories → valid JDK/SDK/AVD/build-tools/NDK state | No package installation or license acceptance | T-H2A | M-H2.a |
| 11 | **H2.b** (P1) project/build preflight | Trusted project handle → safe Gradle wrapper/variants/tasks plan | No free-form Gradle task string or external checkout | T-H2B | M-H2.b |
| 12 | **H2.c** (P1) artifact records | Artifact bytes → opaque handle/hash/MIME/size/retention | Private storage, no sensitive binary Tool output | T-H2C | M-H2.c |
| 13 | **H2.d** (P1) durable job state | Prepared action → stable job ID, transitions/recovery/cancel | Before any slow Gradle/emulator/trace command | T-H2D | M-H2.d |
| 14 | **H2.e** (P1) APK/AAB inspectors | Trusted artifact handle → metadata, signature/ABI/resource verification | Local-only readers, no signing or install | T-H2E | M-H2.e |
| 15 | **H2.f** (P1) controlled build/lint | Trusted project + allowlisted build variant → job/report/artifacts | Gradle wrapper, strict resource budget, no physical device | T-H2F | M-H2.f |
| 16 | **H3.a** (P1) AVD inventory | SDK + AVD name → API/ABI/running/snapshot status | Read-only; AVD is not physical device | T-H3A | M-H3.a |
| 17 | **H3.b** (P1) disposable AVD management | User-scoped test AVD plan → create/delete only MCP-owned AVD | Never delete pre-existing/user-owned AVD | T-H3B | M-H3.b |
| 18 | **H3.c** (P1) emulator lifecycle | MCP-owned AVD handle → start/wait/stop/reconcile | Bound QEMU process; exact serial + no USB fallback | T-H3C | M-H3.c |
| 19 | **H3.d** (P1) emulator snapshots/fault simulation | Disposable AVD + snapshot/test condition → state/result | Emulator-only; no other AVD rollback | T-H3D | M-H3.d |
| 20 | **H3.e** (P1) instrumentation/test jobs | Test artifact + verified emulator handle → run/result report | Reuse H2.d, allowlisted Gradle/instrument commands | T-H3E | M-H3.e |
| 21 | **H3.f** (P1) debug APK deployment | Local debug APK + verified disposable AVD → install/start/uninstall | Never default to connected physical tablet | T-H3F | M-H3.f |
| 22 | **H4.a** (P2) screenshot | Explicit selected emulator/device + policy → sensitive artifact handle | Fixed screenshot backend; no raw base64/logging | T-H4A | M-H4.a |
| 23 | **H4.b** (P2) UI tree | Exact target → bounded hierarchy with redaction | Scoped read; no Accessibility permission bypass | T-H4B | M-H4.b |
| 24 | **H4.c** (P2) bounded screenrecord | Approved target + cap/duration → job/artifact + stop | Sensitive read; plan-only until consent policy met | T-H4C | M-H4.c |
| 25 | **H4.d** (P2) file export/pull | Explicit allowlisted remote source → private Host artifact | Never unscoped `/data` or arbitrary host output | T-H4D | M-H4.d |
| 26 | **H4.e** (P2) file push/import | Host artifact + safe remote destination → dry-run or emulator write | Physical device write remains default-denied | T-H4E | M-H4.e |
| 27 | **H4.f** (P2) UI input | Fixed tap/swipe/key intent → simulator/AVD-only execution or plan | Physical UI changes stay disabled without grants | T-H4F | M-H4.f |
| 28 | **H5.a** (P2) bugreport | Exact target + redaction → bounded private report artifact | May contain secrets, TTL/delete mandatory | T-H5A | M-H5.a |
| 29 | **H5.b** (P2) Logcat stream/process | Target + bounded stream lease → cursor, poll, stop | Finite file/bytes, no session-owned orphan | T-H5B | M-H5.b |
| 30 | **H5.c** (P2) Perfetto | Debuggable test target + fixed profile → trace job | Fake/AVD, explicit size/time caps and cleanup | T-H5C | M-H5.c |
| 31 | **H5.d** (P2) Simpleperf/profiling | Debuggable app + supported ABI → bounded profile job | Capability probe and safe unsupported results | T-H5D | M-H5.d |
| 32 | **H5.e** (P2) symbolization/analysis | Trace/log/symbol handles → bounded report with provenance | Never log symbols/credentials; local artifacts only | T-H5E | M-H5.e |
| 33 | **H6.a** (P3) Host/Native pairing contract | Fake Native identity + signed challenge → deny-by-default interface | No new Native endpoint or live pairing | T-H6A | M-H6.a (inert) |
| 34 | **H6.b** (P3) fencing/lease simulator | Exact target+plan digest+fence → durable state machine | Fake Native only, fail closed on stale/missing ACK | T-H6B | M-H6.b (inert) |
| 35 | **H6.c** (P3) physical deploy plan | APK/artifact/target → signed plan, denial by default | *No live physical install/uninstall/grant/force-stop* | T-H6C | M-H6.c (disabled) |
| 36 | **H6.d** (P3) wireless/forward plan | Target + endpoint → safe route/pairing plan + policy denial | No auto adb tcpip/forward, remote exposure or credential write | T-H6D | M-H6.d (plan-only) |
| 37 | **H7.a** (P4) bootloader variables | Exact Fastboot target → narrow getvar/version/slot snapshots | Prefer fake CLI; physical observations opt-in only | T-H7A | M-H7.a |
| 38 | **H7.b** (P4) image preflight | File hash + device profile → match/mismatch, partition/slot plan | Never open broad arbitrary paths or write flash | T-H7B | M-H7.b |
| 39 | **H7.c** (P4) recovery plan | Target/image/read-only facts → printable manual runbook | No flash/unlock/erase/reboot Tool enabled | T-H7C | M-H7.c (plan-only) |
| 40 | **H8.a** (P4) AOSP worker availability | Host ABI/OS/RAM/disk/toolchain → eligible/unavailable | x86-64 Linux build eligibility, not Pi/macOS assumption | T-H8A | M-H8.a |
| 41 | **H8.b** (P4) Repo/Soong preflight | Approved source checkout+target → safe manifest/build plan | No bulk `repo sync` without approved workspace | T-H8B | M-H8.b |
| 42 | **H8.c** (P4) AOSP job/report adapter | Eligible worker/fake job → durable build/test result/provenance | No physical flash; unavailable if worker absent | T-H8C | M-H8.c (adapter) |
| 43 | **H9.a** (P3) release readiness | Versioned APK/AAB/artifact → offline track-readiness checklist | Local manifest/signature only | T-H9A | M-H9.a |
| 44 | **H9.b** (P3) provider capability/read | Account connector/status → scoped Play/Firebase read or unavailable | If no connected account, do not invent one | T-H9B | M-H9.b (read/disabled) |
| 45 | **H9.c** (P3) rollout/release plan | Signed artifact + release policy → draft/rollback/stop plan | Live upload/commit/halt **disabled** without scoped grant | T-H9C | M-H9.c (plan-only) |

**45 serial PR slices across 10 stages.** A developer may subdivide a
slice *further* when it crosses safety or file-ownership boundaries; do
not combine adjacent slices into a multi-stage PR for speed. Contracts
for H6–H9 should use fakes, fixtures and truthful disabled paths when
the required privileged backend is absent.

## 6. Mandatory test-first acceptance for **every** Hx.y

Every package has a dedicated test file (or additions to a named existing
contract module) and **at least five specific new/updated cases** in
[the test matrix](host-mcp-serial-test-cases-20261013.md). For each package:

1. **Red evidence:** run a focused pytest selection, show a meaningful
   assertion fails before implementation (or a new safety regression fails),
   and retain the test identifier. Tests that merely fail on import/syntax
   errors are not a meaningful red phase.
2. **Pure unit cases:** success on trusted synthetic input, absent/degraded
   dependency, malformed/untrusted input, limits/boundaries and denied
   operation. Use `tmp_path`, fixed fake ADB/Fastboot/Gradle/SDK binaries,
   deterministic clocks and fake subprocesses. Never rely on actual
   Android device access for CI correctness.
3. **Security/negative cases:** test all external paths/arguments for
   traversal, symlink, arbitrary shell injection, invalid device ID,
   privacy/logging, unexpected privilege and wrong-device selection where
   applicable. Do not interpret a long response or hidden exception
   as a valid denial without checking its typed error.
4. **Lifecycle cases:** when stateful, enforce timeout, cancellation,
   bounded memory/disk, repeated request, crash/restart, partial/unknown
   result, device disconnect and accurate audit ordering. Tests must
   prove no orphan subprocess and no unsafe automatic retry.
5. **Real FastMCP contracts:** run `Client(create_server())` and at least
   one isolated localhost Streamable HTTP fake-ADB/fake CLI test for each
   newly published public Tool family. Assert catalog name, description,
   input/output JSON Schema, annotations, `structured_content`,
   typed domain denials and unchanged legacy Tool results.
6. **Coverage and hygiene:** `scripts/check-host.sh` enforces true
   *per-module statement and branch* thresholds: critical modules >=95%,
   all others >=90%, with <=500 physical lines per module, Ruff,
   strict mypy and Bandit. Avoid weakening checker thresholds or tests
   to meet a merge window. `host/.coverage.json` alone is not proof.
7. **Two-host exact-commit matrix:** macOS ARM64 **and** sextant Linux ARM64,
   Python **3.11 / 3.12 / 3.13 / 3.14** each run the full locked Host
   gate against the **same SHA**, plus `scripts/check-host-package.sh`
   (clean wheel/sdist + CLI Doctor). Run pre-commit and pre-push checks,
   dependency audit as appropriate and `git diff --check`. Never
   count unstarted GitHub Actions billing-blocked jobs as green.
8. **Conformance/product truth:** run real in-process FastMCP and local
   HTTP tests; these are **not** equivalent to an ordinary Chat/Work
   tool-selection test, certified MCP conformance suite or real tablet
   acceptance. Label every unrun category accurately.
9. **Review before merge:** a genuine self-review covers changed paths,
   data flow, side effects, denied cases, compatibility and cleanup.
   External independent review is **not fabricated**. Non-enabling
   bounded code may merge after configured deterministic gates pass;
   high-privilege enabling code may **not**.
10. **Merge and repeat:** create exact-head PR, recheck real
    `refs/heads/main`, compare file scope, merge safely, fetch
    `origin/main`, compare integrated tree and rerun relevant smoke.
    Document `merge_sha` and result in the PR. On main movement,
    safely reconstruct the owned Host-only changes and rerun tests.
    **Immediately start the next safe package**, no artificial
    13:00/18:00 wait.

### Work-package trace record (must survive context loss)

For each Hx.y store: `package_id`, catalog IDs, base SHA,
exclusive worktree path, branch/head SHA, intended Tool/adapter,
created tests + red evidence, constraints, test command matrix with
exit codes/versions, changed files and diff, review findings,
risk class, external/user grants **not used**, PR number,
merged main SHA/tree, rollback target and next package status.
Record once per PR or in owned `docs/handoffs/host-*.md`, not
by modifying Native's shared STATUS file.

Do not silently mark `implemented_disabled` as a live feature.
Stage finish is the union of the actual merged PRs, safe plan-only
deliverables and explicit deferred/excluded ledger entries.

## 7. Serial branch/merge protocol for the new chat

```text
READ latest main / existing PRs / file ownership / current worktree
  |
SELECT first Hx.y without verified merged_sha
  |
NEW isolated Host worktree from latest origin/main (not Native's worktree)
  |
ADD targeted failing tests → implement smallest safe slice → run focused tests
  |
RUN Mac exact-head 3.11-3.14 + Linux exact-head 3.11-3.14 gates
  |                      |
  | failure              +---> fix/rerun; if truly unavailable, checkpoint BLOCKED
  |                                             and move to another independent slice
  +---> no merge of failed code
  |
SELF-REVIEW, determine safe enabled vs implemented_disabled/plan_only
  |
OPEN PR → recheck live main SHA/head/scope → squash merge exact head
  |
VERIFY merged main Git tree and post-merge smoke, record receipt
  |
RE-FETCH main and proceed to NEXT serial package
```

There is **one current implementation slice**. A paused, blocked PR
may exist as durable evidence; never work on two slices concurrently,
and do not accumulate a chain of stacked feature branches. If more
than two blocked PRs would remain outstanding, prioritize resolving
their tooling/test blockers or finish independent documentation/tests;
do not silently proceed to a large unmergeable backlog.

The shared [integration schedule](host-native-integration-schedule-20261013.md)
defines communication/merge windows for **two active streams**.
For the single-Chat Host execution requested here, **successful
exact-head gates are the actual immediate-merge trigger**.
Clocks are review reminders, **never hard waits**. No unattended
clock-based automation is promised.

Do not rebase/delete Native's current worktree, overwrite shared
`contracts/**`, restart another session's processes, or run
physical Android/bootloader operations as part of this workflow.

## 8. Explicit no-human-decision policy and boundaries

| Situation | ChatGPT serial choice (without asking an absent owner) | What cannot be claimed |
| --- | --- | --- |
| Multiple safe framework designs | Choose minimal compatible FastMCP adapter and document trade-off/tests | No claim of outside approval |
| A new read-only Tool and tests are green | Merge exact-head PR to main immediately and move on | No requirement to wait until 13:00/18:00 |
| Local Java/SDK version mismatch | Use existing installed toolchain, safe absolute paths or `unavailable`; test fallback | No blind SDK license acceptance or auto system upgrade |
| Pi unavailable or CI blocked | Checkpoint failing/blocked PR with exact log/SHA, continue independent fake/unit work serially | Do not report Mac-only validation as a passed Linux gate |
| Native contract unavailable | Implement fake adapter and **inert** handshake/lease semantics; keep callable mutation disabled | Do not claim authenticated Native integration is verified |
| Physical device install, reboot, root, Fastboot flash/unlock/erase | Implement plan-only verifier and fail-closed denial; record enabling as deferred | No device action, owner approval or independent review inferred |
| Firebase/Google Play account not connected | Implement offline artifact/track readiness and a mock provider returning `unavailable` | No publishing, uploading or token discovery |
| AOSP x86_64 Linux builder absent | Inventory requirements, expose unavailable, test simulated worker | No claim that Pi or Mac builds full AOSP ROM |
| Ordinary Chat/Work model selection inaccessible | Write evaluation corpus and expose transparent `not_run`; use in-process/client tests meanwhile | No product-surface results invented |
| Context/tools/session terminate | Commit a resumable checkpoint and state the next precise action | No background work guarantee |

The absence of required authorization should **block only the
privileged enabling substep**, never stop independent safe Host
development. Authorized local macOS build/test, fake-CLI subprocess
and explicitly preverified disposable test emulators are permitted
under bounded test rules. Never choose the first physical device.

## 9. 95-family coverage and completion criteria

Audit all catalogue Host IDs exactly once: `A01–A38` (38),
`H01–H24` (24), `P01–P06` (6), `F01–F12` (12),
`R01–R07` (7) and `E01–E08` (8): **95 families**.
The catalog's separate `N01–N20` (20) are Native-owned.
Stage tests/contract PRs may cover multiple IDs but a numeric
catalogue count is **not** a count of completed public Tools.

For each ID maintain a case in the capability ledger:
`catalog_id`, chosen Tool/provider or excluded policy,
SDK/CLI source/version, platform, risk class, phase/PR,
unit/HTTP/packaging test IDs and results, owner, exact merged SHA,
`runnable/denied/unavailable/plan_only` disposition.
Add a simple test that rejects missing or duplicate IDs and
unapproved upgrade from plan-only to runnable. This ledger may be
added in H0.c after the common safe data model is in place; do
not change the original Google/AOSP catalog merely to update
implementation status.

**Completion definition per slice:** tests implemented and passed,
verified PR merged to `main` at exact source tree,
compatibility/negative cases retained, and output/authorization
state accurately documented. The safe implementation roadmap
can finish while some execution families remain deliberately
disabled/unavailable. That **does not** certify operational full
privilege or release capability.

**Immediate next step for the new serial Host chat: H0.a** on
the newest `main`, writing baseline Tool/Schema/HTTP regression
tests without introducing a device-changing command.
