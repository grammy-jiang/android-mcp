# Android toolchain capability catalog — Host and Native MCP

**Review date:** 2026-10-12 (Australia/Sydney)
**Target:** `grammy-jiang/android-mcp`, source main
`7c4ff1e7350b36c89a59b95a9618c471c8906f5b`.
**Purpose:** Identify the meaningful feature families throughout app development,
release, diagnosis, automation and OS maintenance before choosing MCP Tool APIs.

This is a capability **inventory and design input**, not a list of
implemented Tools or a permission to execute these commands on a tablet.
It covers the documented command families and normal app APIs, not every
undocumented OEM fastboot verb or every arbitrary device shell program.
Original official references are linked in the source register at the end.
Availability, documented existence, support on an actual device, and
ChatGPT-visible exposure are four distinct facts.

## Terminology / risk

- **Host** = Python FastMCP on macOS/Linux; may use vetted installed CLI
  programs and explicit, never model-supplied command templates.
- **Native** = Kotlin MCP service on Android, subject to normal Android app
  sandbox, user-granted permissions and foreground lifecycle requirements.
- **D0** = inventory, metadata, version checks and no sensitive device data.
- **D1** = scoped diagnostics or sensitive read, finite bounded collection.
- **W2** = bounded/reversible device or host write; signed request and approval.
- **W3** = costly/persistent host write or major device state change.
- **X4** = potentially destructive flashing, erase, root, unlock, recovery,
  or critical system state; **plan/inspect only by default**, separate
  physical-device-aware operator procedure.
- **X5** = unrestricted shell/OEM commands, unconstrained privilege/bootloader
  control; not exposed as generic model-executable Tools.

Stages are *proposals*: `0` registry+security design, `1` diagnostics,
`2` SDK/build/artifacts, `3` tests/emulator/deployment, `4` UI/files/fallback,
`5` profiling/observability, `6` authenticated joint control,
`7` fastboot/recovery, `8` AOSP/ROM builds.

## Existing repository and host facts

| Surface | Confirmed current state | Limit |
| --- | --- | --- |
| Python Host | Three registered Tools: `device_status`, `adb_observe`, `adb_develop` | The latter allows bounded logcat/package reads and previews, not default mutation |
| Android Native | One real device-side Tool: `device_status`, reporting minimal loopback service status | No current screenshot, Accessibility, package scan, UI action, install, or root |
| Native transport | User-started, local-only Kotlin service on `127.0.0.1:38765`; two UI lifecycle modes with process-local port ownership | No caller authentication, no approved external relay, no distributed lease |
| MacBook | `adb` and `fastboot` 37.0.1; registered OpenJDK 17.0.20.1; SDK Build Tools 36.0.0, Emulator 37.2.12.0, Gradle 9.6.0 | Fresh zsh successfully ran Java/Javac/Gradle version, SDK-local sdkmanager 22.0, apkanalyzer, apksigner and Emulator version; no real device test |
| Mac SDK binaries | `apksigner`, `zipalign`, `aapt`/`aapt2`, `d8` and SDK-local `apkanalyzer` verified on disk | JAVA_HOME and SDK bin paths persisted for zsh; Homebrew ADB/Fastboot preferred; GUI launchctl environment denied under SIP |
| sextant Linux ARM64 | Debian `adb` 34.0.5 and newly installed `fastboot` 34.0.5 | Official Debian arm64 package validated; no full SDK/AVD toolchain detected on PATH, no actual bootloader test |
| raspberrypi Linux ARM64 | Debian `adb` 34.0.5 and newly installed `fastboot` 34.0.5 | Second Pi 5 confirmed same official packages, no project branch change or device operation |
| Host/Native pairing | Draft state machine / fencing rules in `docs/host-native-coordination.md` | NOT implemented; Host-side process locks cannot arbitrate Native or another Host |
| Repo security | Default no root/arbitrary shell/public listener/device mutation; all three Tool output Schemas versioned | Claims below beyond the current three are design candidates only |

No physical-device command was executed to prepare this catalog. The
MacBook's CLI help and `fastboot --help` were inspected, and the
source registry was cross-checked with current official docs.

