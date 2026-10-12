# Host MCP serial plan: specific test cases for each work package

**Date:** 2026-10-13 (Australia/Sydney).
**Reference:** [45 Host development slices](host-mcp-implementation-plan-20261013.md).
**Status:** test design. These cases are **not claimed implemented or passed**
until the corresponding PR records actual test results and a verified merge SHA.

Every H0.a–H9.c package must implement **six named tests** (270 test cases),
plus existing Host regression and quality checks. Proposed files can be
consolidated into existing test modules, but preserve the case IDs in the
PR and the 95-family capability ledger.

## Required baseline regression on *every* PR

1. **Q-01 MCP shape:** FastMCP in-process Client tools/list and tools/call,
   plus a fake-executable localhost HTTP test for every new public Tool.
   Assert description, input/output schemas, annotations, structuredContent,
   expected domain-denial codes and backward compatibility.
2. **Q-02 device safety:** exact explicit device/transport selection,
   unauthorized/offline/multi-device errors and no fallback to first device.
   Fake runner records argv; denial must result in **zero executions**.
3. **Q-03 input security:** no generic shell, unchecked executable name,
   arbitrary Gradle/Fastboot flags, untrusted paths, symlink traversal,
   environment-variable credential leakage or unsafe root/listener.
4. **Q-04 resource limits:** bounded bytes/CPU/time/disk, controlled
   subprocess group shutdown, cancellation, retries and uncertain results
   where applicable; fixtures must not use real personal data.
5. **Q-05 cross-platform:** Mac OpenJDK17/SDK36/ADB/Fastboot37, Pi
   ADB/Fastboot34 but no full SDK, missing tools and malformed output.
6. **Q-06 merge gate:** exact-head macOS ARM64 and Linux ARM64 four-Python
   matrix (3.11, 3.12, 3.13, 3.14), true per-module statement and branch
   coverage (critical >=95%, other >=90%), Ruff, mypy strict, Bandit,
   clean wheel/sdist and CLI Doctor, precommit/prepush and no-paid-Actions
   policy, exact verified merged main Git tree.

For **new functionality**, add the failing assertion before code (red
phase), then make it pass. For H0.a only, prove golden contract fixtures
are mutation-sensitive by changing an isolated copy, observing the test
fail and restoring it. Import/syntax errors alone are not valid red proof.
Never lower existing test coverage or redefine the test to fit bad code.

The six tests under each Hx.y below are concrete targeted tests, **not
substitutes** for Q-01–Q-06.

## H0: baseline, installed CLI and capability profiles

### H0.a — host/tests/test_host_baseline_golden.py

- **T-H0A-01:** in-process catalog is exactly the three legacy Tool names,
  unchanged title/description/hints and v1 output schema IDs.
- **T-H0A-02:** valid fake ADB status, observer and developer read results
  validate canonical structuredContent Schemas.
- **T-H0A-03:** invalid serial, unknown/duplicate probe, unknown action
  give existing typed domain denial and zero fake ADB calls.
- **T-H0A-04:** default physical mutation is disabled; instrument preview
  is marked a plan and causes no fake device execution.
- **T-H0A-05:** timeout, unauthorized/offline target and 64 KiB flooded
  ADB output return bounded error/partial responses, no orphan process.
- **T-H0A-06:** intentionally mutated temporary expected schema or denial
  assertion fails; restored expected golden passes (test sensitivity).

### H0.b — host/tests/test_toolchain_inventory.py

- **T-H0B-01:** synthetic Mac fixed Java17/SDK36/Gradle9.6/ADB and
  Fastboot37 outputs produce accurate version and runnable state.
- **T-H0B-02:** synthetic Pi ADB/Fastboot34 with no Java/SDK gives
  partial availability without pretending SDK tools exist.
- **T-H0B-03:** missing, non-executable, permission-denied and malformed
  CLI version results retain distinct reason codes.
- **T-H0B-04:** fake executable on a hostile earlier PATH cannot shadow
  an authorized fixed binary or insert shell flags.
- **T-H0B-05:** hung version/help probe, nonzero exit and oversized output
  produce bounded timeout/output limit and cleaned process group.
- **T-H0B-06:** inventory MCP tool has typed Schema, truthful safety
  annotations, no SDK install/update, and old three Tools unchanged.

### H0.c — host/tests/test_capability_profiles.py

- **T-H0C-01:** default profile exposes only non-privileged capabilities
  and never enables executable physical mutation.
- **T-H0C-02:** missing SDK, Fastboot or provider account is honestly
  unavailable/not_installed, never authorized by presence alone.
- **T-H0C-03:** duplicate, unknown and conflicting profile identifiers
  fail closed; no unrestricted developer profile selected.
- **T-H0C-04:** verified transport creates a typed temporary target
  reference; stale/changed/disconnected transports invalidate it.
- **T-H0C-05:** coverage ledger contains all 95 Host family IDs once;
  missing, duplicate and disabled-to-runnable unapproved changes fail.
