# Android Host + Native MCP: full-lifecycle capability architecture and staged roadmap

**Date:** 2026-10-12, Australia/Sydney
**Status:** **PROPOSED DESIGN FOR REVIEW; NOT AUTHORIZED IMPLEMENTATION**
**Target main:** `7c4ff1e7350b36c89a59b95a9618c471c8906f5b`.
**Inputs:** [toolchain and Native capability catalog](android-toolchain-capability-catalog-20261012.md),
previous [FastMCP F0 acceptance](host-fastmcp-final-acceptance-20261012.md),
[Host/Native coordination draft](host-native-coordination.md), Android official
documentation cited in the catalog. No executable Tool or privilege change
was made during this research.

## 1. Product decision to evaluate

The desired end product consists of two complementary MCP runtimes:

- **Host MCP** exposes selected, versioned host workstation capabilities:
  Android SDK and CLI toolchains, build/test tooling, ADB, Fastboot,
  emulator, profiling tools, source management and **authorized** device
  recovery. It should cover the complete source-to-APK/ROM/diagnose cycle
  even if Native MCP is unresponsive.
- **Native MCP** exposes Android-app-level device, permission, UI and
  self-monitoring capabilities when its foreground/user-consented runtime
  is healthy, with a credible authenticated paired communication path.
- Their overlap is **intentional**, justified case by case by resilience,
  different privilege levels or test reproducibility. Overlap must not
  create two independent uncoordinated writers.
- Completeness means every relevant capability family is inventoried
  and assigned an executable, plan-only or deliberately unexposed policy.
  It does **not** mean every raw ADB/Fastboot/OEM option becomes a direct
  model-callable command, nor that all permissions are enabled by default.

Retain existing three Host Tools as a backwards-compatible initial
`host-base` profile, not a hard maximum of three Tools. The current
Native Tool remains `device_status` while additional contracts are
designed, reviewed and tested.

## 2. Scope and lifecycle coverage

| Developer lifecycle | Primary tool/backend | Role of Native | Capability value / boundary |
| --- | --- | --- | --- |
| 0. Inventory / prerequisite checks | Host versions, JDK/SDK/ADB/Fastboot, source checkout and device registry | Native self-health, Android OS capabilities and permission inventory | Know what is installed vs runnable vs authorized |
| 1. Source / SDK setup | Git/Repo, SDK package listing and signed install/update planning | Native reports compatibility/API needs | Never modify source or SDK from free-form shell |
| 2. Code quality / local build | Gradle wrapper, lint, artifact reports and build cache | Self-tests under Kotlin/Android test frameworks | Bounded jobs and reproducible artifact lineage |
| 3. Package, sign and verify | APK/AAB, apkanalyzer, AAPT2, apksigner, zipalign, bundletool | PackageInstaller with user action when allowed | Signing private keys never visible in MCP input |
| 4. Emulator/device provisioning | AVD/emulator snapshots, device list/ADB pair/connection | Native service starts only with user opt-in | Emulator effects isolated from real hardware |
| 5. Deploy / update / run | ADB typed install/test/launch/stop/uninstall | App-controlled launch/install requests where Android permits | Irreversible/privileged commands need signed narrow grants |
| 6. UI test / reproduce | Host screenshot, UI Automator, ADB input; Gradle instrumentation | Accessible hierarchy/gesture and consented capture | Shared user action intent, independently authorized backend |
| 7. Debug / observe | logcat, dumpsys, bugreport, process and file inspection | Self diagnostics and allowed package/sensor state | Sensitive capture/retention/redaction |
| 8. Measure and optimize | Perfetto/Simpleperf, startup/jank/memory benchmarks, retrace | App-owned traces, health counters | Durable bounded trace jobs and safe file export |
| 9. Recover app/service | Host ADB independent of Native; re-establish transport | Native self/service restart with user's consent | Host fallback does not imply privilege escalation |
| 10. Recover Android OS / ROM | Fastbootd, OTA, AOSP build images, slot/partition planning | Normally unavailable in bootloader mode | Human-owned high-risk runbooks, not unattended flash |
| 11. Reproduce/release evidence | Versioned source/SDK/build/ABI/package/target hashes | Provenance of native app and pairing identity | Signed receipts, rollbacks and result artifacts |
| 12. Distribute, monitor and halt application releases | Optional Firebase App Distribution and Google Play Developer API provider | Tester installs through approved Android flow | Scoped OAuth, consent and per-release write approvals |