The installation follow-up and exact version validation are recorded in
[2026-10-12 toolchain setup evidence](android-development-toolchain-setup-20261012.md).
The Mac's JAVA_HOME setup and Pi Fastboot installations were performed after
the original exploratory inventory, without running device-changing commands.

## A. Android platform-tools: ADB host service, transport and connection

| ID | Feature family / representative commands | Host | Native equivalent | Risk | Stage | Official |
| --- | --- | --- | --- | --- | --- | --- |
| A01 | Discover USB/emulator targets: `devices -l`, state, serial, transport IDs | existing | local status only | D0 | 1 | O02 |
| A02 | Inspect ADB server/backend/version/features, host-features | partial | none | D0 | 0–1 | O02 |
| A03 | Wait for device/recovery/offline/disconnect, bounded deadlines | proposed | native app health | D0 | 1 | O02 |
| A04 | Secure wireless pairing, Wi-Fi connect/disconnect, mDNS browse | proposed | authenticated secure relay, not ADB equivalent | W2 | 4/6 | O02 |
| A05 | Enumerate port forward/reverse routes | proposed | report local listener | D1 | 1 | O02 |
| A06 | Create/remove explicit port forward/reverse routes | proposed | private transport endpoint | W2 | 6 | O02 |
| A07 | USB attach/detach and ADB transport reset/reconnect | proposed | own service reconnect, different transport | W2 | 6 | O02 |
| A08 | ADB daemon start/stop, connection recovery, key inventory | proposed | lifecycle start/stop | W2 | 6 | O02 |
| A09 | ADB global `-s` serial / transport-ID selection | existing | native installation identity | mandatory identity gate | 0 | O02 |

## B. ADB device/app inspection, debugging and sensitive reads

| ID | Capability family / representative source | Host | Native possibility | Risk | Stage | Official |
| --- | --- | --- | --- | --- | --- | --- |
| A10 | System identity / build / security patch / ABI / boot properties | existing probes | Build.* + allowed APIs | D1 | 1 | O01,O03 |
| A11 | Battery, power, memory, storage, displays, network statistics | partial probes | scoped system APIs; limited stats | D1 | 1 | O03 |
| A12 | Package list, targeted `dumpsys package`, permissions, app version | existing partial | PackageManager package visibility filtered | D1 | 1 | O03,O18 |
| A13 | Scoped `dumpsys` services: activity/window/input/battery/meminfo | partial | only app-authorized data | D1 | 1/5 | O03 |
| A14 | Scoped logcat snapshot, package/tag filtering | existing bounded | own app logs, not unrestricted system logcat | D1 | 1 | O01 |
| A15 | Bounded logcat streaming with cursor and stop handle | proposed | app-scoped event stream | D1 | 5 | O01 |
| A16 | Bugreport / `bugreportz` collection, redaction, downloadable artifact | proposed | small self-diagnostic report | D1 | 5 | O02 |
| A17 | Process list, `top`, JDWP process listing, debuggable-app metadata | proposed | self process only | D1 | 5 | O02,O03 |
| A18 | `run-as` on debug-enabled app (scoped files and process) | proposed | Native self-owned files | D1/W2 | 4/5 | O01 |
| A19 | Log/trace artifact sanitize, retention, hashes, metadata | proposed | redact local capture artifacts | D1 | 1/5 | product policy |
| A20 | TCP diagnostics and socket inspection via named allowlisted command | proposed | ConnectivityManager/network API (limited) | D1 | 5 | O03 |
| A21 | SELinux/identity/proc/restricted system info read | existing partial | limited or unavailable under sandbox | D1 | 1 | O03 |

## C. ADB deploy, file, UI and device-side actions

