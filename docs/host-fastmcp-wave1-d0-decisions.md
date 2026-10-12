# Host FastMCP refactor — Wave 1 D0 decisions and Wave 2 gates

**Date:** 2026-10-12, Australia/Sydney. **Owner:** ChatGPT Host integrator.
**Status:** Accepted *bounded* design decisions for Wave 2; future external
contract changes and privileged deployment are **not approved** by this file.

## Evidence and provenance

- B0: `docs/host-fastmcp-refactor-baseline.md`,
  `docs/host-fastmcp-baseline-tools.json`, merged PR #18, SHA `f4ebf10e`.
- P3: `host/tests/test_fastmcp_public_contract.py`, merged PR #19,
  SHA `4af1938d` (11 regression tests; entire Host suite 316 on integration).
- P2: `docs/host-fastmcp-public-contract-policy.md`, PR #20 merged at
  `12991bd7`; explicit 73-call FastMCP comparison, schema checks and policy
  recommendations; distinguishes REQUIRED / OBSERVED_ONLY / ACCIDENTAL.
- P1: `docs/host-fastmcp-4-1-compatibility.md`, independent local agent's
  POC report, PR #21 merged to main at `a3fa29a62eff855babcb73f49f6f100bb1d09485`.
  The actual P1 evidence was independently inspected before these decisions. P1 studied FastMCP 4.1.0,
  MCP SDK 2.3.0, Pydantic 2.14.1 across Python 3.11–3.14 on macOS.
- The full original plan is
  `docs/superpowers/plans/2026-10-12-host-fastmcp-progressive-refactor.md`.

## S1 — Pinned compatibility and owned responsibilities

Keep standalone FastMCP 4.1.0 / locked MCP SDK 2.3.0, no dependency upgrade
within these refactor slices. FastMCP owns tool registration, transport,
serialization/metadata, and *client-facing* unexpected-error masking;
application owns typed denials, Android device selection, ADB allowlists,
process deadlines, audit and (future) Host/Native lease fencing.

FastMCP `mask_error_details=True` prevents **unhandled exception content**
from reaching MCP clients, but not its server logs. Deliberate `ToolError`
and validation errors may still contain user-visible data. Therefore E1 is
eligible only with synthetic canary and ordinary-behavior tests; future log
redaction is a separate safety work item, not falsely covered by E1.

FastMCP accepts explicit JSON output schemas including `oneOf`, `if/then`,
`$ref`, but the installed implementation does not validate generated results
on the server; a conforming MCP client may reject invalid responses. The
runtime tool input JSON is derived from Pydantic and global strict validation
does not prove nested free-form `action` correctness. Neither tool session
cancellation nor a framework timeout replaces the Host bounded subprocess
cleanup and process-group deadline.

## S2 — Public Tool and error contract decisions

1. **Frozen for this refactor:** exactly three public names
   (`device_status`, `adb_observe`, `adb_develop`), localhost-only Host,
   explicit device ID and ADB readiness gates, typed v1 application envelopes,
   default-denied actual APK install/instrumentation, no arbitrary shell/root,
   bounded read-only output and deterministic failure codes.
2. **Expected domain denials:** return a normal MCP result (`is_error=false`)
   with an application status/errors array. Preserve it across E1/I1; this is
   the target client-facing behavior. Unexpected exception/argument type error
   is an MCP error. Do not switch domain denials to `ToolError` in a refactor.
3. **Validation boundary:** advertise domain enum/range/shape accurately when
   supported, but retain domain validation in the application to preserve
   `INVALID_PROBE`, `UNKNOWN_OPERATION`, `INVALID_DEVICE_ID`, etc., until an
   independently reviewed wire contract change. FastMCP must still reject
   fundamentally malformed framework-level types. This selects P2 D-ERR-2
   option A (advertise and delegate domain enforcement).
4. **`dry_run` coercion:** existing string-booleans becoming booleans is an
   accidental/observed behavior, not a new accepted contract. Do not toggle
   server-wide `strict_input_validation` in this wave; no production mutation
   is available. Rejection of legacy inputs is a separate compatibility
   decision, and strict parsing is a precondition before any future mutation.
5. **Tool hints and metadata:** no annotations are added in E1/M1/V1.
   Whether `device_status`/`adb_observe` qualify as read-only despite ADB
   daemon startup and whether mixed `adb_develop` should be marked as
   destructive are deferred to I3. Test descriptions/current metadata now,
   but do not freeze incidental auto titles or permissive schemas.