This lifecycle includes **platform/ROM development** as a later distinct
worker profile. Current AOSP documentation specifies a **64-bit x86 Linux
(glibc)** build machine, approximately **400 GB free disk** and at least
**64 GB RAM**; neither a Pi ARM64 node nor the MacBook ARM64 host is
automatically a supported complete Android OS build worker. The Pi remains
an independently verified ADB/test node until a supported build
environment is provisioned.

## 3. As-is responsibility and availability truth

At the reviewed commit, Host FastMCP provides only
`device_status`, `adb_observe` and `adb_develop` (two read-only
diagnostic action variants, two mutation variants that are disabled unless
trusted components are injected). The Kotlin Native service registers
only minimal local `device_status`; its N3 foreground lifecycle is
real but does **not** grant Android Accessibility or screen capture.

Host uses standalone FastMCP 4.1.0 and its typed Tool registration.
Native uses the official Kotlin MCP SDK and Ktor loopback; neither service
may silently convert presence of an installed binary into execution
authorization. The Native endpoint at 127.0.0.1:38765 cannot be reached
from an unrelated remote ChatGPT client without an explicitly engineered
secure transport.

Tool discovery on the Mac found ADB 37.0.1, Fastboot 37.0.1, SDK/Emulator,
Build Tools 36 and Android CLI candidates. But at the time of this check,
`sdkmanager --help` and `apkanalyzer --help` could not resolve Java.
On sextant Linux ARM64 only ADB 34.0.5 was confirmed on PATH from this
toolchain set; Fastboot/emulator/build-tools were not. These are
**versioned capability gaps** that `host_toolchain_inventory` must
report with reasons and corrective prerequisites, not conceal.

## 4. Proposed architecture: capable providers, focused public contracts

```text
ChatGPT / approved MCP client
     │
     ├── Host FastMCP public Tool catalog (capability profiles)
     │     └── Host application use cases / authorization / durable jobs
     │           ├── Android SDK adapter (sdk/avd/emulator/Gradle/artifacts)
     │           ├── ADB transport + typed allowlisted operations
     │           ├── Fastboot inspect + separate maintenance plan adapter
     │           ├── Profiler/trace/read-only diagnostic adapter
     │           ├── AOSP Repo/Soong build worker (eligible host only)
     │           └── artifact store, grants, audit, versioned jobs
     │
     └── Native Kotlin MCP public Tool catalog (capability profiles)
           └── Native permission-aware application use cases
                 ├── OS info/self health/filtered PackageManager
                 ├── opt-in UI inspection/gesture (policy constrained)
                 ├── opt-in MediaProjection screen capture
                 ├── user-directed app/file/notification APIs
                 └── authenticated pairing/fencing (NOT implemented)
```

Key architecture decisions to review:

1. **Different provider ≠ different safety policy.** Each action carries
   source origin, exact target identity, required permission, side effect
   and its own bounded output. All execution uses argv arrays, strict
   per-tool templates and fixed binary paths, never user-controlled
   `adb shell <arbitrary text>` or `fastboot oem ...`.
2. **Versioned profiles, not a monolithic registry.** Base observation
   Tools remain visible without privileged service configuration.
   Host-build, host-emulator, host-test, native-ui, trusted-mutation and
   maintenance/recovery profiles require local configuration and a
   proven target/environment. FastMCP 4.1 composition/visibility behavior
   must be POC-tested with real tools/list and ChatGPT surfaces before
   promising dynamic filtering.
3. **Read versus write is a Tool boundary.** Existing `adb_develop`
   stays backwards-compatible initially; migrate to focused
   `adb_logcat_read`, `adb_package_info`,
   `adb_test_instrumentation_plan`, and separately
   `adb_install_package`/execution Tools under versioned contracts.
   No Tool mixes model-visible read-only hints with reachable mutation.