| ID | Family / representative commands | Host | Native counterpart | Risk | Stage | Official |
| --- | --- | --- | --- | --- | --- | --- |
| A22 | APK install, multi-split install, atomic multi-package install | preview only | PackageInstaller session with user interaction | W3 | 3/6 | O02,O17 |
| A23 | Uninstall, retain-data option, package reset/clear | proposed | own application / privileged installer limits | W3 | 3/6 | O02 |
| A24 | Launch Activity/Intent, restart app and force-stop app | proposed | limited Intent launch; self lifecycle | W2 | 3/4 | O01 |
| A25 | Instrumentation tests via `am instrument` | preview only | UI Automator under test runner, not normal Native service | W2 | 3 | O01,O10 |
| A26 | Permission grants/revokes; app-op and settings changes | proposed | user consent and app-owned permissions only | W3 | 6 | O01,O17 |
| A27 | Device-to-Host `pull` and scoped export | proposed | SAF/user-authorized export | D1/W2 | 4 | O02 |
| A28 | Host-to-device `push`, checksum, atomic staging | proposed | SAF/import only when granted | W2 | 4/6 | O02 |
| A29 | `sync` partitions/filesystem updates | plan only | not possible for ordinary app | X4 | 7 | O02 |
| A30 | Screenshot via `exec-out screencap -p` | proposed | MediaProjection with current consent | D1 | 4 | O01,O16 |
| A31 | Screen recording via `screenrecord` | proposed | consented MediaProjection | D1/W2 | 4 | O01,O16 |
| A32 | UI hierarchy from `uiautomator dump` / instrumentation | proposed; OS-dependent | Accessibility nodes if enabled | D1 | 4 | O01,O15 |
| A33 | Input tap/swipe/key/text via typed `input` allowlist | proposed | Accessibility gesture when purpose/permission valid | W2 | 4/6 | O01,O15 |
| A34 | Accessibility/UI Automator cross-app test replay | proposed via test instrumentation | UI Automator test code; not unrestricted app permission | W2 | 3/4 | O15 |
| A35 | Reboot system/recovery/bootloader/sideload modes | plan only initially | generally not normal app ability | X4 | 7 | O02 |
| A36 | OTA sideload through recovery | plan only initially | ordinary app cannot replace recovery service | X4 | 7 | O02 |
| A37 | `adb root`, `remount`, verity, unrestricted shell | never generic model-executable | not normal Native capability | X5 | 7/8 | O02 |
| A38 | `adb emu` to a chosen emulator console | proposed on verified disposable AVD only | not needed | W2 | 3 | O02,O09 |

## D. APK/SDK/Emulator/Gradle toolchain (Host workstation)

| ID | Tool/capability | Host status | Risk | Stage | Official |
| --- | --- | --- | --- | --- | --- |
| H01 | Discover installed SDK, platform-tools, fastboot, Java/JDK, versions and validity | partial host reporting | D0 | 0–2 | O04 |
| H02 | SDK packages list/update/install/uninstall, licenses | SDK-local `sdkmanager` 22.0 and new Android CLI run with existing JDK 17; no install/update executed | W3 | 2 | O04,O05 |
| H03 | AVD list/show/create/edit/delete profiles | `avdmanager` help verified with JDK 17; no AVD modification | D0/W2 | 2 | O04,O06 |
| H04 | Emulator list/start/stop, headless/writable, startup diagnostics | Emulator installed in Mac SDK | W2 | 3 | O07 |
| H05 | Emulator snapshots: list/save/load/reset/restore with artifact inventory | SDK emulator available, not wired to MCP | W2/W3 | 3 | O07 |
| H06 | Emulator camera/network/geolocation/battery/sensor simulation | candidate with AVD-only guards | W2 | 3 | O07 |
| H07 | Gradle wrapper build / variant / task introspection and report | wrapper exists, not Host MCP Tool | D0/W3 | 2 | O08 |
| H08 | `assembleDebug`, package APK/AAB and recorded build artifacts | Gradle 9.6.0 wrapper runs `--version --offline` using JDK 17; actual APK build separately gated | W3 | 2 | O08 |
| H09 | `test`, `lint`, static/security/code inspections | scripted outside MCP; not model-visible | D0/W3 | 2–3 | O08,O10 |
| H10 | `connectedAndroidTest`, test package install/run/results | scripts exist; runner state/target selection needed | W2/W3 | 3 | O10 |
| H11 | APK size, metadata, Manifest, DEX, resource diff (`apkanalyzer`) | SDK-local `apkanalyzer --help` works with JDK 17; no actual APK file analysis performed | D0/D1 | 2 | O11 |
| H12 | AAPT2 compile/link/inspect resources; d8/dexdump intermediate verification | build-tools 36 installed on Mac | W3 | 2 | O04 |
| H13 | `apksigner verify`, cert fingerprint, `zipalign -c` | build-tools installed | D0 | 2 | O12 |
| H14 | Sign/align output; release keystore handling in separate vault | build-tools installed; never expose key material to model | W3 | 2/6 | O12 |
| H15 | R8 `retrace` mapping of obfuscated stack traces | JDK now configured; retrace itself not individually verified | D1 | 5 | O04 |
| H16 | AAB `bundletool build-apks`, device-specific split install, size estimate | not installed on PATH | W2/W3 | 2–3 | O19 |
| H17 | Build/test reports, provenance, manifest and retained artifact IDs | proposed | D0/D1 | 2–5 | O08,O10 |
| H18 | Git source revision/branch/worktree, safe diff and reproducibility | Git installed; shared PR process exists | D0/W2 | 0/2 | O20 |