- **T-H0C-06:** real FastMCP catalog respects allowed profile and
  denied operations; legacy Tool results remain unchanged.

## H1: ADB and Fastboot read-only diagnostics

### H1.a — host/tests/test_adb_devices_list_tool.py

- **T-H1A-01:** two synthetic distinct ADB targets preserve serial,
  transport ID and exact connection states.
- **T-H1A-02:** empty discovery returns an empty list rather than a
  cached/default first device.
- **T-H1A-03:** offline, unauthorized, recovery and malformed device rows
  are not misclassified as authorized online.
- **T-H1A-04:** duplicate transport IDs or ambiguous target identifiers
  fail closed with a typed ambiguity error.
- **T-H1A-05:** daemon failure, no adb binary, bad stderr and timeout
  return bounded partial/unavailable and terminate child process.
- **T-H1A-06:** MCP tools/list and localhost HTTP schema reflect the
  actual read scope, with no pairing/connection write.

### H1.b — host/tests/test_adb_transport_inspect.py

- **T-H1B-01:** selected device moves offline-to-device in bounded fake
  wait, returning the exact target and observed state.
- **T-H1B-02:** wrong, stale, unauthorized or unknown serial is rejected;
  no fallback, pairing or automatic ADB reconnect.
- **T-H1B-03:** negative/excessive wait, unsupported state or malformed
  mDNS endpoint gets typed validation denial.
- **T-H1B-04:** fake forward/reverse list is parsed as inert data; no
  port forward/reverse creation or exposure.
- **T-H1B-05:** disconnect, timeout and cancellation clean up the wait
  process and leave explicit timeout/unknown outcome.
- **T-H1B-06:** Tool schema promises inspection only; no hidden
  mutation, transport change, or raw address reflection.

### H1.c — host/tests/test_adb_system_probe_expansion.py

- **T-H1C-01:** allowlisted fake identity/battery/storage/display/
  network/dumpsys probes return typed units and v1 compatible shape.
- **T-H1C-02:** unknown service/probe, duplicates and probe count
  exceeding limit rejected before any process.
- **T-H1C-03:** invalid UTF-8, impossible numeric values and missing
  fields produce partial/error rather than invented normal data.
- **T-H1C-04:** ambiguous/offline serial cannot produce unscoped
  adb shell argv; fixed command always includes exact serial.
- **T-H1C-05:** flooded output, timeout and partial dumpsys terminate
  cleanly within resource budget.
- **T-H1C-06:** existing nine probe names, typed errors and current
  output Schema remain compatible in FastMCP and HTTP.

### H1.d — host/tests/test_adb_package_diagnostics.py

- **T-H1D-01:** exact valid package returns bounded targeted metadata,
  version and permission summaries from fake dumpsys.
- **T-H1D-02:** absent package or unresolvable visibility returns not
  found/unavailable, never substitutes a similarly named package.
- **T-H1D-03:** metacharacters, Unicode confusables, length and invalid
  package components cannot reach an ADB shell.
- **T-H1D-04:** huge package list, credentials and control sequences
  are bounded/sanitized without raw sensitive log persistence.
- **T-H1D-05:** offline device, permission denial, unexpected exit and
  timeout return typed errors and no orphan processes.
- **T-H1D-06:** legacy package_details remains v1 compatible; new
  Tool does not advertise install/uninstall capability.

### H1.e — host/tests/test_adb_logcat_filters.py

- **T-H1E-01:** bounded lines plus approved exact tag/package/severity
  filters compile to fixed argv and redacted structured result.
- **T-H1E-02:** over-limit lines, invalid time, unknown filter and
  command injection get typed invalid-arguments error.
- **T-H1E-03:** synthetic bearer tokens/passwords/identifiers/ANSI
  codes receive documented redaction and never appear in normal logs.
- **T-H1E-04:** ambiguous/offline serial cannot read a connected
  different device or unrelated filesystem path.
- **T-H1E-05:** hung, partially returned and >limit Logcat captures
  are interrupted and expose timeout/partial semantics.
- **T-H1E-06:** legacy logcat_snapshot defaults/denials remain stable;
  new Tool warns that output may contain sensitive data.

### H1.f — host/tests/test_fastboot_inventory.py

- **T-H1F-01:** Mac37 and Debian34 fake Fastboot devices -l outputs
  parse independent bootloader identities and versions.
- **T-H1F-02:** missing binary or no bootloader device returns
  available-empty/unavailable, never maps booted ADB devices.
- **T-H1F-03:** repeated/malformed serial, bad mode and ADB/Fastboot
  mismatch produce ambiguity, not guessed identity.
- **T-H1F-04:** fake runner accepts only version/devices-list argv;
  never invokes getvar, flash, erase, unlock, reboot or oem.
- **T-H1F-05:** CLI timeout, oversized output and malformed rows
  produce bounded errors with clean process cancellation.