4. **Common canonical use-case layer; independent execution adapters.**
   A request like "capture current screen" may have two providers
   but each has its own effective permissions and result provenance.
5. **Capability discovery is runtime evidence.** Expose states
   `not_installed`, `installed_unusable`, `available`,
   `authorized`, `temporarily_unavailable`, and
   `unsupported` distinctly; no speculative "supported" indicator.
6. **Artifacts use bounded handles.** Screenshots, APK comparisons,
   traces, bugreports and build outputs are stored with size, MIME,
   SHA-256, redaction/sensitivity classification and retention policy.
   Large binary outputs do not become unbounded JSON Tool responses.
7. **Long jobs are durable application state, not MCP sessions.**
   For builds/tests/recordings: plan → authorize → start → poll/read →
   cancel/cleanup → review. Persist operation ID and status in a
   trusted Host job store; restarts and duplicate requests are explicit.

## 5. Candidate focused public Tool contract sets

Names are **proposals**, not implemented registrations. Tool counts are
not quotas; select a coherent set based on use cases and measured
ChatGPT tool-selection quality. These are distinct families, not direct
wrappers for every OS subcommand.

| Family | Proposed Host Tools | User-facing outcome | Risk / exposure |
| --- | --- | --- | --- |
| Capability / targets | `host_toolchain_inventory`, `adb_devices_list`, `adb_device_status`, `fastboot_devices_list` | Know valid tools, devices, transport/modes and limitations | D0/D1, base |
| Observability | `adb_device_diagnostics`, `adb_package_list`, `adb_package_info`, `adb_logcat_read`, `adb_dumpsys_read` | Bounded device and application investigation | D1, base |
| SDK setup | `sdk_packages_list`, `sdk_package_install_plan`, `sdk_package_install` | Reproducible local SDK setup | D0/W3, opt-in |
| Build & review | `android_build_plan`, `android_build_run`, `android_build_result`, `apk_inspect`, `apk_verify` | Build/debug/release provenance | D0/W3, trusted workspace |
| Artifacts/signing | `apk_compare`, `apk_sign_plan`, `apk_sign`, `app_bundle_inspect` | Validate/installable release artifacts | D1/W3, keystore never model-visible |
| Emulator | `avd_list`, `avd_create`, `emulator_start`, `emulator_stop`, `emulator_snapshot_manage` | Disposable reproducible Android environment | D0/W2–W3, AVD-only |
| Testing | `android_test_plan`, `android_test_run`, `android_test_result` | Unit/instrumented/UI test evidence | W2, explicit device/AVD |
| Deployment | `adb_install_plan`, `adb_install_package`, `adb_uninstall_package`, `adb_app_launch`, `adb_app_stop` | Controlled application lifecycle | W2/W3, explicit grants |
| UI and media | `adb_ui_inspect`, `adb_capture_screen`, `adb_record_screen`, `adb_ui_action` | Reproduce screens and input as backup | D1/W2, scoped/consent |
| File exchange | `adb_pull_file`, `adb_push_file` | Bounded pull/push with hash and safe roots | D1/W2, allowlisted paths |
| Diagnostics/jobs | `adb_bugreport_collect`, `perfetto_capture`, `simpleperf_capture`, `diagnostic_artifact_get` | Crash/performance reproduction | D1/W2, bounded stored artifacts |
| Connections | `adb_transport_inspect`, `adb_transport_pair`, `adb_forward_inspect`, `adb_forward_manage` | Safe connection setup/repair | D0/W2, pairing owner |
| Recovery | `fastboot_inspect`, `recovery_plan`, `recovery_artifacts_verify` | Preflight and physically supervised repair | D0/D1, maintenance profile |
| AOSP development | `aosp_source_status`, `aosp_build_plan`, `aosp_build_run`, `aosp_test_run` | Source-to-ROM/CTS/VTS lifecycle | W3, build-worker profile |
| NDK/native debug | ndk_toolchain_inventory, native_build_plan, native_build_run, native_crash_symbolize | Reproduce C/C++ Android builds and symbolized native crashes | D0/W3, pinned project and tools |
| App distribution | release_track_list, release_draft_plan, release_artifact_upload, release_commit, release_halt | Tester distribution, approved staged rollout and release monitoring | D1/W3, separately connected provider with account-scoped grants |