| H19 | Discover NDK, ABI, Clang, CMake and ndk-build toolchains | not audited/installed as a ready Host provider | D0 | 2 | O26 |
| H20 | NDK C/C++ build, `externalNativeBuild`, CMake and ndk-build | candidate, project toolchain prerequisite | W3 | 2 | O26 |
| H21 | NDK native crash/tombstone symbolization (`ndk-stack`) | candidate with matching unstripped native symbols | D1 | 5 | O26 |
| H22 | Java/JDWP and LLDB native debugger attach | candidate on debuggable/authorized app only | D1/W2 | 5 | O26 |
| H23 | GPU profiling, AGI/system-frame traces | optional graphics profiler provider, version/driver/device dependent | D1/W2 | 5 | O28 |
| H24 | Optional scrcpy USB/OTG mirror, recording and controlled input | third-party tool absent from PATH, separate admission/security review | D1/W2 | 4 | O27 |

**Version-sensitive note:** In the current Android developer docs, the new
`android sdk` and `android emulator` CLI subcommands are recommended and
the legacy `sdkmanager` / `avdmanager` / direct `emulator` entrypoints are
described as deprecated. The old binaries still exist on the Mac. The
future adapter must detect actual installed command semantics and choose a
tested implementation, not hard-code yesterday's spelling. [O05–O07]

## E. Tracing/profiling and reproducible diagnostics

| ID | Family | Host capability | Native counterpart | Risk | Stage | Official |
| --- | --- | --- | --- | --- | --- | --- |
| P01 | CPU/memory/jank diagnostics and `dumpsys` sampling | ADB allowlist | app-process metrics | D1 | 5 | O03 |
| P02 | Bounded `adb shell perfetto` trace collection | candidate; trace artifact storage required | native app trace annotations, not global kernel trace | D1/W2 | 5 | O13 |
| P03 | Simpleperf native/app process performance profiling | candidate, availability/debuggability-dependent | app profileable APIs | D1/W2 | 5 | O14 |
| P04 | Memory/heap and allocation summaries/trace diff | candidate; explicit debug permission | own app memory sampling | D1 | 5 | O13 |
| P05 | Macrobenchmark, Baseline Profiles, startup/jank measurement | Gradle + UI Automator test runner | test-specific, not ordinary service privilege | W2 | 5 | O10,O15 |
| P06 | ANR/crash dump, retrace symbols and structured triage | bugreport/logcat/retrace inputs | app crash report with explicit permission | D1 | 5 | O02,O04 |

## F. Fastboot / fastbootd / recovery (Host, NOT normal Android app)

