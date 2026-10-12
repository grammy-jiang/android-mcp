# Android Host MCP: FastMCP framework-first refactor F0 acceptance

**Date:** 2026-10-12, Australia/Sydney.
**Target:** grammy-jiang/android-mcp; Host Python runtime only.
**Verified origin/main:** 6ed3d3beabe0a40104c7b072ab7c5480dbd0b079.
**Framework:** pinned standalone FastMCP 4.1.0; MCP Python SDK 2.3.0.
**Outcome:** complete for the bounded Host FastMCP adapter refactor and
default-denied security improvements described here, not a general
authorization to deploy an externally reachable or mutating Android MCP server.

## Completed change inventory

| Wave / PR | Change | Merge evidence |
| --- | --- | --- |
| Wave 0 and Wave 1, PRs 17-22 | Plan, synthetic baseline, version compatibility, public contract decisions and 11 characterization tests | Merged; checked in docs and tests |
| Wave 2, PR 23 | Use native FastMCP client-facing unexpected-error masking | Merged |
| Wave 2, PR 24 | Package canonical Host output JSON Schemas and prove copy equality in tests | Merged |
| Wave 2, PR 25 | Metadata governance and safety tests | Merged |
| Wave 3, PR 27 | Switch Host acceptance clients to stable MCP structured_content | Merged |
| Wave 3, PR 30 | Publish canonical device_status output Schema | Merged |
| Wave 3, PR 31 | Publish canonical adb_observe output Schema and non-enforcing Probe hints | Merged |
| Wave 3, PR 33 | Publish canonical adb_develop output Schema and four typed Action input choices | Merged |
| Security, PR 34 | Prevent invalid device ID / Action kind from being reflected unbounded in denial envelopes | Merged |
| Security, PR 35 | Uniformly refuse APK paths when no trusted APK root is configured; never probe path existence first | Merged |
| I3, PR 36 | Declare conservative Tool titles, metadata hints and ADB-daemon side effect | Merged |

All changes are on the verified main commit above. The three MCP
tool names remain device_status, adb_observe and adb_develop.
There are no new public Resources or Prompts.

## F0 full local matrix: tests actually executed

These commands ran on the same exact main Git revision listed above,
not on an unmerged branch or a differently named worktree.

| Host | Python | Full Host result | Evidence log |
| --- | --- | --- | --- |
| MacBook, macOS ARM64 | 3.11 | completed / passed, 366 tests | /tmp/android_mcp_f0_mac_3.11_20261012.log |
| MacBook, macOS ARM64 | 3.12 | completed / passed, 366 tests | /tmp/android_mcp_f0_mac_3.12_20261012.log |
| MacBook, macOS ARM64 | 3.13 | completed / passed, 366 tests | /tmp/android_mcp_f0_mac_3.13_20261012.log |
| MacBook, macOS ARM64 | 3.14 | completed / passed, 366 tests | /tmp/android_mcp_f0_mac_3.14_20261012.log |
| sextant, Linux ARM64 | 3.11 | completed / passed, 366 tests | /tmp/android_mcp_f0_linux_3.11_20261012.log |
| sextant, Linux ARM64 | 3.12 | completed / passed, 366 tests | /tmp/android_mcp_f0_linux_3.12_20261012.log |
| sextant, Linux ARM64 | 3.13 | completed / passed, 366 tests | /tmp/android_mcp_f0_linux_3.13_20261012.log |
| sextant, Linux ARM64 | 3.14 | completed / passed, 366 tests | /tmp/android_mcp_f0_linux_3.14_20261012.log |

Each full Host gate includes its locked unit/contract and localhost
HTTP fake-ADB tests, Ruff lint/format, strict mypy, Bandit and the
independent per-module statement and true branch coverage policy.
All eight invocations reported that all Host quality gates passed.

- Mac clean sdist/wheel install and CLI doctor: completed / passed.
  Log: /tmp/android_mcp_f0_mac_package_20261012.log.
- Linux ARM64 clean sdist/wheel install and CLI doctor:
  completed / passed.
  Log: /tmp/android_mcp_f0_linux_package_20261012.log.
- Mac manual dependency advisory check: completed / passed,
  uv audit --project host --locked, exit code 0;
  116 packages evaluated, no known vulnerabilities or adverse
  project statuses reported at this check.
  Log: /tmp/android_mcp_f0_uv_audit_20261012.log.