For **Native**, the proposed primary Tools are
`native_device_status` (existing),
`native_system_snapshot`,
`native_permission_status`,
`native_package_query`,
`native_app_health`,
`native_ui_inspect`,
`native_capture_screen`,
`native_record_screen`,
`native_ui_action`,
`native_file_exchange`,
`native_app_launch`,
`native_service_status` and `native_pairing_status`.
Registration of anything beyond status requires its Android permission
and authentication gates; many features cannot be delivered by an
ordinary app under current Android policies.

**No generic public Tools** named `execute_adb`, `run_shell`,
`fastboot_oem`, or `arbitrary_gradle_task`; exhaustive coverage
comes from audited command families under focused operations.

## 6. Valuable overlap: why both Host and Native should own some features

Redundancy is justified only if the alternate provider adds a real
reliability, debugging or permission advantage. Retain explicit
provider-specific evidence and avoid silent privilege downgrade/upgrade.

| User goal | Preferred normal provider | Host fallback / additional value | Native fallback / additional value | Preconditions and risks |
| --- | --- | --- | --- | --- |
| Device and service health | Native local self-health + Host discovery | ADB can see device even if Native process crashes | Native can report its own service and permissions when USB/ADB is absent | Authenticated Native transport must exist before remote status is used |
| OS/API/build/battery/storage | Native allowed Android APIs | ADB can inspect more system services and detect unauthorized/offline state | Native useful when no authorized ADB cable is available | Some Native package/device data is filtered by sandbox |
| Screenshots and screen recording | Native MediaProjection with current consent | `adb exec-out screencap -p` / `screenrecord` when Native service is broken | Native can capture with user grant when ADB is unavailable | Sensitive screen data; avoid secure-screen bypass and unapproved capture |
| UI hierarchy and interaction | Instrumented UI Automator for tests or intentionally enabled Native UI API | ADB UI tree/input can repair test flow if Native UI automation fails | Native consented UI information may avoid brittle ADB command output | Per-action approval, foreground/current-window validity, no unattended generic gestures |
| Package inspection | Host ADB targeted `pm`/`dumpsys` | Broader diagnostics than normal APK sandbox | Native PackageManager can show only caller-visible apps | Do not assume native package enumeration is complete |
| App launch/restart | App/dev test runner or scoped Native Intent | ADB can launch/force-stop even when Native application is dead | Native can launch allowed apps with no cable, if authorized | Force-stop or clear-data is a write; never silently replay |
| Logcat/crashes | Host ADB bounded logcat/bugreport | Captures OS and other processes (sensitive) | Native reports its own app crashes, structured state | Native ordinary app cannot read arbitrary global logcat |
| File transfer | Host ADB from approved roots | Pull app artifacts after Native crashes | Native SAF/user-selected file export works without ADB | Path sandbox, size/retention, no arbitrary /data exfiltration |
| APK testing/deployment | Host Gradle + ADB with explicit grants | Reinstall/diagnose broken Native APK | Native PackageInstaller may request system-mediated user action | Not interchangeable silently; signed build and consent |
| Reboot/recovery | Host ADB then Fastboot | Host can inspect bootloader when Android/Native do not boot | Usually unavailable once Android is down | High-risk profile with physical owner confirmation; no automatic wipe/flash |

### Failure-domain selection (not an automatic privilege escalator)