| ID | Tool/capability | Default mode | Risk | Stage | Official |
| --- | --- | --- | --- | --- | --- |
| F01 | Detect connected bootloader devices (`fastboot devices -l`) | inspect | D0 | 1/7 | O21 |
| F02 | `getvar` allowlisted values: product, slot, unlocked, version | inspect, sanitize outputs | D1 | 7 | O21,O22 |
| F03 | Distinguish bootloader fastboot versus userspace fastbootd (`is-userspace`) | inspect | D0 | 7 | O21 |
| F04 | Inspect active A/B slot, partition metadata and unlock ability | inspect; no state changes | D1 | 7 | O21,O22 |
| F05 | Verify flashing inputs: image hash, model/codename, partition, slot, ABI | local-only plan | D1 | 7 | O21,O22 |
| F06 | Boot/reboot bootloader/recovery/fastbootd, set active slot | approved maintenance action only | X4 | 7 | O21 |
| F07 | Flash partition, update/flashall, boot image, vendor_boot | independent approved recovery executor; no default Tool | X4 | 7 | O21,O22 |
| F08 | Create/delete/resize logical partition, erase/format or wipe-super | plan-only; high-risk physical maintenance | X4/X5 | 7 | O21 |
| F09 | Lock/unlock bootloader or critical partitions, factory wipe | NEVER unattended model execution; often erases user data | X5 | 7 | O21,O23 |
| F10 | GSI status, snapshot-update, fetch partition | read inspection where safe; writes separate gate | D1/X4 | 7 | O21 |
| F11 | OEM-specific `fastboot oem ...` and `--force` | out of generic MCP; bespoke reviewed device profile | X5 | 7 | O21 |
| F12 | `fastboot` recovery after Native and normal ADB unavailable | staged/manual plan with exact physical selection | X4 | 7 | O22 |

Fastboot is **not** a substitute for ADB inside a booted Android session.
Fastboot CLI is installed on the Mac (37.0.1) and now on both Pi 5 machines
(34.0.5). Real bootloader-mode operation remains untested and unapproved.
Bootloader/fastbootd implementation, partition availability and OEM
support must be probed per physical device. Unlocking is a data-wipe
operation on ordinary devices. [O21–O23]

## G. Native app capabilities (Android SDK user/permission scope)

| ID | Capability | Implementation today | Proposed native interface | Risk | Stage | Official |
| --- | --- | --- | --- | --- | --- | --- |
| N01 | Device-local MCP service/health and lifecycle | `device_status` only, loopback N2/N3 | preserve | D0 | 0 | repo Native source |
| N02 | Android OS/build/ABI/app version | not implemented | `native_device_profile` | D1 | 1 | Android Build APIs |
| N03 | Device battery/storage/display/network current state | not implemented | `native_system_snapshot` | D1 | 1 | Android SDK |
| N04 | Native permission/feature readiness | not implemented | `native_permission_status` | D0/D1 | 1 | O15–O18 |
| N05 | PackageManager visible applications and app-specific metadata | not implemented | `native_package_query` | D1 | 1 | O18 |
| N06 | Native own-app diagnostics, errors and long-running status | not implemented | `native_service_diagnostics` | D1 | 1/5 | Android SDK |
| N07 | Accessible UI tree and focus state | not implemented; needs genuine approved use case and user enablement | `native_ui_inspect` | D1 | 4 | O15 |
| N08 | Touch/click/scroll/gesture through Accessibility APIs | not implemented; sensitive/policy-limited | `native_ui_action` | W2 | 4/6 | O15 |
| N09 | Screen capture with MediaProjection consent | not implemented | `native_capture_screen` | D1 | 4 | O16 |
| N10 | Consent-bounded screen recording/stream | not implemented | `native_record_screen` | D1/W2 | 4 | O16 |
| N11 | User-authorized import/export (SAF, app files) | not implemented | `native_file_exchange` | D1/W2 | 4 | Android SDK |
| N12 | Launch explicit known application/activity via Intent | not implemented | `native_app_launch` | W2 | 4/6 | Android SDK |
| N13 | Sensors/location/notifications as expressly permitted | not implemented | focused opt-in capabilities | D1 | 4/5 | Android permissions |
| N14 | Native self/app performance and crash reporting | not implemented | `native_app_telemetry` | D1 | 5 | O13 |
| N15 | PackageInstaller user-approved installation | not implemented | `native_install_request` after consent/auth | W3 | 6 | O17 |
| N16 | User-visible service start/stop, notification status | current native UI, NOT a model tool | `native_service_control` bounded by real user lifecycle | W2 | 6 | repo N3 |
| N17 | Authenticated Host/Native pairing, identity binding | draft only | `native_pairing_status` | W3 | 6 | repo coordination |
| N18 | Durable replay-safe cross-runtime action leases | draft only; NOT a current safety boundary | `native_lease_status`/internal protocol | W3 | 6 | repo coordination |
| N19 | DeviceOwner/enterprise admin functions | NOT normal app power; provisioning required | separate managed-device product profile | W3/X4 | 8 | O24 |
| N20 | Root/system partition/bootloader control | absent and not granted to regular APK | **not** a Native generic Tool | X5 | 7 | O21–O23 |