- **T-H1F-06:** published discover Tool is truthful/read-only at
  device layer; FastMCP/HTTP contract is versioned and bounded.

## H2: SDK/build and artifact/job infrastructure

### H2.a — host/tests/test_sdk_ndk_inventory.py

- **T-H2A-01:** fake complete JDK17, SDK36, build-tools, emulator,
  Gradle and NDK/CMake report accurate independent capability states.
- **T-H2A-02:** Pi missing SDK and JDK, missing NDK or partial
  SDK files do not claim a build-ready workstation.
- **T-H2A-03:** hostile JAVA_HOME, symlinked SDK outside safe root,
  PATH spoofing and wrong-version binaries fail closed.
- **T-H2A-04:** installed but broken Homebrew apkanalyzer is marked
  installed_unusable; valid SDK-local binary is distinguished.
- **T-H2A-05:** CLI timeout, nonzero error, malformed output and
  overflow yield bounded typed reasons without SDK modifications.
- **T-H2A-06:** Tool advertises per-host availability and no
  install/license-acceptance operation.

### H2.b — host/tests/test_android_build_preflight.py

- **T-H2B-01:** approved pinned Gradle wrapper/project and safe build
  variant yield a read-only plan with exact root/revision.
- **T-H2B-02:** missing wrapper or incompatible AGP/JDK/SDK yields
  typed build-unavailable before executing tasks.
- **T-H2B-03:** path traversal, symlink escape and arbitrary Gradle
  task/argument injection are rejected.
- **T-H2B-04:** dirty/uncommitted project is reported truthfully,
  without git stash/reset/clean or unrequested checkout mutation.
- **T-H2B-05:** Gradle metadata discovery hangs, floods output or
  exits nonzero; no orphan daemon and no false positive plan.
- **T-H2B-06:** output plan contains allowed actions, toolchain
  versions, SHA and input validation with no build execution.

### H2.c — host/tests/test_host_artifact_store.py

- **T-H2C-01:** small generated fixture stores privately and returns
  opaque handle, accurate MIME/size/SHA-256.
- **T-H2C-02:** unknown, expired, cross-owner or revoked handle
  is rejected without revealing other artifact paths.
- **T-H2C-03:** symlink/traversal/untrusted filename, oversized
  bytes and wrong MIME cannot escape the private store.
- **T-H2C-04:** duplicate/concurrent content creates consistent
  atomic records; crash during write leaves no trusted partial file.
- **T-H2C-05:** restart, TTL expiry, delete and bounded disk cleanup
  maintain proper access/retention semantics.
- **T-H2C-06:** public metadata returns handle/hash rather than raw
  large bytes or private absolute path; logs omit sensitive payloads.

### H2.d — host/tests/test_host_durable_jobs.py

- **T-H2D-01:** prepared/queued/running/succeeded/failed job
  transitions persist stable job ID, owner, timestamps, result digest.
- **T-H2D-02:** duplicate request ID plus identical plan digest
  is idempotent; different digest with reused ID rejected.
- **T-H2D-03:** invalid transition, stale identity, wrong owner
  or absent authorization is transactionally denied.
- **T-H2D-04:** two fake workers/processes racing for one job
  result in exactly one owner and deterministic audit ordering.
- **T-H2D-05:** cancel, timeout, worker crash/restart and
  uncertain result reconcile without duplicate unsafe execution.
- **T-H2D-06:** public status/poll schema distinguishes queued,
  running, succeeded, failed, cancelled and uncertain without secrets.

### H2.e — host/tests/test_apk_aab_inspection.py

- **T-H2E-01:** synthetic APK/AAB returns package/version,
  permissions/ABI, signature verification, hash and artifact reference.
- **T-H2E-02:** unsigned/corrupt/fake-signature archive cannot
  produce an incorrectly verified package.
- **T-H2E-03:** ZIP-slip, symlink, zip bomb, oversized archive
  and resource path traversal are rejected before extraction.
- **T-H2E-04:** missing/incorrect build tools yield unavailable,
  not a model-supplied alternative executable.
- **T-H2E-05:** CLI timeout, malformed metadata and huge manifest
  produce bounded error/partial, with cleanup.
- **T-H2E-06:** real FastMCP/HTTP result reveals no signing key,
  password, raw archive or arbitrary local path.

### H2.f — host/tests/test_host_gradle_build_job.py

- **T-H2F-01:** approved project + supported variant starts exactly
  one fake Gradle job and yields bounded report/artifact handles.
- **T-H2F-02:** unknown project/variant/free-form task flags and
  tampered wrapper prevent any subprocess launch.
- **T-H2F-03:** build log containing synthetic credentials,
  ANSI codes and huge output is sanitized, bounded and not stored raw.
- **T-H2F-04:** absent SDK/JDK, nonzero Gradle exit, invalid APK
  output or Gradle daemon failure yields truthful job failure.
- **T-H2F-05:** double-submit, timeout, cancel, process tree
  cleanup and job-restart recovery follow H2.d semantics.