| Incident | Safe first response | When Host can help | When Native can help | Must not occur automatically |
| --- | --- | --- | --- | --- |
| Native MCP crash / permission revoked | Check ADB identity and read-only status | USB-authorized ADB diagnostics, bounded logs/screenshots with permission | User explicitly re-starts/re-consents Native service | Force-install, root, wipe, background resurrection or unlogged UI action |
| Host MCP or ADB daemon down | Check local availability and prevent stale device selection | Repair host service/ADB per typed approved operation | Continue Native local status if the approved secure relay is alive | Treat loopback Native endpoint as public/authenticated |
| USB disconnect | Mark Host device unavailable | Wait/reconnect with verified transport and expiry | Native may operate only with its actual user permissions | Reuse stale serial or auto-pair with a different tablet |
| Android OS boot failure | Detect explicit bootloader/fastboot mode | `fastboot devices`, narrow `getvar`, image preflight | Native is normally unavailable | Assume booted Android is available; automatic flash/erase/unlock |
| Two Hosts or Host+Native simultaneously request a write | Reject/queue until authenticated lease arbitration | Durable Host operation record and fencing token | Native owns current UI mutation lock and stale-token rejection | Two independent writes without fencing |
| Last operation result unknown after timeout | Return `uncertain` with operation ID, require reconciliation | Re-probe exact target and signed result | Verify app-level state if healthy | Blind retry of install, force-stop, reboot, erase or gesture |

The Host can be an emergency diagnostic **backup**, not a hidden
superuser channel. When Native goes offline, routine approved reads
may switch to the Host if ADB identity/permissions are still valid.
An existing privileged grant to Native never grants Host the same
privilege by implication; mutation fallback requires a **new**
authorization bound to the exact Host action and device state.

## 7. Required public contract / state before expanded Tools

All new operations need an explicit versioned schema contract with
at least the following concepts:

| Field/concept | Requirement |
| --- | --- |
| `source` | `host` or `native`, command/backend version, permission posture |
| `target_ref` | Resolved, approved target returned by a discovery Tool, not model-invented |
| `preconditions` | Connection mode, API/ABI, app scope, consent/ADB authorization and version constraints |
| `safety_class` | D0, D1, W2, W3, X4 or X5 with honest annotations and effect description |
| `action_plan` | Structured command template, exact target, expected writes, artifact hashes and rollback |
| `authorization` | Server-side identity, per-action signed grant where necessary; never caller `approved=true` |
| `result` | Structured status `ok/partial/denied/unavailable/uncertain`; typed error; bounded outputs |
| `operation_id` | Stable handle for long jobs and repeat requests; dedupe/recovery outside MCP session |
| `artifact_ref` | Bounded file, MIME, SHA-256, origin, sensitivity, retention and access permissions |
| `audit` | Durable record before and after state change; target boot epoch/fencing when applicable |

Preserve the existing Host v1 error envelopes and three-tool names
through compatibility migration. New Tool variants require S2 review
of how domain `status=error` differs from MCP `is_error`;
do not accidentally turn every invalid domain action into an
unhandled Tool error just because the advertised input schema is stricter.

**Device identity:** a Host `adb` serial/transport ID and a Native
installation identity are **not equivalent**. Pair with an authenticated
challenge, store binding privately and invalidate stale linkage on
reinstall, reboot, disconnect, firmware change or pairing replacement.
The cross-runtime lease/fencing design in
`docs/host-native-coordination.md` is still draft; don't claim it exists.

**Tool metadata:** advertise real effects. ADB discovery can start
a Host daemon, and mixed `adb_develop` actions can be potentially
destructive under injected trusted configurations. Separate
read-only diagnostics from write/maintenance Tools rather than
mislabeling them.

**Long-running jobs:** build, test, trace, upload, install or ROM image
validation needs a durable job handle and cancellation semantics.
A timed-out MCP request is not proof the underlying subprocess/device
action stopped. Never infer a retry is safe after loss of connection.

**Privacy:** logcat, bugreports, screen recordings, package lists,
system screenshots, network traces and artifacts can contain
passwords, notifications, user data or secrets. Apply per-tool
minimum capture, destination whitelist, size caps, output redaction,
short retention and explicit collection consent.

## 8. Prioritized staged implementation (proposed)

Priority classes: **P0** critical foundations/diagnostics, **P1**
routine full app development, **P2** UI/performance and valuable
redundancy, **P3** authorized writes, **P4** physical recovery
and full AOSP platform development.

