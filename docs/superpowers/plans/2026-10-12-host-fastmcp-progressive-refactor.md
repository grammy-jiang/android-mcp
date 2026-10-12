# Host FastMCP Framework-First Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use the installed
> chatgpt-mcp-engineering planning, audit/refactor, compatibility and
> verification guidance. For implementation use superpowers:
> subagent-driven-development or executing-plans, task by task. All
> work items below are tracked using checkboxes; no production change is
> authorized merely by this planning document.

**Goal:** Gradually align the Python Android Host MCP with standalone
FastMCP 4.1.0's documented responsibilities without losing any current
supported behavior, security restrictions or cross-platform functionality.

**Architecture:** Keep FastMCP responsible for MCP transport, tool
registration, input/output schema exposure, supported validation,
client-facing error masking, and appropriate framework lifecycle hooks.
Keep Android device identity, ADB allowlists, operation policy, bounded
subprocesses, grants, local/durable lease semantics and audit in application
and infrastructure code. The CLI and MCP adapters should use the same
application services; neither should call the other.

**Tech stack:** Python 3.11-3.14; standalone FastMCP 4.1.0;
MCP Python SDK 2.3.0 via locked dependencies; Pydantic as supplied by
the current lock; uv, pytest, Hypothesis, Ruff, mypy, Bandit, GitHub CI;
Linux ARM64 sextant is the optional read-only USB acceptance node.

**Source specifications:** contracts/device-status.v1.schema.json,
contracts/adb-observation.v1.schema.json,
contracts/adb-development-action.v1.schema.json,
contracts/adb-development.v1.schema.json, docs/security.md,
docs/host-merge-gates.md, docs/parallel-workstreams.md and
docs/host-native-coordination.md. This plan refines, not replaces, those
contracts. FastMCP framework claims must be checked against the installed
4.1.0 version and dated official documentation; an API's existence
does not mean it is appropriate for the target's public contract.

**Planning baseline:** 2026-10-12, origin/main at
0a1e0a418dab134d5081c5d7308843379f69fb8a (Native N2 merged).
Host-only source was unchanged by that merge. Recheck origin/main,
FastMCP version, open PRs, CI, and worktree ownership at each execution
wave. Prior Host full gate: 305 tests, approximately 99% combined
coverage; treat this as dated evidence, not an evergreen assertion.

**Status:** PROPOSED IMPLEMENTATION PLAN. Small refactor slices require
the applicable S1-S5 choices and protection tests below to be settled;
do not execute all rows merely because this plan exists.

## A. Scope, acceptance and non-negotiable invariants

The requested outcome is framework-respecting integration, not a new
Android MCP product, a migration away from FastMCP or a new transport.
Keep the existing three public tool names: device_status, adb_observe,
adb_develop. Keep localhost-only HTTP on 127.0.0.1 (default port 8765),
the existing CLI doctor/serve behavior, typed device selection and
bounded ADB subprocess model, no root or arbitrary shell, and denied
APK installation/instrumentation. No Native code or shared contract
files may be changed unilaterally.

Each **finished implementation slice** must leave a usable complete Host:

- Preserve the frozen, accepted public behavior and exactly three tools,
  unless an explicit separately approved, versioned contract PR says
  otherwise. Capture MCP tools/list, MCP tools/call, structured response,
  errors, CLI doctor, and loopback HTTP compatibility.
- Do not confuse an MCP is_error flag with the application envelope's
  status="error". Do not silently switch between them in a refactor.
- Enforce explicit device selection, no mutation, output limits, typed
  denials, no sensitive exception material returned to clients.
- Pass focused red/green tests, then all Host quality gates locally,
  pre-commit and pre-push, and exact-head GitHub CI on the supported
  macOS/Linux x Python 3.11/3.12/3.13/3.14 matrix, wheel install,
  dependency audit and repository hygiene before merge.