- **T-H2F-06:** MCP request/result and real HTTP fake Gradle test
  preserve no-device-build-only contract and v1 Host Tools.

## H3: disposable AVD and reproducible tests

### H3.a — host/tests/test_avd_inventory.py

- **T-H3A-01:** fake AVD list reports verified name, API, ABI,
  snapshot metadata and run state using fixed installed SDK binary.
- **T-H3A-02:** SDK or emulator unavailable returns truthful state,
  not ADB physical target or a guessed AVD name.
- **T-H3A-03:** malformed JSON/text, duplicate AVD names,
  invalid API/ABI and impossible snapshot version are rejected.
- **T-H3A-04:** hostile AVD name cannot become a shell option or
  escape configured AVD store; read-only calls never create an AVD.
- **T-H3A-05:** stale running PID, CLI hang and oversized metadata
  are bounded and do not kill an unrelated emulator.
- **T-H3A-06:** MCP tool availability matches verified emulator
  support and does not expose physical device control.

### H3.b — host/tests/test_avd_provisioning.py

- **T-H3B-01:** uniquely named MCP-owned disposable AVD can be
  provisioned from a pinned already installed synthetic image.
- **T-H3B-02:** user-owned/pre-existing AVD cannot be modified,
  deleted, renamed or replaced.
- **T-H3B-03:** malicious AVD name, symlinked store, injected
  image path and unsupported API/ABI fail before provisioning.
- **T-H3B-04:** SDK image missing or license not accepted gives
  unavailable without auto-downloading or accepting terms.
- **T-H3B-05:** interrupted/duplicate create, disk allocation
  failure and teardown leave no orphaned AVD directory.
- **T-H3B-06:** request/result schema includes owner, target
  and artifact identity, without physical-device access.

### H3.c — host/tests/test_emulator_lifecycle_jobs.py

- **T-H3C-01:** verified MCP-owned AVD starts fake emulator child,
  reaches expected boot/health and records durable job handle.
- **T-H3C-02:** target not recognized as QEMU/disposable never
  falls back to a physical USB tablet.
- **T-H3C-03:** conflicting AVD name, duplicate start and hostile
  flags fail without spawning a second emulator.
- **T-H3C-04:** readiness rejects mismatched serial/API,
  boot-incomplete state and unowned PID.
- **T-H3C-05:** timeout, forced shutdown, crash, cancellation
  and restart reconcile without orphan processes/stale lease.
- **T-H3C-06:** tool status/poll remains durable and correctly
  declares emulator state changes, not a read-only operation.

### H3.d — host/tests/test_emulator_snapshot_manager.py

- **T-H3D-01:** named disposable snapshot creates/lists/restores
  with verified source image fingerprint.
- **T-H3D-02:** other user's AVD and pre-existing snapshot
  cannot be overwritten/rolled back/deleted.
- **T-H3D-03:** invalid name, symlink, path traversal,
  cross-AVD source and unsupported emulator version fail closed.
- **T-H3D-04:** snapshot incompatible with API/ABI/system image
  is rejected, not automatically migrated.
- **T-H3D-05:** partial write, disk full, timeout and cancel
  preserve previous safe snapshot and honest job state.
- **T-H3D-06:** MCP result identifies exact possible emulator
  state change and never affects physical Android.

### H3.e — host/tests/test_emulator_instrumentation_jobs.py

- **T-H3E-01:** valid test APK and runner on exact booted
  disposable AVD generate fixed argv and structured test report.
- **T-H3E-02:** fake physical serial/other AVD rejected before
  APK install or instrumentation.
- **T-H3E-03:** invalid class/component, extra adb shell flags,
  wrong APK digest and unsupported API denied.
- **T-H3E-04:** failed instrumentation test is reported as
  failed with IDs, not a successful job.
- **T-H3E-05:** timeout, emulator restart, duplicate request
  and cancel reconcile without unsafe retry.
- **T-H3E-06:** MCP artifact/job status includes provenance,
  exact target and test result without raw private data.

### H3.f — host/tests/test_emulator_debug_deployment.py

- **T-H3F-01:** approved debug APK installs to one verified
  disposable AVD via fixed argv and verified receipt.
- **T-H3F-02:** physical serial and unverified emulator-looking
  serial rejected despite appearing in ADB list.
- **T-H3F-03:** unsigned/wrong package/ABI, symlinked APK,
  missing checksum and unsupported flags fail before subprocess.
- **T-H3F-04:** uninstall/launch/cleanup only touches
  test-owned package and AVD, never arbitrary app.
- **T-H3F-05:** install timeout/transport loss/duplicate request
  produces unknown state with no blind retry.
- **T-H3F-06:** physical install remains default denied;
  disposable AVD profile is explicit in published Tool contract.

## H4: media, user interface and limited file exchange

### H4.a — host/tests/test_adb_screenshot_artifacts.py