Native is **not** privileged merely because it runs on the device.
PackageManager visibility is filtered on Android 11+, MediaProjection
requires user consent for each session, and AccessibilityService has
purpose/permission restrictions; do not design an unattended generic
gesture bot and claim it is a regular app capability. [O15–O18]

## H. Platform-source, kernel/ROM and deep lifecycle coverage

| ID | Family | Actual workstation requirement | Risk | Stage | Official |
| --- | --- | --- | --- | --- | --- |
| R01 | Git + Repo init/status/sync/manifest/branch/review | workstation with explicitly selected source checkout | D0/W3 | 8 | O20 |
| R02 | AOSP `envsetup.sh`, target `lunch`, `m` module/image builds | officially supported 64-bit x86 Linux/glibc worker, ample RAM/disk | W3 | 8 | O25 |
| R03 | Kernel, modules, device tree, boot/vendor partitions and signatures | target-specific sources, binaries and authorized hardware | W3/X4 | 8 | O25 |
| R04 | CTS/VTS/Tradefed suite dispatch and report aggregation | certified target build/test worker and device/emulator | W3 | 8 | Android Test |
| R05 | Image diff, incremental OTA metadata and rollback slot planning | verified image manifests, A/B/device profile | D1/X4 | 7/8 | O21,O25 |
| R06 | Host ROM recovery for broken Native/ADB | fastboot/recovery diagnostic and manual gate | X4 | 7 | O21–O23 |
| R07 | Device/vendor specific flashing, modem, bootloader, OEM commands | device-owner-authorized separate runbook; NOT an arbitrary Tool | X5 | 7/8 | O21 |

AOSP full OS builds have a materially different workstation profile
than APK builds. Google's current official setup specifies a **64-bit x86
Linux/glibc** build workstation, at least **64 GB RAM**, and approximately
**400 GB free disk** for source and build. Existing ARM64 Pi ADB nodes and
macOS ARM64 machines must NOT be treated as supported full-AOSP ROM workers
without a separately proven supported toolchain/environment. [O25]

## I. Distribution, publishing and release rollback (beyond local SDK CLI)

The full **application** lifecycle extends beyond ADB and APK installation:
real tester distribution, staged rollout, release tracking, patching and
halting a release require account-scoped distribution services, not a
locally installed device-control binary. These must be separate opt-in
providers with OAuth/service-account scopes and explicit write confirmation.

| ID | Capability family / authoritative source | Host-side integration | Native role | Risk | Stage |
| --- | --- | --- | --- | --- | --- |
| E01 | Release-readiness checklist, APK/AAB hash/signing and version provenance [O12,O19] | local artifact inspection | report Native app compatibility | D0 | 2/9 |
| E02 | App Distribution testers/groups and pre-release upload [O30] | optional Firebase CLI/API/Gradle provider | tester installs via approved Android flow | W3 | 9 |
| E03 | Google Play app/track/release information read [O29] | separately authenticated Play Developer API | none | D1 | 9 |
| E04 | Play edit creation, upload artifacts and draft release plan [O29] | OAuth-scoped plan with versioned artifact digest | none | W3 | 9 |
| E05 | Commit release edit, staged rollout percentage and track updates [O29] | explicit independent approval, audit and rollback plan | none | W3 | 9 |
| E06 | Release halt/status/monitoring and user-facing rollback limitation [O29] | authorized API, not equivalent to uninstall or user-data rollback | none | W3 | 9 |
| E07 | Store listing screenshots, release notes, localization and assets [O29] | signed approved artifact staging, content review | optional native capture source with user consent | D1/W3 | 9 |
| E08 | Release postmortem, crash/ANR trend and provenance [O29,O30] | opt-in external APIs plus local historical traces | own-app crash evidence | D1 | 9 |