- After each merge, verify main HEAD, post-merge applicable CI, and
  rebase only independently owned later feature branches. A failing
  or skipped required gate means STOP and repair, not bypass.
- Any shared schema change additionally requires coordination with
  Native and its applicable contract/CI suite. Physical-device tests
  are separately authorized and serialized across sessions.

### Review focus: negative and boundary cases

1. Unexpected exception with a synthetic secret: MCP Tool error must
   not echo it; server log exposure must be assessed independently.
2. Unknown probe/action or wrong device: preserve expected typed
   application denials without launching an ADB action.
3. Strict argument validation: string "true" for dry_run and
   invalid action structure must have intentionally specified semantics;
   changing an existing coercion counts as an external contract change.
4. Competing requests, timeout and cancellation: no implicit first
   device, no unbounded child process and no lost operation safety gate.
5. Packaging and reconnection: a clean wheel over real localhost
   Streamable HTTP must preserve the three-tool catalog and output
   envelope without relying on source-tree-only schema files.

## B. What the framework owns (and what it does not)

| Concern | Owner | Rule |
| --- | --- | --- |
| MCP handshake, transport, serialization, tools/list | FastMCP / SDK | No hand-coded MCP protocol or HTTP compatibility layer |
| Tool registration, metadata, validation, schema exposure | FastMCP adapter | Use supported 4.1.0 interfaces; protect published contract |
| Unhandled error masking | FastMCP | Prefer mask_error_details; separately handle server logs |
| Deliberate application denials and partial results | Application service | Stable typed codes and versioned envelopes |
| Device ID and ADB allowlist | Host application | Always checked regardless of MCP input validation |
| ADB process groups, byte limits, timeouts | Host infrastructure | Not delegated to FastMCP request timeout |
| Signed grants, audit, durable Host/Native lease fencing | Security domain | Never infer from model hint or middleware |
| CLI argument parsing and exit codes | CLI adapter | Share application services, not MCP tool calls |
| Resource/middleware/lifespan helpers | FastMCP, if justified | Do not add abstractions without an owned resource or use case |

FastMCP 4.1.0 provides mask_error_details, strict_input_validation,
Tool annotations, output_schema, run_in_thread, and lifespan hooks
in its installed API. Whether, where and how they are enabled is a
separate target decision. Background tasks, new public tools,
remote AuthProvider activation, dynamic tool providers and persistent
session stores are **out of scope** for this refactor.

## C. Decisions and prerequisites before implementation (S1-S5)

- [ ] S1 Compatibility: capture exact standalone FastMCP, MCP SDK,
  Python and relevant protocol/client versions; independently verify
  error masking, strict input, tool schema, annotations, sync tool
  dispatch, HTTP transport and cancellation semantics. Newer docs do
  not automatically describe the pinned 4.1.0 build.
- [ ] S2 Contract: identify observed versus required versus accidental
  behavior for all three public tools. Decide whether coercive inputs,
  app-level error envelopes, read-only hint claims and metadata changes
  are part of the intentionally supported contract. Freeze agreed
  schema-v1 shapes or explicitly approve a versioned change.
- [ ] S3 Architecture: retain current application/infra modules and
  FastMCP-only server adapter. Decide **one** public schema source of
  truth, e.g. typed adapter models verified against canonical JSON
  Schema, or explicitly packaged canonical schema passed through
  FastMCP. Do not invent a second drifting schema or depend on
  repository paths in installed wheels.
- [ ] S4 Verification: approve focused, structural contract, real
  HTTP, error, platform and security checks for each affected slice.
  A mock-only unit pass does not establish wire compatibility.
- [ ] S5 Enforcement: keep pre-commit fast and CI authoritative.
  Identify which checks run on every PR and which only on relevant
  changes; require exact PR-head evidence. The existing GitHub
  private-repository branch-protection limitation remains a separate
  administrative blocker.

Decisions that remain open block only dependent tasks. In particular,
strict-input enforcement and any new write Tool require contract
approval; error masking does not require adopting a new schema.

