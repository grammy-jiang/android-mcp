# Host FastMCP refactor — Wave 0 baseline evidence

**Captured:** 2026-10-12 (Australia/Sydney), synthetic MCP fixture and MacBook ARM64.

**Repository:** `grammy-jiang/android-mcp`, `origin/main` at
`f536b26cd717adcbf7e5de96cb0d2118bf84da33` (the merged refactor-plan PR #17).
**Worktree:** `~/Projects/android-mcp-host-fastmcp-wave0` on the independent
`docs/host-fastmcp-wave0-baseline` branch. This evidence has **no Host
production-code changes**.

## Runtime and test surface

- macOS ARM64; locked Python 3.13.16, standalone FastMCP 4.1.0, underlying
  MCP Python SDK 2.3.0, Pydantic 2.14.1.
- Client experiment uses `fastmcp.Client(create_server(...))` with an injected
  **synthetic** AdbReport, fake fixed probe executor, and fake operation runner.
  No real ADB command was executed by this test. The fixture and exact observed
  input/output metadata are in
  [host-fastmcp-baseline-tools.json](host-fastmcp-baseline-tools.json).
- The Host full gate includes its normal read-only doctor; a separate host
  device-discovery check observed one connected ADB entry on the Mac at capture
  time. No real-device probes, install, instrument, screenshots or logcat were
  executed in this Wave 0 evaluation. Do not assume a previous zero-device
  observation remains true, or attempt to claim which runtime owns that device.

## Completed checks

| Check | Command / scope | Result |
| --- | --- | --- |
| Developer diagnostics | `python3 scripts/dev.py doctor --require-hooks --json` | Completed, exit 0; hooks/lock valid |
| MCP focused tests | `uv run --project host --locked --group dev pytest -q host/tests/test_server.py host/tests/test_server_observation.py host/tests/test_server_development.py host/tests/test_host_http_fake_adb.py` | Completed, **4 passed** |
| Host full gate | `python3 scripts/dev.py check` | Completed, **305 passed**; Ruff, formatting, strict mypy, Bandit, true-branch quality policy passed |
| Clean package installation | `bash scripts/check-host-package.sh` | Completed, success: wheel/sdist, separate venv, CLI doctor, import check |
| In-process MCP catalog & synthetic calls | Script run with locked `uv run ... python` and no actual device | Completed, 3 tools, 10 call examples, 0 resources/templates/prompts |
| GitHub host CI | Most recent observed passing Host run at `d85847fc` | Historical CI pass, **not** an exact-HEAD `f536b26c` CI claim; plan commit is docs-only |

Test output came from the MacBook command session run under the Wave 0 Worktree.
The package installation used a temporary isolated virtual environment.

## Observed ChatGPT-visible MCP contract (not yet a retention decision)

| Tool | Input shape advertised by FastMCP 4.1.0 | Output schema advertised | Annotations |
| --- | --- | --- | --- |
| `device_status` | Empty object | Permissive generic object | None |
| `adb_observe` | `device_id: string`, `probes: string[]` | Permissive generic object | None |
| `adb_develop` | `device_id: string`, `action: any object`, `dry_run: boolean=false` | Permissive generic object | None |

The tool names, returned status codes and current envelopes are observable.
They do not prove the current metadata is the desired contract. The canonical
application schemas are `contracts/device-status.v1.schema.json`,
`contracts/adb-observation.v1.schema.json`,
`contracts/adb-development-action.v1.schema.json`, and
`contracts/adb-development.v1.schema.json`; the published FastMCP schemas are
currently less specific. This is a boundary-design issue, not permission to
change behavior without contract approval.

### Synthetic call characterization

- `device_status`: MCP `is_error=false`; response has version, runtime,
  capabilities, host/ADB, devices and errors (not a `status` field).
- `adb_observe` valid `selinux`: MCP success and application status `ok`.
  Unknown probe: `is_error=false`, status `error`, `INVALID_PROBE`.
  Bad serial: application `INVALID_DEVICE_ID`.
  Wrong input type (`probes` string): FastMCP returns `is_error=true`.
- `adb_develop` valid package-details: application status `ok`.
  Disallowed `instrument_test`: `is_error=false`, status `error`,
  `MUTATION_DISABLED`; same action with `dry_run=true`: status `planned`.
  Unknown action: application `UNKNOWN_OPERATION`.
- **OBSERVED_ONLY / possible accidental behavior:** `dry_run="true"` (a
  string) is coerced to true by the FastMCP input layer and yields `planned`.
  Wave 1 contract work must decide whether to preserve or intentionally break
  this conversion before any strict-input change.
- The fake operation runner was called once for the one permitted
  package-details action; never for install/instrument.

## Behavior vs requirements vs proposals

| Classification | Evidence or source | Decision for next wave |
| --- | --- | --- |
| REQUIRED: explicit authorized target; no implicit selection | `docs/security.md`, code guard, contracts | Preserve and protect with negative tests |
| REQUIRED: no default APK/install/instrument/root or public HTTP listener | `docs/security.md`, `docs/host-merge-gates.md` | Preserve; no authorization side effects |
| REQUIRED: exact three public names in this refactor | Approved refactor plan, observed tools/list | Protect Tool catalog count/names |
| REQUIRED: versioned application JSON envelopes | Existing JSON Schema and Host contract tests | Preserve unless separately approved versioned change |
| OBSERVED_ONLY: app errors may be `is_error=false` | Synthetic calls above | P2 decides expected two-level error semantics |
| OBSERVED_ONLY: permissive advertised output objects | Synthetic tools/list | P1 schema study and P2 decision before change |
| ACCIDENTAL/UNRESOLVED: `dry_run` coerces string booleans | Synthetic call above | Do not freeze/alter without P2 decision |
| PROPOSED: mask unexpected exception details | Previous FastMCP review, `mask_error_details` supported by v4.1.0 | P1 must verify log/client boundary; E1 requires approved tests |
| PROPOSED: precise schemas and annotations | Existing detailed contracts, FastMCP API | Decide authoritative schema strategy and hint truthfulness |
| UNKNOWN: cancellation equivalence of sync-tool dispatch | No Wave 0 concurrent/cancel experiment | P1 investigation; do not swap `asyncio.to_thread` blindly |

## Architecture and state boundary

The only production module importing `fastmcp` is
`host/src/android_mcp_host/server.py`. `create_server()` constructs one
FastMCP instance and closures over `AdbClient`, `ProbeService`, and
`OperationService`. CLI (`cli.py`) uses shared status/service functions rather
than invoking MCP Tool objects. This thin separation is **worth retaining**.
`OperationService` has process-local per-device `threading.Lock` objects;
the optional security coordinator uses SQLite-backed state, external signed
approvals and a future Native lease port. Neither a FastMCP session nor a
process-local lock establishes cross-Host or Host/Native mutation authority.
The default server does not inject the secure mutation coordinator.

## Wave 1 / Wave 2 handoff gates

- P1: check pinned FastMCP 4.1.0 framework masking, schema/validation,
  annotations, sync dispatch and cancellation in isolated disposable tests.
- P2: write public contract and expected application-vs-MCP error decisions;
  choose supported vs accidental input coercions, side effects and hints.
- P3: add public-surface characterization tests without touching `server.py`;
  do not treat all observations as contract requirements.
- After parallel work, integrator reviews conflicts, accepts the relevant
  S1-S5 decisions and only then starts Wave 2 E1/M1/V1 in separate Worktrees.
  Any changes to `server.py` have one integrator/owner at a time.

**Remaining limits:** This captures a synthetic MCP client, macOS tests and
build, not ChatGPT ordinary Chat/Work interoperability, an authenticated
remote MCP endpoint, real-device execution or official MCP conformance.