Google Play Publishing API is **not** installed or connected just because
the local SDK exists. Google documents transactional Edits and track
rollouts, and some Play Console first-publish/legal-consent work cannot be
completed by API alone. Do not claim arbitrary server-side rollback of
already installed APKs, live editing of existing policy consents, or
unattended production rollout. [O29]

## Official source register (Google / Android / AOSP; reviewed 2026-10-12)

- **O01**: Android Debug Bridge guide — <https://developer.android.com/tools/adb>
- **O02**: AOSP authoritative ADB man page — <https://android.googlesource.com/platform/packages/modules/adb/+/refs/heads/main/docs/user/adb.1.md>
- **O03**: Android `dumpsys` reference — <https://developer.android.com/tools/dumpsys>
- **O04**: Android SDK command-line tool families — <https://developer.android.com/tools>
- **O05**: SDK manager / evolving Android CLI — <https://developer.android.com/tools/sdkmanager>
- **O06**: AVD manager / evolving Android CLI — <https://developer.android.com/tools/avdmanager>
- **O07**: Emulator command line — <https://developer.android.com/studio/run/emulator-commandline>
- **O08**: Android Gradle CLI builds — <https://developer.android.com/build/building-cmdline>
- **O09**: Emulator snapshots — <https://developer.android.com/studio/run/emulator-snapshots>
- **O10**: Android tests via command line — <https://developer.android.com/studio/test/command-line>
- **O11**: APK analyzer — <https://developer.android.com/tools/apkanalyzer>
- **O12**: Signing/alignment — <https://developer.android.com/tools/apksigner> ; <https://developer.android.com/tools/zipalign>
- **O13**: Perfetto trace collection — <https://developer.android.com/tools/perfetto> ; <https://perfetto.dev/docs/getting-started/system-tracing>
- **O14**: AOSP Simpleperf and platform performance — <https://source.android.com/docs/core/tests/debug/eval_perf>
- **O15**: UI Automator and AccessibilityService — <https://developer.android.com/training/testing/other-components/ui-automator> ; <https://developer.android.com/guide/topics/ui/accessibility/service>
- **O16**: MediaProjection user consent — <https://developer.android.com/media/grow/media-projection>
- **O17**: Android PackageInstaller session API — <https://developer.android.com/reference/android/content/pm/PackageInstaller.SessionParams>
- **O18**: PackageManager application visibility — <https://developer.android.com/reference/android/content/pm/PackageManager>
- **O19**: Android App Bundle and bundletool — <https://developer.android.com/guide/app-bundle/test>
- **O20**: Repo/Git source control — <https://source.android.com/docs/setup/download/source-control-tools> ; <https://source.android.com/docs/setup/download>
- **O21**: Fastbootd, logical partitions and Fastboot commands — <https://source.android.com/docs/core/architecture/bootloader/fastbootd>
- **O22**: AOSP flashing with Fastboot — <https://source.android.com/docs/setup/test/running>
- **O23**: Bootloader lock/unlock and wipe conditions — <https://source.android.com/docs/core/architecture/bootloader/locking_unlocking>
- **O24**: Device Owner / Policy Manager permissions — <https://developer.android.com/reference/android/app/admin/DevicePolicyManager>
- **O25**: AOSP build and workstation requirements — <https://source.android.com/docs/setup/build/building> ; <https://source.android.com/docs/setup/start>

- **O26**: Android NDK/CMake and native debugger tooling — <https://developer.android.com/ndk/guides/build> ; <https://developer.android.com/studio/projects/gradle-external-native-builds> ; <https://developer.android.com/ndk/guides/ndk-stack> ; <https://developer.android.com/studio/debug>
- **O27**: Optional non-SDK tool, scrcpy (upstream only) — <https://github.com/Genymobile/scrcpy>
- **O28**: Android GPU Inspector — <https://developer.android.com/agi>
- **O29**: Google Play Developer Publishing API / Edits — <https://developers.google.com/android-publisher/edits> ; <https://developers.google.com/android-publisher/api-ref/rest/v3/edits.tracks>
- **O30**: Firebase App Distribution — <https://firebase.google.com/docs/app-distribution>

**Provenance constraint:** docs establish available capabilities;
local CLI inspection establishes presence/version only. No commands
above (except `--help`/version/read-only host filesystem checks) were
executed on physical devices for this design review.