- In-process FastMCP 4.1 catalog inspection: completed / passed.
  Exactly 3 Tools, 0 Prompts, 0 Resources; canonical output Schema
  IDs for all Tools; four named development action variants; Tool
  hints correspond to the conservative policy in I3.
- Ordinary Chat/Work model tool-selection evaluation: not run /
  unavailable as part of F0; the V1 evaluation corpus remains
  unscored. Do not claim a ChatGPT product-surface result.
- Official MCP conformance suite: not run; current tests exercise
  the installed FastMCP client and actual loopback HTTP fake-ADB path.
- New physical USB Android-device acceptance at this final SHA:
  not run by design. Previous independent opt-in Host read-only
  hardware smoke is historic evidence, not this F0 revision.
  No root, APK install, real Logcat capture or other device mutation
  occurred during these F0 tests.
- GitHub Hosted Actions: unavailable; jobs fail to start because of
  account billing/usage limits. They were NOT counted as passing.
  The user rejected increasing the budget; use documented zero-paid
  local Mac/Linux merge gates instead.

## Verified interface and security contract

- FastMCP handles MCP transport, registration, typed Tool advertisement,
  output Schema publication, client-visible unexpected-exception masking
  and advisory Tool metadata; domain/ADB policy remains in application
  code, not in a custom protocol layer.
- Only one explicitly named, online ADB-authorized device can be
  targeted by observation/development calls; no implicit first-device
  fallback or unrestricted adb shell is available.
- Expected application denials preserve typed business errors
  (for example UNKNOWN_OPERATION, INVALID_DEVICE_ID and
  MUTATION_DISABLED) without turning them into unexpected Tool errors.
- Mutation stays disabled in the default production composition;
  trusted grants, audit, signed approval and actual cross-runtime
  lease fencing remain prerequisites for any future enabling project.
- Output byte/character limits, subprocess deadlines and timeout
  cleanup remain application/infrastructure responsibilities.
- APK path validation when no trusted roots exist is uniformly denied
  before accessing the caller-selected filesystem path.
- Conservative readOnlyHint=false for each Tool accounts for
  host-side ADB daemon effects and the mixed potential of
  adb_develop. Tool metadata is advisory, not an authorization gate.

## Deferred or separately gated risks

1. FastMCP mask_error_details protects the client-visible unexpected
   exception payload; server-side exception logs may still contain
   error details. Logging/redaction needs an independently scoped
   follow-up before exposing any untrusted remote transport.
2. Framework-generated input validation errors can include a rejected
   user input_value. No new Host-specific validation exception
   middleware is claimed. Risk is limited by the current loopback
   only deployment and must be reviewed separately for remote use.
3. Global strict_input_validation (I2) is deliberately deferred:
   changing legacy Pydantic coercion, including dry_run string inputs,
   would be a visible compatibility change. Strict-before-mutation
   is mandatory for any future privileged operation design.
4. Replacing async + asyncio.to_thread (I4) has no demonstrated
   safety or resource benefit; current bounded ADB subprocess
   cancellation/deadline handling is retained.
5. Native foreground service lifecycle, user authentication,
   Host/Native durable cross-process leases, Android APK real
   hardware acceptance and authenticated external deployment are
   separate release/security projects; not certified by Host F0.
6. No fresh independent cross-provider code review was performed
   in this self-implemented wave. Independent approval remains
   necessary before privileged deployment or security-enabling work.
7. Default-denial changes are intentionally more conservative than
   previous accidental behavior. They are covered by typed-error,
   conformance and negative tests but are not a claim of unchanged
   wire values for invalid/untrusted inputs.

## Rollback, evidence and handoff

Each implementation stage was merged as a scoped, independently
revertible PR. Revert the affected individual PR if a verified
application contract regression appears; never force-reset main
or overwrite a Native developer's worktree. The exact main SHA
and tests above are the primary handoff reference.

Host main worktree: /Users/grammy-jiang/Projects/android-mcp-host-security-followup.
Linux verification worktree:
  /home/grammy-jiang/Projects/android-mcp-host-fastmcp-f0-final-20261012.

The acceptance of this bounded framework-first Host refactor closes
its planned required F0 gate. Additional privilege, transport,
auth and Native features require new separate designs and approvals.
