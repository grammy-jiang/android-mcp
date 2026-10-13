# Host H2.f — finite, pinned offline Gradle jobs (opt-in only)

## Scope and trust model

H2.f provides an optional Host MCP Tool: host_gradle_build(action,
request_id). It runs only a local operator-approved source checkout using
one of three fixed Android Gradle tasks: assemble_debug, lint_debug,
or test_jvm, all on the debug variant. There is **no default execution**
or Android-device selection. No adb install, package uninstall, device
reboot, UI action, Fastboot, root, signing or release publishing operation
is added. The original three Host MCP Tools remain unchanged by default.

Action is a closed typed enum. The idempotent request_id is a bounded
key, not a path, command string, task list, argument, shell script or
device target. Trusted Host composition, not an MCP caller, pins the
working tree, exact Git commit SHA, Gradle wrapper JAR SHA-256, job
ledger root, owner scope and private artifact store scope.

The Host operator must explicitly start a localhost-only server
with all prerequisites. Sketch of the required configuration:

    android-mcp-host serve \
      --build-preflight \
      --build-root /operator/approved/android-mcp \
      --build-approved-revision FULL_GIT_COMMIT_SHA \
      --build-wrapper-sha256 FULL_APPROVED_WRAPPER_SHA256 \
      --artifact-metadata \
      --artifact-root /operator/private/artifacts \
      --artifact-owner operator-artifacts \
      --durable-job-status \
      --job-root /operator/private/jobs \
      --job-owner operator-jobs \
      --controlled-build

Only source roots and private stores selected by the local Host operator
are accepted. Invalid combinations fail during CLI parsing; the same
arguments are never accepted from MCP tool calls. Starting the server
without the controlled-build flag never exposes an execution Tool.

## Admission and bounded execution

Each request rechecks AndroidBuildPreflight.plan, which must report a
clean worktree at exactly the operator-pinned Git revision, a genuine
Gradle wrapper JAR at the pinned SHA-256, compatible fixed SDK/JDK/Gradle
toolchain and fixed task list. The controller independently verifies
root, symlinks, wrapper bytes, launcher executable and task selection.
An unresolved or stale preflight **never executes** a build.

Accepted commands use a positional argument vector, not a user shell,
with fixed offline and no-daemon flags and known tasks. A safe local
working directory points only at the pinned android tree. The
environment is minimal, the timeout defaults to 90 seconds (hard
maximum 120 seconds) and combined stdout/stderr capture has a 64 KiB
hard cap. The bounded runner terminates the child process group on
timeout or overflow.

The offline flag restricts Gradle dependency resolution; **it is
not an OS network sandbox or a general guarantee that a trusted Gradle
plugin cannot spawn other commands**. Do not activate this executor
against unknown unreviewed Gradle projects. Host source pinning and
local operator configuration are necessary prerequisites, not a
substitute for independent source provenance and process isolation.

## Durable jobs, outputs and privacy

H2.d supplies an owner-scoped SQLite durable job state machine. Every
request and exact action/variant/revision/wrapper digest maps to one
stable opaque job ID. Transitions are prepared -> queued -> running,
with exactly one worker claim. An exclusive OS file lock scoped to the operator-pinned checkout
prevents simultaneous builds using the same job-store root. Duplicate
submissions and process restarts never cause a second claim for one
request. A different request during a locked build is safely reported
as busy and never reserves a speculative worker. All active/uncertain
jobs in the same owner scope impose a conservative durable recovery
fence: new requests are blocked until trusted reconciliation. For this
reason each approved checkout should have a dedicated job-owner scope.

A successful job persists a small structured JSON report inside the
existing H2.c private artifact store, referenced by an opaque handle.
An assemble_debug job additionally requires a freshly created or
updated bounded regular, owned, non-symlinked, non-hardlinked,
CRC-validated ZIP APK at the fixed debug output path. A stale output
left by a prior build cannot be reported as the result of a new job.
The APK is saved as a separate private artifact. This establishes ZIP
integrity and content SHA, **not** signing or deployment authorization.
H2.e must separately verify signatures when configured.
Tests and lint jobs have a report handle but no APK handle.

No raw Gradle stdout, stderr, local paths, keystores, secrets, ANSI
escape codes, private artifact bytes or environment credentials are
included in a Tool result or build report. Nonzero exit, output
truncation, invalid APK, storage failure or absent SDK/JDK yields
typed failure, never success. Runtime timeout, lost worker ownership
or uncertain post-execution receipt means uncertain; the controller
does not retry an unsafe or unknown effect. Audit events are retained
as H2.d metadata.

A replay of a completed idempotency key returns the existing job ID
and durable digest without launching a new worker. When the associated
private report and APK records still exist, their opaque handles are
also recovered from digest-matching metadata. Expired/revoked records
are not rebuilt; successful status can therefore have null handles.
The caller can inspect owner-scoped job state through the separately
opted-in host_job_status Tool.

## Limitations and test strategy

This is a bounded single-Host operator-controlled offline build adapter,
**not** a general worker scheduler or cross-runtime device lease.
It does not promise deterministic Gradle plugins, network isolation,
cryptographic attestations of third-party builds, remote deployment,
or rollback of already executed child processes. Killing the
local process group cannot undo a side effect already completed.
The Tool advertises destructive and open-world hints as true because
trusted Gradle scripts may mutate checkout output files and the
Gradle --offline flag is not a genuine network sandbox.
An expired running lease therefore reports uncertain and cannot
be dispatched again automatically.

T-H2F-01 through T-H2F-06 cover synthetic Gradle fixtures, wrapper
and toolchain denial, privacy/resource caps, success/failure/timeout,
local process cleanup, concurrent owner claims and localhost MCP.
No physical Android device or arbitrary Gradle project is exercised
by these acceptance tests.

Per docs/host-merge-gates.md, integration requires source review,
per-module coverage, Ruff/mypy/Bandit, Git hooks, Python 3.11–3.14 on
both Mac ARM64 and Linux ARM64 at the identical Git SHA, separate
wheel/sdist installs, and postmerge smoke. Hosted Actions that
cannot start due to billing are not counted as passed.