- **T-H4A-01:** fake valid PNG screenshot from exact allowed
  target returns private SHA-256 artifact handle.
- **T-H4A-02:** unknown/unauthorized target and missing
  sensitive-capture consent return denial.
- **T-H4A-03:** corrupted/non-PNG, zero bytes, huge frame,
  control characters and response spoofing rejected.
- **T-H4A-04:** secure-screen protection is not bypassed;
  raw screenshots never enter normal JSON/logs.
- **T-H4A-05:** timeout, disconnect, duplicate capture and
  TTL deletion obey artifact budget and clean processes.
- **T-H4A-06:** MCP result contains opaque handle/provenance,
  truthful privacy hints and no unbounded media.

### H4.b — host/tests/test_adb_ui_hierarchy.py

- **T-H4B-01:** valid fake hierarchy parses bounded nodes,
  focus/window IDs and parent relationships.
- **T-H4B-02:** unauthorized target, absent UI capability,
  locked or sensitive window produces redacted/unavailable.
- **T-H4B-03:** XML entity expansion, deep tree, malformed
  Unicode and duplicate node IDs rejected.
- **T-H4B-04:** synthetic password/notification/token
  text redacted according to exact sensitivity policy.
- **T-H4B-05:** hung uiautomator, partial dump and mode
  change produce bounded failure and clean subprocess.
- **T-H4B-06:** no click/tap/input command issued by
  inspection Tool, with matching FastMCP and HTTP schemas.

### H4.c — host/tests/test_adb_screenrecord_job.py

- **T-H4C-01:** consented disposable AVD capture produces
  bounded fake video and durable job/artifact handles.
- **T-H4C-02:** physical target without valid capture grant
  returns denial/plan-only with no recording process.
- **T-H4C-03:** invalid duration/display/codec/size,
  hostile output path and injected flags rejected.
- **T-H4C-04:** video stored privately with TTL, MIME
  and hash, never embedded raw in Tool result.
- **T-H4C-05:** cancel, timeout, subprocess failure and
  device disconnect leave no orphan recording.
- **T-H4C-06:** tools/list honestly labels sensitive
  capture and job lifecycle, not covert background read.

### H4.d — host/tests/test_adb_file_pull_policy.py

- **T-H4D-01:** allowed synthetic app-owned file pulled
  with exact private artifact hash and byte length.
- **T-H4D-02:** /data credentials, arbitrary system
  paths and unknown device denied before adb pull.
- **T-H4D-03:** traversal dot-dot, symbolic links,
  nul/control bytes and normalization tricks cannot bypass roots.
- **T-H4D-04:** remote response cannot choose arbitrary
  Host destination, overwrite user data or inject argv.
- **T-H4D-05:** large/interrupted transfer, disconnect
  and checksum mismatch leave no trusted partial artifact.
- **T-H4D-06:** Tool exposes private handle only,
  not local Host path or raw file contents.

### H4.e — host/tests/test_adb_file_push_policy.py

- **T-H4E-01:** signed synthetic artifact imported to
  verified disposable AVD allowed dir with receipt.
- **T-H4E-02:** physical target without grant remains
  MUTATION_DISABLED, with zero adb push calls.
- **T-H4E-03:** remote traversal, symlink, /system,
  external directories and arbitrary flags rejected.
- **T-H4E-04:** wrong artifact owner/digest/type,
  excessive size fails before any transfer.
- **T-H4E-05:** duplicate request, cancel, timeout
  and partial push reconcile without overwriting unrelated files.
- **T-H4E-06:** Tool is not read-only; dry run provides
  bounded side-effect plan and typed denials.

### H4.f — host/tests/test_adb_emulator_ui_actions.py

- **T-H4F-01:** typed tap/swipe/key on exact preverified
  disposable AVD compiles to allowlisted argv only.
- **T-H4F-02:** physical tablet, unknown serial or
  missing grant returns plan-only/denied.
- **T-H4F-03:** invalid coordinates, negative duration,
  arbitrary keycode/text and shell injection rejected.
- **T-H4F-04:** stale screen/window generation,
  rotation change and focus shift deny wrong-target gesture.
- **T-H4F-05:** duplicate action, cancel and unknown
  tap result never trigger blind replay.
- **T-H4F-06:** per-action ID/audit, write-side annotation
  and no generic adb shell surface asserted through MCP.

## H5: bugreport, tracing and diagnostics

### H5.a — host/tests/test_adb_bugreport_artifacts.py

- **T-H5A-01:** fixed synthetic bugreport collected under
  bounded size/time with opaque private artifact and SHA-256.
- **T-H5A-02:** offline/unauthorized or ambiguous device cannot
  produce any cross-device bugreport.
- **T-H5A-03:** malicious ZIP entries, missing bugreportz markers,
  invalid encoding and excessive nested files rejected.
- **T-H5A-04:** synthetic private account data/tokens/log IDs
  redacted before storing any derivative or normal log.
- **T-H5A-05:** timeout, disk full, cancel and disconnect
  delete partial artifacts and reconcile uncertain status.