## D. Dependency graph and parallel execution waves

All task IDs refer to the work packages in Section E. A work package is
the smallest independently reviewable and revertible PR.

    Baseline B0
       |
       +--> P1 framework version/POCs --------+
       +--> P2 public semantics inventory ----+--> D0 accept S1-S5
       +--> P3 characterization harness ------+
       |                                        |
       +--> E1 exception protection <----------+
       |                                        |
       +--> M1 boundary models/tests <---------+
       +--> V1 metadata/check design <---------+
                                                |
                                   I1 single-writer server integration
                                                |
                                   I2 strict-input decision/optional PR
                                                |
                                   I3 annotations/error decision/optional PR
                                                |
                                   I4 sync dispatch decision/optional PR
                                                |
                                   F0 final integration + docs + evidence

Wave 0: B0 only (read-only snapshot, no structural edit).
Wave 1: P1/P2/P3 in parallel, each with disjoint files and a separate
worktree; the decision owner performs D0 only after their evidence.
Wave 2: E1 may ship independently as an early security PR; M1 and V1
can run concurrently **without editing server.py**.
Wave 3: I1 alone owns server.py and integrates the accepted, tested
boundary models. If I2/I3 materially change external semantics,
they follow as separate PRs after I1, never quietly bundled with it.
Wave 4: I4 only if a concurrency/lifecycle experiment justifies it.
F0 reconciles main and closes evidence gaps.

**Maximum planned concurrency:** three isolated evidence worktrees in
Wave 1; two or three disjoint implementation/test worktrees in Wave 2;
**one writer of server.py per integration wave**. Parallelism is for
independent deliverables, not long-lived competing feature branches.

### Shared-file and integration ownership