6. **No change** to versioned envelope keys, `schema_version`, mutation
   behavior, authorization, Tool count or runtime transport in Wave 2.
   Any incompatible external behavior requires separate approval and
   coordinated v2/migration work with Native.

## S3 — Boundary-model and packaging architecture

The **four versioned JSON Schema files under `contracts/` are canonical**.
For FastMCP's public output-schema surface, prefer exact canonical schema
JSON rather than generate another independent Pydantic JSON schema.

The clean wheel currently contains zero `contracts/*.json` files. Wave 2 M1
may add *packaged copies* under an application-owned private resource
namespace, with a deterministic test that checks their parsed JSON equals
the matching canonical source on every Host CI run. Packaged copies must be
shipped in the wheel and accessible through `importlib.resources`; no source
checkout-relative path may be required at runtime. This is a distribution
artifact, not a second source of truth: fail CI on any copy drift.

Wave 2 M1 must not edit `server.py`. It should supply a small boundary loader,
e.g. `host/src/android_mcp_host/mcp_boundary.py` with a typed helper
`get_output_schema(tool_name: str) -> dict[str, object]` that selects one of
the three approved canonical output files, defensive-copies the mutable JSON,
and raises for an unknown name. The eventual `server.py` integrator owns the
actual schema advertising change. Package data/build metadata is a shared
file; M1 may propose it, but only the integration owner edits
`host/pyproject.toml`. The minimum change must pass a clean-wheel test.

The published `adb_develop` action **input** should eventually expose the
canonical v1 discriminated actions without turning current typed application
denials into framework errors. The P1 study found that lax Pydantic union
validation can drift; preserve the current runtime until an I1c POC establishes
schema fidelity. Do not automatically add a new runtime dependency.

## S4 — Verification responsibilities

- E1 must have a red/green synthetic exception-canary test, preserve typed
  application `MUTATION_DISABLED`, valid ADB observation and CLI doctor.
- M1 must prove three resource schema copies exactly match canonical JSON,
  unknown tool rejection, defensive copying, and clean wheel packaging.
- V1 must test only metadata already *accepted* (three names, descriptions,
  required input fields), not demand unintegrated annotations/titles/schemas.
- Actual tools/list and tools/call in process and loopback HTTP remain
  mandatory for public behavior changes; any future real hardware acceptance
  must be separately authorized and remain read-only.
- For any code slice, run targeted RED/green tests, `python3 scripts/dev.py
  check`, complete applicable pre-commit/pre-push gates and exact-head GitHub
  CI across supported macOS/Linux/Python versions; verify post-merge `main`.

## S5 — File ownership, integration and rollback

| Wave 2 slice | Exclusive writable scope | Dependencies | Exit gate |
| --- | --- | --- | --- |
| E1 (first executable change) | `server.py`, new `test_fastmcp_error_masking.py` | S1 error masking, S2 existing denials | tests red→green, no canary, full suite and PR |
| M1 (independent boundary) | `mcp_boundary.py`, packaged schema resources, new `test_mcp_boundary.py` | S3 canonical source decision | exact schema equality and clean wheel |
| V1 (independent metadata) | new `test_fastmcp_metadata_policy.py`, Host-specific metadata review document | S2 hints deferred | current contract remains green |

Only the Host integrator may edit `server.py` and packaging/shared config;
if M1 requires packaging metadata updates, the integrator applies them
separately. Wave 2 branches start from the same merged Wave 1 baseline,
have disjoint writers, and are merged one small independently reversible PR
at a time. The user has expressly directed **ChatGPT to implement remaining
work itself without launching additional Claude Code/Codex agents**.

## Deferred and risk register

- **Not approved:** external listener/auth, persistent MCP tasks, Native
  device actions, actual APK mutation, Root, broader Tool catalog.
- **I2 strict input:** deferred until explicit compatibility/value decision.
- **I3 annotations and presentation text:** conditional; readOnlyHint
  depends on observed external side effects and mixed action semantics.
- **I4 thread rewrite:** skip by default — P1 found no correctness or resource
  benefit, and cancellation can leave work running. Keep Host process deadlines.
- **P2 security follow-ups:** device/action reflection and APK path-existence
  oracle require their own security analysis; not to be buried in E1/M1/V1.
- **Review independence:** no agent is being used for future implementation;
  all evidence must be checked against real file diffs, tests and CI, and
  external independent approval is still required for privilege-enabling work.

**Next action:** verify the full Wave 1 merged base, then run
E1, M1 and V1 directly as independently testable Host slices. One failed
slice cannot be papered over by another passing one.