- **T-H5A-06:** output never embeds raw bugreport,
  password or unrestricted Host path; artifact retention stated.

### H5.b — host/tests/test_adb_logcat_stream_jobs.py

- **T-H5B-01:** synthetic finite stream returns stable cursor,
  monotonic chunk positions, stop handle and bounded event count.
- **T-H5B-02:** wrong target, duplicate cursor and expired lease
  rejected without continuing another user's stream.
- **T-H5B-03:** malformed cursor, unknown tag and hostile
  raw Logcat fields denied/redacted.
- **T-H5B-04:** slow client backpressure and huge stream cap
  memory and disk, dropping/truncating explicitly.
- **T-H5B-05:** worker crash/restart, cancellation, deadline
  and device disconnect terminate child and mark uncertain/ended.
- **T-H5B-06:** HTTP/MCP poll/stop respects durable
  operation ID, sensitive-content hints and bounded JSON envelope.

### H5.c — host/tests/test_perfetto_trace_job.py

- **T-H5C-01:** approved synthetic emulator capture with
  fixed traced profile records bytes/time limits and artifact handle.
- **T-H5C-02:** no tracing support, missing debuggability
  or physical unapproved target returns unavailable/denied.
- **T-H5C-03:** arbitrary Perfetto config file, trace
  destinations and shell extras rejected before subprocess.
- **T-H5C-04:** synthetic traces with host names/secret
  markers are not printed in ordinary Tool JSON or logs.
- **T-H5C-05:** trace timeout, cancel, process restart
  and device disconnect stop capture and clean partial files.
- **T-H5C-06:** resulting artifact records exact profile,
  target, version, digest and status/uncertain semantics.

### H5.d — host/tests/test_simpleperf_profile_job.py

- **T-H5D-01:** supported ABI/debuggable app/authorized
  test target results in safe fixed Simpleperf argv and report.
- **T-H5D-02:** missing Simpleperf/unsupported ROM/ABI
  returns accurate unavailable rather than fake performance data.
- **T-H5D-03:** privileged kernel-event selectors,
  arbitrary PID, unknown app and command-injection flags rejected.
- **T-H5D-04:** race where process dies/reuses PID
  cannot profile a different app without revalidation.
- **T-H5D-05:** timeout, cancellation, oversized
  profile, insufficient storage and restart clean up properly.
- **T-H5D-06:** output reports bounded metrics and
  opaque profile artifacts with truthful environment provenance.

### H5.e — host/tests/test_native_symbolization_reports.py

- **T-H5E-01:** approved local crash trace plus exact matching
  Build ID/native symbols returns bounded reproducible frames.
- **T-H5E-02:** wrong build fingerprint/ABI, absent
  mapping file or incomplete symbols returns partial/unavailable.
- **T-H5E-03:** symbol file traversal, archive bombs
  and arbitrary native tool flags rejected.
- **T-H5E-04:** synthetic addresses/secrets in trace
  are redacted from report and server logs as specified.
- **T-H5E-05:** analyzer timeout/flood, repeated job,
  canceled parse and bad UTF-8 cannot create a successful report.
- **T-H5E-06:** result includes input hashes, exact
  tool version, per-frame status and bounded artifact handle.

## H6: inert Host/Native coordination and no-approval privilege planning

### H6.a — host/tests/security/test_native_pairing_inert.py

- **T-H6A-01:** fake Native install public identity and challenge
  produce versioned pairing plan with no live socket handshake.
- **T-H6A-02:** no Native endpoint/credentials/caller authentication
  remains unpaired and cannot enable sensitive Tool visibility.
- **T-H6A-03:** invented pairing ID, replayed nonce, reused
  boot epoch and mismatched identity are rejected.
- **T-H6A-04:** fake signature mismatch/expiry/clock rollback
  never become an approved caller.
- **T-H6A-05:** disconnect/restart and duplicate
  messages leave high-water protection and honest unpaired state.
- **T-H6A-06:** no Native worktree modifications, network
  listener, signed private key disclosure or physical write.

### H6.b — host/tests/security/test_fencing_state_machine_inert.py

- **T-H6B-01:** fake Host/Native lease state progresses
  acquire/held/release with exact device ID and plan digest.
- **T-H6B-02:** absent Native ACK or no authenticated pairing
  denies every mutation with an explicit reason.
- **T-H6B-03:** duplicate operation, stale fencing counter,
  conflicting Host ID and wrong boot epoch rejected.
- **T-H6B-04:** two concurrent Host actors cannot both
  hold a valid exclusive write lease in deterministic race tests.
- **T-H6B-05:** crash/restart/expiry and lost release
  reconcile as uncertain, not automatically grant new write.
- **T-H6B-06:** default production Host composition keeps
  this coordinator disabled and cannot execute device mutation.

### H6.c — host/tests/security/test_device_deployment_plan_denials.py