The Host integration owner exclusively writes server.py,
host/pyproject.toml, host/uv.lock, contracts/*, AGENTS.md, shared CI
and canonical coordination docs during integration. Other workers
may read these but submit change requests rather than editing them.
A change to contracts/* needs explicit Native coordination before
any affected merge. No force push, reset --hard, clean, stash over
another worker, or concurrent rebases of shared branches.

For each wave start from the then-current origin/main; use one owned
worktree/feature branch per write package and record HEAD SHA, base SHA,
diff, tests, reviewer, residual risks, rollback and PR URL. Merge small,
green PRs promptly. If main moves, update later worktrees only after
checking their ownership and dirty state.

## E. Atomic work packages and tests

The "Files" paths below are ownership, not an order to create them
without the required contract decision. Every implementation package
is a distinct PR, with a complete passing Host at its boundary.

### B0 — Reproducible baseline (serial, read-only)

**Files:** write evidence only to
docs/host-fastmcp-refactor-baseline.md; read host/src/android_mcp_host,
contracts, Host tests and CI. **Produces:** exact base SHA, versions,
catalog snapshot, sample outcomes and known limitations.

- [ ] Inspect Git worktrees and latest main; record 4.1.0 FastMCP,
      SDK and Python versions from the locked interpreter.
- [ ] Via FastMCP Client with fake ADB, capture names, titles,
      descriptions, input/output schemas, annotations, and sample
      success/denial responses for exactly three tools.
- [ ] Run the real localhost HTTP fake-ADB test, CLI doctor, and
      full Host check. Do not invoke a real device.
- [ ] Label observations REQUIRED / OBSERVED_ONLY / ACCIDENTAL /
      PROPOSED / UNKNOWN. Never freeze accidental behavior blindly.
- [ ] Commit a baseline/evidence-only PR after repository hygiene.

    python3 scripts/dev.py doctor --require-hooks
    uv run --project host --locked --group dev pytest -q host/tests/test_server.py host/tests/test_server_development.py host/tests/test_host_http_fake_adb.py
    python3 scripts/dev.py check

**Gate:** baseline is reproducible; unclassified failures block
behavior-preserving refactoring.

### P1 — Version-specific FastMCP behavior study (parallel wave 1)

**Files:** docs/host-fastmcp-4-1-compatibility.md only. Local Python
experiments are disposable and must not be shipped as product code.

- [ ] Verify 4.1.0 exception masking and deliberate ToolError
      behavior, distinguishing client results from server logs.
- [ ] Verify strict_input_validation behavior for string booleans,
      wrong list types, malformed nested objects and unknown keys.
- [ ] Compare Pydantic type-derived and explicit output_schema
      mechanisms, including nested JSON Schema conditions/refs,
      emitted tools/list, returned-result validation and wheel
      packaging.
- [ ] Compare run_in_thread sync Tool execution with the existing
      async + asyncio.to_thread wrapper using synthetic concurrency,
      cancellation and timeout cases.
- [ ] Record source/version/date, exact POC and pass/fail evidence.

**Gate:** framework features used later have reproducible, pinned
version evidence; unanswered issues remain explicitly blocked.

### P2 — Public contract and failure-semantics decision (parallel wave 1)

**Files:** docs/host-fastmcp-public-contract-policy.md only.
**Reads:** canonical contracts and B0 inventory.

- [ ] Record device_status, adb_observe, adb_develop use cases, names,
      descriptions, fields, result shapes, device scope and side
      effects; include all four typed adb_develop action variants.
- [ ] Decide per-case framework Tool error versus typed application
      denial: wrong device, invalid type, unknown probe/action,
      unavailable ADB, partial results, output cap, disabled mutation.
- [ ] Explicitly decide whether existing dry_run="true" coercion is
      supported or accidental. Changing it is a contract change.
- [ ] Decide annotations separately. ADB discovery may start a host
      daemon, and future coordinator injection could make adb_develop
      mutating; do not blindly label everything read-only.
- [ ] Identify any potential wire-version bump; keep three tools
      for this plan unless separately accepted.

**Gate:** the required public semantics are approved before any
external schema/annotation/validation change.

### P3 — Characterization and contract test harness (parallel wave 1)

**Files:** create host/tests/test_fastmcp_public_contract.py and
optional host/tests/fixtures/fastmcp_baseline.json only.

- [ ] Construct fake ADB, ProbeService and OperationService fixtures
      with no actual device contact.
- [ ] Assert the three tool names, intentionally required schema
      fields and application responses; use actual tools/list and
      tools/call rather than introspecting Python functions only.
- [ ] Exercise normal response, wrong/offline device, unknown probe,
      unsupported action, bounded/partial response and
      MUTATION_DISABLED with zero forbidden command execution.
- [ ] Exercise real subprocess + loopback HTTP via existing
      test_host_http_fake_adb.py, keeping outputs synthetic.
- [ ] Ensure tests protect P2 REQUIRED behavior, not every incidental
      baseline detail; run focused and whole Host suites.

    uv run --project host --locked --group dev pytest -q host/tests/test_fastmcp_public_contract.py host/tests/test_host_http_fake_adb.py

**Gate:** executable protection exists without changing production
Tool registration.

### D0 — Freeze decisions for the next eligible slices (serial)

**Files:** P2 policy document only; owner = Host integrator.

- [ ] Reconcile P1/P2/P3 and accept the affected S1-S5 decisions.
- [ ] Record allowed differences in input/output/metadata and exact
      error shapes. Defer unapproved strict-input or tool splitting.
- [ ] Identify needed POCs; close them, or narrow the dependent scope.
- [ ] Confirm each package owns disjoint writable files, tests,
      rollback and an independent review boundary.
- [ ] Approve the first package whose prerequisites are closed.

**Gate:** no implementation worker must invent an external contract.

### E1 — Use FastMCP's own error masking (early independent PR)

**Files:** modify host/src/android_mcp_host/server.py; create
host/tests/test_fastmcp_error_masking.py. May update a Host-only
security note. **Consumes:** B0, P1, accepted error semantics.

- [ ] Write a failing FastMCP Client test: an injected unexpected
      exception includes a synthetic canary; is_error is true and
      the canary must not be visible to the MCP caller.
- [ ] Prove normal status, read-only probes, typed
      MUTATION_DISABLED and CLI doctor still behave as before.
- [ ] Make the smallest change: FastMCP(mask_error_details=True).
      Do not build a second generic exception middleware.
- [ ] Retest unexpected versus deliberate errors. Record separately
      that framework masking does not certify server logs as
      secret-free.
- [ ] Run all slice gates, PR review, CI, merge and post-merge gate.

**Rollback:** revert this PR only. **Gate:** unexpected errors
do not echo private exception details; normal tools still work.

### M1 — MCP boundary models / schema source (parallel wave 2)

**Files:** create host/src/android_mcp_host/mcp_boundary.py and
host/tests/test_mcp_boundary.py. Do not modify server.py.
**Consumes:** P1 schema POC, P2 contract decision, D0.

- [ ] Write RED tests comparing model acceptance and serialized
      output against canonical v1 JSON Schema fixtures, including
      optional values, additionalProperties, null and error cases.
- [ ] Implement only approved MCP-facing Pydantic/types or packaged
      canonical schema interface. Choose the approach from P1, not
      from convenience. Keep ADB/domain code FastMCP-independent.
- [ ] Ensure runtime does not load schema files relative to the Git
      checkout: clean wheels must contain any required resources.
- [ ] Verify schema compatibility and normal JSON wire envelopes,
      then run the complete Host checks; commit models/tests alone.
- [ ] Submit the exact interface and PR to the server.py integrator.

**Gate:** no Tool schema change yet; independently tested boundary
definitions are ready for staged registration.

### V1 — Tool metadata and protocol test design (parallel wave 2)

**Files:** create host/tests/test_fastmcp_metadata_policy.py and
docs/host-fastmcp-metadata-review.md; no server.py edits.

- [ ] Specify title, descriptions, input/output schema, annotations,
      failure and retry semantics for every existing Tool.
- [ ] Build tools/list verification and focused model-tool-selection
      prompts. Do not mistake Python unit tests for actual ChatGPT
      tool-selection evidence.
- [ ] Mark disputed readOnlyHint/idempotency claims as unresolved,
      not necessarily false or automatically true.
- [ ] Confirm metadata never substitutes for application device
      authorization or enlarges permissions.
- [ ] Stage tests/docs for integrator without changing registrations.

**Gate:** metadata expectations are reviewable before the decorator
owner touches production code.

### I1a — Publish device_status schema (serial PR)

**Files:** sole integrator owns server.py and the device_status
portion of test_fastmcp_public_contract.py. Depends on M1 + D0.

- [ ] RED test: tools/list currently reports a generic object where
      the accepted device-status-v1 contract is required.
- [ ] Register an approved typed return or output_schema mapping
      using the supported FastMCP 4.1.0 adapter mechanism.
- [ ] Preserve build_status(), CLI doctor and ADB missing-device
      semantics; verify actual tools/call over in-process + HTTP.
- [ ] Full Host local gate, CI, review, merge, post-merge main.
      Do not change other Tools in this PR.

### I1b — Publish adb_observe schema (serial PR)

**Files:** server.py plus the observer-focused contract tests.
**Requires:** I1a already merged into main.

- [ ] RED test for enumerated nine probes, 1-8 selection, duplicate
      rejection and the approved observation output contract.
- [ ] Register typed probe input/output only at FastMCP boundary.
      Retain application duplicate/allowlist/online checks as
      direct-call defense in depth.
- [ ] Test valid, malformed, wrong/offline/ambiguous devices,
      partial/truncated fields and no unauthorized subprocess.
- [ ] Full local/HTTP/CI gates, merge, verify main.

### I1c — Publish adb_develop action/output schema (serial PR)

**Files:** server.py and development-focused contract tests.
**Requires:** I1b merged and P2 mutation/preview semantics accepted.

- [ ] RED tools/list test for logcat_snapshot, package_details,
      instrument_test and install_apk action shapes and existing
      output result statuses.
- [ ] Integrate approved boundary types/schema without changing
      prepare_action's domain-policy role or enabling mutation.
- [ ] Verify preview vs execution, null/partial results, wrong
      action, unregistered device and MUTATION_DISABLED; also
      verify exactly three public Tools remain.
- [ ] Run full tests, clean wheel, HTTP, exact-head CI, and
      post-merge main checks. Split any intentionally breaking
      semantics into a separately reviewed contract PR.

### I2 — Strict input validation (conditional behavior-change PR)

**Files:** server.py + host/tests/test_fastmcp_strict_validation.py.
**Blocked until:** P2 decides coercion and P1 verifies 4.1.0
behavior. Do not implement if compatibility decision is DEFER.

- [ ] Characterize the existing boolean-string and nested-object
      behavior in deterministic MCP wire tests.
- [ ] Explicitly accept rejecting that behavior, or keep it unchanged.
- [ ] If approved, write RED tests and use FastMCP's
      strict_input_validation or narrowly typed strict fields;
      never silently change the global default for all clients.
- [ ] Verify invalid inputs do not run ADB, typed domain denials are
      still appropriate, and any changed public contract is versioned.
- [ ] Standalone PR with full local/CI + rollback.

### I3 — Safety annotations and error-semantics metadata (conditional PR)

**Files:** sole server.py integrator + metadata tests from V1.
**Requires:** I1 and the corresponding accepted P2 policy.

- [ ] Assert accurate per-tool annotations and descriptions from
      actual MCP tools/list, with failure/retry meaning.
- [ ] Apply only approved metadata. Do not label adb_develop
      read-only merely because production mutation is currently
      disabled; do not ignore adb device discovery side effects.
- [ ] Preserve deliberate domain error envelopes and no mutation.
      Any switch to MCP ToolError for a domain denial is a separate
      external-contract decision.
- [ ] Full local + loopback HTTP + exact-head CI, then integrate.

### I4 — Optional thread/lifespan simplification (conditional PR)

**Files:** server.py + host/tests/test_fastmcp_execution_semantics.py.

- [ ] Measure concurrency, cancellation, timeout and process cleanup
      with the current async + asyncio.to_thread handlers.
- [ ] Compare synthetic alternatives using sync FastMCP Tools and
      run_in_thread. Do not infer OS subprocess cancellation
      guarantees from HTTP-request cancellation.
- [ ] If behavior is demonstrably equivalent or safer, replace
      one Tool at a time and preserve application interfaces;
      otherwise record SKIPPED and retain the current adapter.
- [ ] Add lifespan only when a real owned long-lived resource needs
      setup/shutdown; current AdbClient need not justify it.
- [ ] Full suite/HTTP/CI and documented rollback if changed.

### F0 — Final integration and verification

**Files:** Host-only documents and handoff evidence, with explicit
Native coordination if a shared path is affected.

- [ ] On latest main, compare the actual three tools/list schemas
      and tools/call behaviors to approved differences.
- [ ] Verify macOS/Linux x Python 3.11, 3.12, 3.13, 3.14,
      packaging, lock/security, repository hygiene and policy gates.
- [ ] If Host runtime ADB or deployment semantics changed, separately
      authorize and serialize a bounded **read-only** sextant hardware
      acceptance. Never default to APK install, root, reboot or Logcat.
- [ ] Record tests separately as not_run, running, completed, skipped
      or blocked, and outcomes separately as passed/failed/error.
- [ ] Confirm merged main, all owned Worktrees, CI SHA, PR reviews,
      rollback instructions, unresolved gaps and Native coordination.

## F. Mandatory quality gates on every code slice

During development run its targeted RED/green tests. Before PR
integration run the full suite and all repository checks:

    uv run --project host --locked --group dev pytest -q host/tests/test_host_http_fake_adb.py host/tests/test_server.py host/tests/test_server_development.py host/tests/test_server_observation.py
    python3 scripts/dev.py check
    uv run --project host --locked --group dev pre-commit run --all-files
    uv run --project host --locked --group dev pre-commit run --hook-stage pre-push --all-files
    bash scripts/check-host-package.sh
    git diff --check

Check current PR head and its checks, *not a historical pass*:

    gh pr view PR_NUMBER -R grammy-jiang/android-mcp --json headRefOid,baseRefOid,mergeable,mergeStateStatus,isDraft,reviewDecision
    gh pr checks PR_NUMBER -R grammy-jiang/android-mcp --json name,state,link

The Host integrator must certify applicable macOS/Linux Python
matrix jobs, package, security/hygiene, negative tests, public
FastMCP contracts, no-device CLI and real loopback HTTP at the
actual head SHA. Following each merge check post-merge main CI.
Test presence/configuration does not prove execution; a skipped
required check is not a pass.

Docs-only/evidence PRs require the applicable hygiene and docs
checks but not a real-device run. Shared contract edits require
Native coordination and additional contract/CI checks.

## G. Rollback and stop rules

- Each PR changes one reviewable behavior/boundary and is
  independently revertible. Do not bundle error masking, strict
  validation, schema migrations and thread changes.
- Stop for any unexpected Tool addition, expanded listen interface,
  device mutation, leaked synthetic canary, changed denial semantics,
  lost output limits, failed CI or competing worktree owner.
- If a PR fails: keep evidence, repair only its branch, recheck exact
  SHA and rerun the gates; if already integrated use an ordinary
  revert PR. No reset --hard or force-push over other workers.
- If canonical JSON Schema cannot be surfaced faithfully by
  FastMCP 4.1, keep current wire output and document a bounded,
  separately versioned alternative. Do not fork protocol machinery.
- Scope excludes remote authenticated deployment, new privileged
  handlers, Native state control, background tasks and dependency
  upgrades. Such work requires separate decisions.

## H. Handoff format for each parallel worker

Each worker receives the package ID, base SHA and versions,
approved contracts, owned branch/worktree and writable file list,
read-only dependencies, forbidden operations, targeted tests,
full gate commands, expected red/green evidence, PR/rollback
requirements and downstream owner.

The integrator alone handles server.py and shared files. A worker
must not start a package whose gate is open. Other workers can
progress on independent evidence or test modules while a PR waits
for CI, but must not edit shared production modules concurrently.

## I. Decision register and proposed defaults

| Decision | Preferred position | Gate before change |
| --- | --- | --- |
| Public tool catalog | Keep three | Separate contract decision for new Tool |
| Uncaught exception | FastMCP masking | P1 proof and E1 negative test |
| Schema source | Canonical v1, with verified FastMCP adapter | P1 schema POC and D0 acceptance |
| Domain denials | Keep structured envelopes | P2 before changing is_error |
| Coercion | No automatic strict toggle | P2 compatibility decision |
| Read-only metadata | Conservative, per Tool | Explicitly account for ADB daemon and future mutation |
| adb_develop mutation | Disabled | Separate independent security-gated project |
| Sync Tool change | Optional only | I4 equivalence evidence |
| Lifespan/middleware | Do not add without lifecycle owner | New owned resource/use case |
| Remote auth and listener | Out of scope; loopback only | Separate security project |
| Runtime dependencies | Keep pinned FastMCP 4.1.0 | Separate dependency-upgrade review |

**Next eligible work:** B0 followed by independent read-only P1/P2/P3.
E1 is the first potential code change once the accepted contracts,
required tests and relevant S1-S5 gates are closed. This document
does not authorize an agent to relax tests or permissions.