| Stage | Priority | Outcome and candidate work packages | Parallel ownership | Must pass before next dependency |
| --- | --- | --- | --- | --- |
| **0 — capability and security contract** | P0 | Tool/SDK version discovery; target IDs and mode registry; client profiles; canonical errors/limits; permissions matrix; job/artifact state and Native reachability design | Host toolchain probe, Native feature model, security contract tests can work in disjoint files | Installed-vs-runnable truth, exact three existing Tools unaffected; threat model and auth/fallback semantics accepted |
| **1 — diagnostic breadth** | P0 | Host typed `dumpsys`, package/system/network reads, richer logcat, target/wait/status, safe Fastboot presence; Native package/permission/device/self-health | Host discovery/diagnostics and Native self-health work independently; single owner for public registry | Both runtimes' shape/contracts and negative device selection; no new Native sensitive Tool before auth gate |
| **2 — local SDK, build and artifact chain** | P1 | JDK/SDK readiness, Android CLI/legacy detection, Gradle plan/build, lint/test report, apkanalyzer, APK/AAB inspection, signing verify, artifact store | Host SDK adapter, build adapter, artifact verifier separate; shared release docs/registry serial | Deterministic build from pinned toolchains; verified binaries, bounded workspace, no key leaks |
| **3 — emulator and app testing** | P1 | AVD list/create/start/stop/snapshots, isolated AVD IDs, Gradle test/instrumentation, typed app deployment/test plans, test-report handles | Emulator lifecycle, test runner and package planner separate | Emulator-only proofs, explicit physical exclusion, safe cleanup and no install side effects without authorization |
| **4 — UI, media and file backup paths** | P2 | Native consented screen/UI; Host ADB screenshot/UI tree/input, bounded pull/push and files; healthy/native-down recovery tests | Native permission/MediaProjection, Host screenshot/UI, file transfer distinct work packages | User-consent and sensitive output policy; no unrestricted shell/UI control; cross-runtime preference/health matrix verified |
| **5 — profiling and fault diagnosis** | P2 | Bugreport, Perfetto/Simpleperf, crash/retrace, app-jank/battery/memory report and redacted stored artifacts | Tracing provider, analysis pipeline and artifact store independent if stable artifact contract | Bounded duration/storage and subprocess cancel; timeout/disconnect; zero real user data in fixtures |
| **6 — trusted deploy / concurrent controls** | P3 | Authenticated pairing, durable Host/Native fencing, signed operator grants, per-action idempotency, install/uninstall/app-state writes, safe pairing/forwarding | Native lease, Host coordinator, operation policy, external auth separate after shared contract freeze | Independent security review, replay/expiry/two-Host/USB failure tests, explicit opt-in hardware approvals |
| **7 — Fastboot/recovery maintenance** | P4 | Fastboot mode inspection, getvar, verified boot/slot/image catalog; approved reboot/OTA, separate supervised flash executor | Read-only Fastboot adapter can be built earlier; writes require exclusive owner | Exact hardware profile, signed artifact verification, brick/wipe warning, physical operator confirmation, rollback/recovery plan |
| **8 — AOSP/ROM full lifecycle** | P4 | Repo/source manifests, AOSP target/build worker, kernel/partition artifacts, CTS/VTS, OTA image validation, staged device bring-up | AOSP source/build/tests on eligible Linux machine, image auditor/Native integration distinct | Machine resources and supported build OS proven; no implicit Pi/macOS full-ROM support; maintenance gate for flashing |
| **9 — distribute and release** | P3 | Optional Firebase tester distribution, Google Play track/release read, approved draft/edit/commit, staged rollout and monitoring | Artifact/release provider separate from Native app and physical device controls | OAuth-scoped account connection, real app ownership, versioned artifact digest, per-release approval, audited state and provider-specific rollback limits |

### Recommended near-term order

**Stage 0 and read-only Stage 1 come first**, because discoverability,
target identity and cross-runtime safety affect every later action.
After the public contract is stable, Stage 2 SDK/artifact analysis
can proceed in parallel with independent Native device self-health
reads. Stage 3 emulator/test automation then yields safe disposable
hardware for the higher-risk Stage 4–6 features.