- **T-H6C-01:** hashed approved synthetic APK plus exact
  device target produces a typed install *plan* and risk summary.
- **T-H6C-02:** any default real-device install, uninstall,
  permission write or force-stop execution returns MUTATION_DISABLED.
- **T-H6C-03:** wrong/unsigned APK, path escape,
  conflicting package, arbitrary flags and wrong target are denied.
- **T-H6C-04:** fake model argument claiming
  approved=true or owner=true cannot replace server-signed grant.
- **T-H6C-05:** duplicate plan/replay, missing Native
  fence, uncertain last mutation and disconnected device fail closed.
- **T-H6C-06:** MCP catalog exposes read/plan only
  by default; no active physical deployment backend is registered.

### H6.d — host/tests/security/test_adb_connection_plan_denials.py

- **T-H6D-01:** selected transport with known mDNS
  service yields bounded Wi-Fi pairing/forwarding *plan*.
- **T-H6D-02:** no trusted grant gives denial without
  adb tcpip, pair, forward or reverse command execution.
- **T-H6D-03:** arbitrary public endpoint, DNS rebinding,
  local bind 0.0.0.0, port overflow and foreign device ID rejected.
- **T-H6D-04:** credentials, QR/pairing codes and
  private keys are never echoed in normal output/logs.
- **T-H6D-05:** duplicate request, expired challenge,
  uncertain reconnect and timeout do not auto-pair.
- **T-H6D-06:** profile/Tool describes its
  network effects and default plan-only behavior truthfully.

## H7: Fastboot read-only preflight and recovery plans

### H7.a — host/tests/test_fastboot_safe_variables.py

- **T-H7A-01:** fake Fastboot34/37 selected exact bootloader
  target yields allowlisted product, slot, version and lock state.
- **T-H7A-02:** missing bootloader device or disconnected/ambiguous
  target returns unavailable without triggering ADB reboot.
- **T-H7A-03:** arbitrary getvar key, unsupported OEM
  variable, malformed value and hostile output rejected.
- **T-H7A-04:** discovered serial differing from selected
  target is never silently considered the same physical device.
- **T-H7A-05:** timeout, nonzero CLI exit, huge output
  and repeated getvar call bounded with clean child process.
- **T-H7A-06:** fake CLI records only safe read-only
  allowlisted getvar calls, never flash, lock, unlock or reboot.

### H7.b — host/tests/test_recovery_image_preflight.py

- **T-H7B-01:** approved local signed image fixture yields
  hash, size, target codename, partition, slot and rollback plan.
- **T-H7B-02:** mismatched model, bootloader lock state,
  incompatible slot or unsupported image gives a denial.
- **T-H7B-03:** symlink/outside-root image, invalid
  digest, zip traversal and oversized archive rejected.
- **T-H7B-04:** unsafe wipe/unlock/critical partition
  operation cannot be laundered as an ordinary file check.
- **T-H7B-05:** incomplete image, cancelled checksum,
  disk read failure or modified file during hash returns unknown/invalid.
- **T-H7B-06:** all results explicitly marked preflight,
  no Fastboot write subprocess even with apparently valid image.

### H7.c — host/tests/test_recovery_manual_plan.py

- **T-H7C-01:** exact synthetic target, validated
  bootloader state and image manifest produce a human-readable plan.
- **T-H7C-02:** no verified image/device, unknown
  bootloader state or absent consent means plan cannot be executable.
- **T-H7C-03:** wipe/erase/flashall/oem/unlock strings
  in user text cannot become public executable Fastboot argv.
- **T-H7C-04:** plan names irreversible effects,
  brick/data-loss consequences, artifact digests and recovery alternatives.
- **T-H7C-05:** expired plan, changed slot, reboot
  epoch or device identity makes previous plan stale/denied.
- **T-H7C-06:** no new callable flashing,
  unlock, wipe or reboot Tool registered in default Host catalog.

## H8: AOSP worker selection and simulated platform-build jobs

### H8.a — host/tests/test_aosp_worker_eligibility.py

- **T-H8A-01:** synthetic 64-bit x86 Linux/glibc
  machine with required JDK, disk/RAM and tools reports eligible.
- **T-H8A-02:** Pi ARM64, Mac ARM64 or missing
  build requirements returns explicit unsupported/unavailable.
- **T-H8A-03:** spoofed architecture, fake free-space
  numbers, poisoned JAVA_HOME or missing repo executable denied.
- **T-H8A-04:** output distinguishes remote builder
  readiness from local Host capability and from authorization.
- **T-H8A-05:** transient system inspection failure
  and tool timeout return typed unavailable without modifying host.
- **T-H8A-06:** no AOSP build job starts merely
  because a synthetic worker appears eligible.

### H8.b — host/tests/test_aosp_repo_preflight.py

- **T-H8B-01:** approved synthetic checkout with
  manifest, target codename and pinned revision yields safe build plan.
- **T-H8B-02:** missing repo/source, unsupported
  target or unapproved workspace returns unavailable.
