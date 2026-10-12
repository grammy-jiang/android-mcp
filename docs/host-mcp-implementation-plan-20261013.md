# Host MCP implementation plan: full Android development lifecycle

**Plan status:** proposed execution backlog and integration policy,
2026-10-13, Australia/Sydney. **Workstream:** Host MCP only.
**Repository target:** grammy-jiang/android-mcp, integration branch
`main` (the user's "master"). **Plan base:** main
`7c4ff1e7350b36c89a59b95a9618c471c8906f5b`; refresh it before work.
**Implementation owner:** Host Chat/development session.
**Native owner:** separate Native Chat session; this plan never authorizes
Host to edit that owner's Android app worktree.

Read together with:
[full toolchain catalog](android-toolchain-capability-catalog-20261012.md),
[Host+Native umbrella design](android-host-native-full-lifecycle-design-20261012.md),
[Native-only implementation plan](native-mcp-implementation-plan-20261013.md)
and the **binding [daily/weekly merge schedule](host-native-integration-schedule-20261013.md)**.

## 1. Precisely bounded starting point

**Already merged and tested:** FastMCP 4.1.0 Host baseline
`device_status`, `adb_observe`, `adb_develop`, with versioned
output Schemas and conservative metadata; 366 Host tests passed on
macOS and Linux ARM64, Python 3.11–3.14, at final F0 acceptance.
Existing default Host supports bounded ADB package and Logcat reads,
selected probe groups and *plans* for install/instrumentation.
**No normal default Host execution of APK installation, device reboot,
root, arbitrary shell, Fastboot write or remote unauthenticated API.**

**Scope of this plan:** **95 Host-relevant capability families**,
as inventoried in the catalog: A01–A38 (38), H01–H24 (24),
P01–P06 (6), F01–F12 (12), R01–R07 (7) and E01–E08 (8).
This is a coverage map, **not 95 externally registered Tools**.
Each family must eventually resolve to a named, versioned
allowlisted Tool, an application-internal service, plan-only/manual
runbook, or a reasoned exclusion; none may disappear unnoticed.

**Runtime evidence:** MacBook (Apple Silicon) now has Java 17,
Android SDK, Gradle, ADB/Fastboot 37.0.1 and Emulator; both Pi 5
machines have ADB/Fastboot 34.0.5. SDK/Emulator are *not* verified
on the Pi. GUI launchd Java/SDK inheritance is not guaranteed by
the terminal profile. Read the
[toolchain setup evidence](android-development-toolchain-setup-20261012.md).

## 2. Capability architecture and contract constraints

- Preserve existing Tool names and v1 output contract during additions;
  never change `adb_develop` denial semantics as a side effect of
  adding a stricter Schema. Build focused read / plan / write Tools.
- FastMCP only handles MCP registration/serialization/metadata;
  device validation, authorization, subprocess planning, audit, jobs and
  artifact retention remain application/service responsibilities.
- **Every physical device requires an exact verified ID and mode**.
  Bootloader serial and booted ADB ID cannot be silently treated as the
  same live instance. Never auto-select the first online device.
- No arbitrary model-controlled shell or command flags. Typed argv
  allowlists, fixed executable discovery, bounded bytes/time,
  safe file roots, sanitized diagnostic output and typed errors.
- Emulator mutation must identify an explicitly verified disposable
  AVD; it cannot silently fall back to a USB tablet.
- Persist long-running job ID, status, timestamp, output digest,
  owner, cancel and retry/unknown state. Loss of MCP session does not
  prove a child process or device operation stopped.
- No signing keys, ADB credentials or Play credentials in Tool input,
  stdout, normal logs or output artifacts.
- **Capability profiles:** base-status, read-diagnostics,
  host-build, emulator-test, media, profiling, deployment,
  fastboot-inspect, recovery-plan, AOSP-build-worker,
  distribution. Implement/POC FastMCP tool visibility for configured
  profiles before assuming a client honors it.
- Tool metadata matches real effects. Read operations that may start
  host ADB daemon cannot claim a perfectly side-effect-free host.
- Cross-runtime UI/app writes require authenticated pairing and
  Native lease/fencing; no "Native is down, so Host may write" shortcut.

## 3. Stage work packages and explicit main merge checkpoints

Each `HWx.y` row is **one bounded PR/merge slice**, not merely a
subtask hidden on a multi-week branch. `M-HWx.y` means merge that
slice to `main` at the **next 13:00 or 18:00 Australia/Sydney
integration window** once all gates pass. Maximum normal age:
one working day after green, or two working days from branch creation.
If blocked, split safe code/tests or record the blocker; never
merge failed/unsafe code to meet the clock.

Stage labels HW0–HW9 refer to this new implementation plan, **not**
the completed historical Host FastMCP Wave 0–3 refactor.

| Stage, order and proposed effort | ID / dedicated PR scope, owner Host | MCP outcome and catalog IDs | Merge checkpoint and proof |
| --- | --- | --- | --- |
| **HW0, P0, 2–4 active days**: prerequisite visibility | **HW0.a** deterministic local toolchain locator/CLI version/failure registry; no device access | `host_toolchain_inventory` (H01, A02, F01); distinguish installed, runnable, authorized and unavailable | **M-HW0.a**. Mac missing-Java and Pi no-SDK fixtures; no tool installation from model input |
| HW0 | **HW0.b** capability profile and target-reference read model, allowlisted use cases and Tool selection golden prompts | Profile list/availability and baseline 3 Tool compatibility (A01,A09) | **M-HW0.b**. No legacy Tool changes; real tools/list and fallback-model selection characterization |
| **HW1, P0, 4–8 days**: safe ADB/Fastboot observations | **HW1.a** read-only device/transport state, bounded wait and connection error handling | `adb_devices_list`, `adb_transport_inspect` (A01–A05,A07 diagnostics only) | **M-HW1.a**. Offline/unauthorized/multiple targets + timeout matrix |
| HW1 | **HW1.b** typed probe expansion, package/system/network snapshots, bounded Logcat and privacy | `adb_device_diagnostics`, `adb_package_info`, `adb_logcat_read` (A10–A21); reuse existing ProbeService | **M-HW1.b**. No user-defined shell; typed limits and redaction fixtures |
| HW1 | **HW1.c** fastboot CLI discovery, read-only fastboot target/mode hints (no bootloader operations) | `fastboot_devices_list`, `fastboot_inspect` (F01–F04 only, where safe) | **M-HW1.c**. Zero devices, conflicting modes, missing tool; no flash/getvar physical test unless separately approved |
| **HW2, P1, 6–12 days**: SDK/build/package | **HW2.a** Java/SDK/NDK/Gradle plan and secure project/root detection | `sdk_packages_list`, `android_build_plan`, `ndk_toolchain_inventory` (H01–H03,H07,H19–H20) | **M-HW2.a**. Correct tool version and missing Java; workspace path allowlist |
| HW2 | **HW2.b** APK/AAB/DEX resource inspection and certificate verification | `apk_inspect`, `apk_verify`, `app_bundle_inspect` (H11–H16) | **M-HW2.b**. No signing secrets or writing; malicious/large APK inputs bounded |
| HW2 | **HW2.c** bounded local Gradle build/lint jobs and artifact records | `android_build_run`, `android_build_result` (H07–H10,H17–H18) | **M-HW2.c**. Durable job ID, cancel, restart, deterministic project/target and toolchain |
| **HW3, P1, 5–10 days**: emulator and tests | **HW3.a** AVD list, create/start/stop/snapshot with exact disposable identity | `avd_list`, `emulator_start`, `emulator_stop` (H03–H06,A38) | **M-HW3.a**. Verified QEMU serial, no physical device fallback, cleanup on failure |
| HW3 | **HW3.b** instrumentation/test plans, scoped runner, result artifacts | `android_test_plan`, `android_test_run`, `android_test_result` (A25,H09–H10) | **M-HW3.b**. Tests on explicitly chosen disposable emulator; no unchecked real tablet install |
| **HW4, P2, 6–12 days**: backup UI/files | **HW4.a** bounded screenshot/screenrecord and UI hierarchy diagnostics | `adb_capture_screen`, `adb_ui_inspect`, `adb_record_screen` (A30–A32) | **M-HW4.a**. Sensitive artifact handles, secure-window rules, size/retention policy |
| HW4 | **HW4.b** bounded pull/export with SHA-256, allowed roots; separate approved push | `adb_pull_file`, `adb_push_file` (A18,A27–A29 only safe subset) | **M-HW4.b**. Path traversal/symlink/large output denial; writes remain opt-in |
| HW4 | **HW4.c** UI action plan/replay, only after permission and device lease decision | `adb_ui_action` (A24,A33–A34) | **M-HW4.c-plan** neutral plan/tests may merge; executable gestures **BLOCKED** until HW6 approved |
| **HW5, P2, 5–10 days**: profiling/debug | **HW5.a** bugreport/logcat stream, process/Crash/ANR storage | `adb_bugreport_collect`, diagnostic artifacts (A14–A17,A19–A20,P06) | **M-HW5.a**. Truncation, redaction, delete, cancel and retention |
| HW5 | **HW5.b** Perfetto/Simpleperf/cpu-mem-trace and symbolization | `perfetto_capture`, `simpleperf_capture`, `native_crash_symbolize` (P01–P05,H21–H23) | **M-HW5.b**. Bounded trace size/time, capability/API checks, verified artifact provenance |
| **HW6, P3, gated; no fixed completion date** | **HW6.a** authenticated pairing/Host identity with Native contract agreed first | Private identity handshake and `host_pairing_status` (A04–A08) | **M-HW6.a-inert** merge non-enabling fixtures/transport tests first; Native ACK and independent security review |
| HW6 | **HW6.b** durable signed plan, operator grant, replay-safe Host/Native fencing | `host_action_plan`, `host_action_status`; bridge to Native (A22–A28) | **M-HW6.b-inert** contract and denied-by-default coordinator tests first |
| HW6 | **HW6.c** approved APK install/uninstall/permission/app control | `adb_install_package`, `adb_uninstall_package`, `adb_app_launch` (A22–A26) | **M-HW6.c** *only after* independent security, dual-Host/Native lease hardware tests and user approval; else keep disabled |
| **HW7, P4, gated**: fastboot/recovery | **HW7.a** read-only partition/slot/image preflight with device-profile checks | `fastboot_inspect`, `recovery_artifacts_verify` (F02–F05,F10) | **M-HW7.a** no write; Mac/Pi version-aware fixtures |
| HW7 | **HW7.b** high-risk recovery plan and human supervised workflow | `recovery_plan` (F06–F12,A35–A37) | **M-HW7.b-plan** only plan, never generic `flashall`, `erase`, `unlock` executor |
| HW7 | **HW7.c** any physical boot/flash executor | Dedicated hardware-specific recovery service, not default catalog | **BLOCKED** until user-owned hardware, artifact signature, rollback and independent security sign-off |
| **HW8, P4, requires eligible builder** | **HW8.a** Repo/Soong/kernel/ROM worker capability inventory | `aosp_source_status`, `aosp_build_plan` (R01–R03) | **M-HW8.a**. Require supported x86-64 Linux/glibc worker and source/storage budgets |
| HW8 | **HW8.b** durable image/test build worker and CTS/VTS evidence | `aosp_build_run`, `aosp_test_run` (R02–R05,R07) | **M-HW8.b**. Signed provenance and sanitized artifacts; physical flashing still HW7 gate |
| **HW9, P3, independent after HW2/3** | **HW9.a** opt-in Firebase/Play capability discovery/track read | `release_track_list`, `release_status` (E01–E03,E08) | **M-HW9.a**. Account connection/scopes verified; read-only provider |
| HW9 | **HW9.b** staged distribution/edit plan and artifact verification | `release_draft_plan`, `release_artifact_verify` (E02–E04,E07) | **M-HW9.b**. No default publish, no account ownership inferred from SDK |
| HW9 | **HW9.c** release commit, staged rollout, halt and audit | `release_commit`, `release_halt` (E05–E06) | **M-HW9.c** user-approved provider-bound action only; separate rollback and independent review |

Effort values are **rough active-development targets**, not unattended
deadlines or guaranteed deliveries. Multiple PR slices in a stage
should merge separately at the daily integration windows. HW9 can
start after build/signing/testing evidence without waiting for HW7/8.

## 4. First two development weeks: exact Host branch/merge intent

| Target Sydney date | Planned Host PR | Blockers / tests | Main merge point |
| --- | --- | --- | --- |
| Tue **13 Oct** | Adopt catalog and these stream-separated plans | Documentation only, Markdown/hygiene + exact head | **M-PLAN** into main immediately after gates |
| Wed **14 Oct** | `HW0.a` Toolchain inventory tests → CLI adapters | Synthetic "Java installed but PATH bad", Mac vs Pi Fastboot versions, `--help` only | **13:00/18:00 M-HW0.a**, if green |
| Thu **15 Oct** | `HW0.b` ability/profile public schema, Tool-selection fixtures | Three original Tools remain accessible and identical | **13:00/18:00 M-HW0.b**, if green |
| Fri **16 Oct** | H1 prep: bounded ADB transport read and missing-device denial | CLI stderr redaction, no real device mutation | **M-HW1.a** small green slice or explicit blocked record by 16:00 |
| Mon–Fri **19–23 Oct** | Complete `HW1.a`/`HW1.b`/`HW1.c` as independent PRs | New read-only tools/list, fake ADB/fastboot help fixtures, two-platform test matrix | **Merge each independently** at 13:00/18:00 after proof |

This does **not** imply ChatGPT will run unsupervised at those times.
Use the live connected session to perform the merge; blocked proof is
a recorded state, never permission to force merge.

## 5. Owned paths / cross-workstream dependencies

**Host-owned by this plan:** `host/src/android_mcp_host/**`,
`host/tests/**`, Host-specific scripts, docs named `host-*.md`,
Host runtime packaging and Host-only test fixtures. Keep central
`server.py` registration and `mcp_boundary.py` Schema ownership with
a single Host integrator per slice.

**Read-only or shared:** `android/**`, Native Gradle and FGS,
`contracts/**`, top-level authentication/security and
`docs/host-native-coordination.md`. When a Host package needs a
Native field, submit a standalone, versioned shared-contract PR
with Native-owner review before either stream consumes it. Avoid
putting Host changes in Native's working branch or vice versa.

**Hardware ownership:** MacBook is SDK/emulator/build host; sextant is
Linux ARM64 ADB device/test host; raspberrypi is separately managed.
No real tablet APK install, Fastboot flash or UI action is authorized
by this implementation plan. Disjoint read-only Host and Native work
can proceed without each other's approval; shared permission/lease
work cannot.

## 6. Mandatory verification and failure behavior for every Host PR

Every slice must record: source capability catalog IDs; input/output
Schema; explicit target ID and permission; deterministic subprocess
argv and bounds; structured success/error and partial/uncertain
semantics; retry/idempotency; output redaction, artifact retention;
tests for absent CLI, malformed output, repeated calls and offline
devices; actual terminal commands and SHA of the tested branch.

**Locked mandatory local gate:** macOS ARM64 plus sextant Linux ARM64,
both at exact branch HEAD, Python **3.11/3.12/3.13/3.14**
via `HOST_PYTHON=... bash scripts/check-host.sh`, then
`bash scripts/check-host-package.sh`, repository pre-commit/pre-push
security hooks, and explicit no-mutation/fake-ADB HTTP tests.
Optional real device reads require their own scoped consent and
recording; no test may silently target the default connected tablet.
GitHub Actions is blocked by billing: do not pay or mark absent jobs green.

- **M-HWx.y admission:** branch HEAD unchanged, all relevant Mac/Linux
  gates green, source file scope reviewed, no unresolved shared path,
  current remote main rechecked, exact-head squash merge, post-merge
  tree equality. Other Native session then fetches main.
- **On main movement:** rebase only owned/unpublished local branch,
  or merge/reconstruct a pushed exclusive branch; rerun tests at
  new integrated SHA. Do **not** force-push/overwrite another owner.
- **On blocked test, missing SDK/worker, expired grant or CI outage:**
  mark blocked, checkpoint branch and split independently safe
  additions; do not merge a partial privileged feature.
- **Regression rollback:** revert the exact individual Host PR,
  preserve previous v1 Schema and deny writes by default.

## 7. Stage exit criteria and coverage accounting

A Stage is **DONE** only when every corresponding `HWx.y`
merge marker is either backed by a merged PR and verified outcome,
or explicitly labelled **not executable / plan-only / deferred**
with reason, authority, next gate and test evidence. Count of
"95 covered families" is not a count of implemented public Tools.

Keep a compact catalog map for all **95 Host-relevant IDs**:
`family_id -> Tool/application service -> min SDK/tool version ->
platform -> permission -> safety class -> work package -> PR ->
test SHA -> main merge SHA -> status`.
No generic free-form command-runner Tool may be used to fill gaps.

**Ready first:** HW0.a only after confirming current main and this
plan's reviewed public result shape. **Not ready to enable:**
physical install, cross-runtime lease, reboot/flash, arbitrary UI
gestures, Play production writes, unsigned ROM maintenance.