**Stage 7 read-only Fastboot inspection** can be researched with
Stages 1–2, but Fastboot writes stay last. Stage 8 AOSP source/build
work is legitimate full-lifecycle scope but needs a dedicated
eligible build machine and independently reviewed physical recovery
path. **Stage 9 application distribution can start independently
after Stage 2–3 package signing and tests are accepted**; it does not
depend on ROM flashing. Store publication, rollouts and stops require
separately connected owner-authorized provider accounts and cannot be
implicitly enabled by local SDK access. No stage may turn
privilege-sensitive execution on merely because code has been implemented.

### Short feedback slices within each stage

Use one independently revertible PR per Tool family or safety
boundary. Every slice must have: accepted S1–S5 prerequisites, a
failing protection test, real FastMCP/Kotlin tools/list and
tools/call contract tests, bounded subprocess/permission negative
cases, an owner of every changed file, exact commit SHA, local
Mac/Linux verification (Native uses Gradle/AVD matrix when applicable),
and a post-merge same-tree check.

**No paid GitHub Actions.** The 2026-10-12 repository policy uses
the locked local MacBook Python 3.11–3.14 matrix and Linux ARM64
counterpart, security/packaging checks and exact-head/merged-tree
evidence. Android Native Kotlin/emulator coverage is separate.
Never claim a tool-selection or real-device test passed merely
because Python unit tests passed.

## 9. Explicit work-package dependency graph

```text
Official command catalog + real tool versions + Native source audit
                         ↓
                 Stage 0 S1/S2/S3
                  ↙         ↘
        Host diagnostics    Native app status/permissions
                  ↘         ↙
             Tool selection & fallback contract
                       │
              Host SDK/build/artifacts  ── Native health continued
                       │                └── Optional distribution (Stage 9;
                       │                    separate provider authorization)
            Emulator/test/deployment plan
                       │
              UI/media/file overlap
                       │
              Perfetto / debugging
                       │
        Authenticated Native pairing and Host fencing
                       │
                 Safe bounded writes
                       │
      Fastboot inspect → separate physical recovery gate
                       │
         AOSP source/build/test/ROM lifecycle
```

A parallel implementation worker owns its exclusive worktree and
files. The integrating engineer exclusively modifies central
FastMCP `server.py`, Kotlin `LocalMcpGateway.kt`, shared JSON
Schemas, package locks and common security configuration.
**ChatGPT itself is the intended implementer** in the current
user-selected workflow; do not delegate code to paid Claude/Codex
agents or consume paid GitHub Actions minutes.

## 10. Verification and product-surface evaluation to design

| Category | Minimum executable evidence |
| --- | --- |
| CLI compatibility | version-aware command discovery, missing Java, absent Fastboot, unsupported AVD/ABI and clean fail-closed errors |
| Existing public contracts | exactly three base Host Tools, original response Schema and error cases, current Native status unaffected |
| Valid target and mode | device ID binding, unauthorized/offline, stale serial, USB disconnect, reboot epoch, two connected devices |
| Work safety | no raw shell, untrusted path, arbitrary `fastboot oem`, reboot/install/gesture without grant |
| Output/data privacy | screens/bugreports/logcat secret redaction, bounds, retention, no arbitrary host/device file reads |
| Staged jobs | double submit/retry, worker restart, cancel/timeout with child process cleanup, partial/unknown status |
| Overlap | Native down + ADB up, ADB down + Native up, both available concurrent, both unavailable |
| Emulator isolation | exact disposable AVD name, forbid physical install, destroy/restore only with human acknowledgement |
| Flash/recovery | verify image hash and codename, current slot/lock state, mismatched device denial and manual confirmation |
| ChatGPT MCP use | golden prompts by lifecycle phase; select Tools and args; must not select blocked/mutating tools on vague requests |
| Platforms | macOS ARM64 Host; Linux ARM64 ADB node; Native device emulator matrix; separate Linux AOSP build worker |

Golden-prompt classes should cover no-device questions, valid
single/multiple targets, SDK missing, package build and comparison,
instrumentation on a disposable emulator, Native unavailable,
fallback screenshot, sensitive bugreport, unknown app ID,
approved/rejected install, Fastboot mode without OS, mismatched
firmware image, uncertain write result and user's refusal to enable
dangerous permissions. ChatGPT Chat and Work behavior should be
measured separately if both are accepted target surfaces.