- **T-H8B-03:** arbitrary repo init/sync URL,
  path traversal, branch injection and shell metacharacters denied.
- **T-H8B-04:** dirty source, unknown vendor blob
  provenance or unreviewed manifest is marked not reproducible.
- **T-H8B-05:** manifest read timeout, huge repo
  output and inconsistent revisions leave no trusted build plan.
- **T-H8B-06:** plan has exact input digests
  and never automatically downloads bulk source or invokes repo sync.

### H8.c — host/tests/test_aosp_build_adapter.py

- **T-H8C-01:** fake eligible Linux worker executes
  a bounded simulated AOSP job and stores structured image/test result.
- **T-H8C-02:** no eligible worker,
  missing trusted project or unapproved target returns unavailable.
- **T-H8C-03:** arbitrary Soong target, unbounded
  make jobs, free-form shell flags and artifact destinations rejected.
- **T-H8C-04:** signed/hashed fake ROM outputs
  remain separate from physical flash permission; no install occurs.
- **T-H8C-05:** build worker crash, timeout,
  cancellation, double submission and restart reconciliation use H2.d.
- **T-H8C-06:** MCP result truthfully
  reports simulated/inert vs real worker execution with exact artifacts.

## H9: local release readiness and disabled remote distribution

### H9.a — host/tests/test_release_artifact_readiness.py

- **T-H9A-01:** valid signed APK/AAB fixture
  yields local readiness report with package, version and digest.
- **T-H9A-02:** invalid signature, missing symbol
  map, wrong version/variant or missing manifest is not ready.
- **T-H9A-03:** malicious release notes,
  zip traversal, oversized artwork and filename injection denied.
- **T-H9A-04:** report never exposes
  private signing keys, keystore password or publishing credentials.
- **T-H9A-05:** changed artifact after verification
  invalidates prior readiness proof; no stale approval.
- **T-H9A-06:** local read-only Tool
  cannot create a Play edit, upload an AAB or publish a release.

### H9.b — host/tests/test_release_provider_capabilities.py

- **T-H9B-01:** fake authorized provider
  returns exact account/app scope and allowed read-only track names.
- **T-H9B-02:** no connected account/expired token
  returns unavailable, not an invented Play/Firebase account.
- **T-H9B-03:** app ownership mismatch,
  unauthorized track and untrusted external endpoint denied.
- **T-H9B-04:** synthetic OAuth credentials and
  error response bodies never appear in output or audit logs.
- **T-H9B-05:** rate-limit, service outage,
  timeout and paginated response truncation return partial/unavailable.
- **T-H9B-06:** read-only tools/list profile
  cannot accidentally register upload, rollout or revoke endpoints.

### H9.c — host/tests/test_release_plan_default_denial.py

- **T-H9C-01:** valid synthetic signed artifact
  and local release policy yield a bounded staged rollout plan.
- **T-H9C-02:** attempt to upload/commit,
  change percent or halt a real release without grant is denied.
- **T-H9C-03:** hostile rollout percentage,
  wrong package/track, duplicated release ID and unsigned artifact denied.
- **T-H9C-04:** model-provided approved=true,
  fake owner token or inferred account identity cannot grant publishing.
- **T-H9C-05:** duplicate commit request,
  uncertain provider response, token expiry and cancellation never
  trigger a blind production replay.
- **T-H9C-06:** all external writes are
  plan-only by default; public contract honestly declares account dependency.

## Test record template — one copy per package

Every package's PR includes the following fields, backed by actual
commands rather than promises:

| Evidence field | Exact required value |
| --- | --- |
| Package / catalog scope | e.g., H1.f; F01–F04; intended Tool and read-only profile |
| RED test(s) | Named T-Hxx-yy selection and actual pre-implementation failure |
| GREEN test(s) | All six cases T-Hxx-01 through -06 passed, with pytest summary |
| Negative behavior | Exact denied caller/device input; recorded fake subprocess argv proving no unsafe execution |
| Mac full matrix | Python 3.11, 3.12, 3.13, 3.14: command, exit, report/log path |
| Linux full matrix | Same versions on sextant; exact branch commit SHA; report/log path |
| Quality | Module statement and true branch coverage, Ruff, mypy, Bandit, clean wheel/sdist, secret hooks |
| MCP wire | In-process Client and loopback HTTP on fake backends, Tool catalog, structuredContent and output Schema |
| Risk / execution mode | runnable, implemented_disabled, plan_only, unavailable or excluded |
| Review | Actual self-review notes; separate independent review if privileged enabling |
| Git merge receipt | GitHub PR, exact tested head SHA, merged main SHA and Git tree, post-merge smoke |
| Next work package | New branch from the freshly merged main, or precisely labelled blocker |

**Do not implement a release or privileged executor merely to make these
tests green.** Expected disabled/plan-only outcomes are positive safety tests
and should leave the real Android device, connected accounts and Native
worktree unchanged.