## 11. Decision register — to be accepted before implementation

| Decision | Proposed default | Alternative / blocker |
| --- | --- | --- |
| Product scope | Full app and platform lifecycle with explicit high-risk plan-only coverage | Full automatic flashing/unlock is not an acceptable general MCP Tool |
| Number of Tools | Focused action-oriented catalog, profile-scoped to installed/authorized capabilities | Arbitrary generic ADB/shell/Fastboot executor rejected |
| Legacy three Host names | Keep compatibility while adding focused read/write Tools; deprecate only with migration | Removing/repurposing existing v1 Tools needs a versioned contract decision |
| Native permissions | User-visible opt-in and Android-supported APIs, no default Accessibility/MediaProjection | Product/API policy and physical consent are required before enablement |
| Backend fallback | Independent, explicit target/consent check for each provider, no permission inheritance | A dead Native runtime cannot grant Host a device mutation lease |
| Durable jobs | Explicit persistent IDs, idempotency rules and uncertainty states | MCP session or in-memory lock is not durable state |
| Fastboot | Inspect first; only approved dedicated physical recovery workflows may write | Unlock/erase/flashall require separate, supervised design |
| AOSP | Provide an eligible x86_64 Linux/glibc worker for full builds; Repo/Soong lifecycle | Neither macOS ARM64 nor Pi ARM64 qualifies by assumption |
| App distribution | Separate opt-in Firebase/Play provider, read before write and no default publishing | External account connection, release policy and human approval required |
| Android SDK CLI | Prefer modern `android` CLI only after exact installed/version support proof; fallback to legacy with tests | Installed Java-dependent wrappers currently fail in Mac session |
| Security gates | Zero-paid local matrices, device/Native permission and independent high-risk review | Paying for GitHub Hosted Actions is not required/authorized |
| Implementation order | Stage 0 safety, routine Stages 1–5, gated Stages 6–9; Stage 9 follows build/artifact evidence | Read-only Fastboot can occur earlier; distribution does not depend on ROM flashing |

## 12. Questions that need evidence, not guesses

1. Which Android device families/ROMs should be physically enrolled for
   privileged development and recovery? A generic model value is not
   an approved target or a hardware compatibility profile.
2. Which **real** Native Android permissions are acceptable for each
   use case, especially Accessibility and screen recording? A
   development app is not automatically an accessibility service.
3. Is ChatGPT ordinary Chat, Work, or both the target public MCP
   consumer? Current loopback endpoints and product-surface
   interoperation have different constraints.
4. Which Mac JDK location is correct for each SDK/Gradle CLI? The
   installed wrappers did not run with the default shell's Java.
5. Do the current Android CLI replacements for SDK/AVD/emulator
   cover all planned operations on the pinned installation, or do
   we need versioned fallback to legacy tools?
6. Where are durable job/artifact records stored and how are
   sensitive reports deleted? Where do operator signing keys live?
7. What machine, if any, will be provisioned for full AOSP/Linux
   source/image builds? Existing Pi ARM64 is not sufficient evidence.
8. How will Host authenticate Native on the device without exposing
   `127.0.0.1:38765` over a public/unauthenticated bridge?
9. What physical confirmation and rollback rules should apply to
   Fastboot flash/unlock/erase? This must be a separate sign-off.
10. Are there vendor-specific capabilities (e.g. LineageOS/OEM)
    needed beyond AOSP's documented command families? These must
    be added as narrowly scoped device profiles, not a generic OEM
    command executor.
11. Which, if any, authorized app-distribution accounts and rollout
    approvals are intended for ChatGPT? Neither local APK tooling nor
    a model's intent grants Google Play/Firebase publishing authority.

**Next eligible action:** accept the full-lifecycle target scope and
Stage 0 inventory/security contract as planning output, then create
small S1–S5 work packages. The document does **not** authorize
activation, mutation, flashing, hardware tests, Android permissions
or an SDK installation.
