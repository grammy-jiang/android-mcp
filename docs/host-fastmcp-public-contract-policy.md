# Host FastMCP public Tool contract policy (Wave 1 / P2 / S2)

**Status:** PROPOSED DECISION RECORD for D0. This document is evidence and a
recommendation set. It does **not** authorize any runtime, schema, annotation,
validation or error-semantics change, and it approves nothing on the
integrator's behalf. Where a choice has several reasonable options, a bounded
recommendation is given with alternatives and compatibility risk.

**Captured:** 2026-10-12. **Base:** `f4ebf10e3c0ad73d2b3dfbcce84dac21a7516b1f`
(`origin/main` after PR #18, Wave 0 baseline). **Branch:**
`feature/host-fastmcp-wave1-p2`. **Runtime used for evidence:** macOS ARM64,
locked Python 3.13.16, standalone FastMCP 4.1.0, MCP Python SDK 2.3.0,
Pydantic 2.14.1. Only injected fake ADB objects were used; no real `adb`
process, device, network listener or mutation was exercised. Findings on
other platforms (Linux, other Python versions) are **not** established here.

**Scope:** exactly the three public Tools `device_status`, `adb_observe` and
`adb_develop`. The catalog stays exactly three. New Tools, a Tool split,
mutation enablement, remote transport, authentication and background tasks are
out of scope and are not proposed here.

## 1. How to read this document

Classification labels follow the Wave 0 baseline and the refactor plan.

| Label | Meaning | May a refactor change it? |
| --- | --- | --- |
| REQUIRED | Backed by a written policy, a canonical contract, a security rule or an existing contract test | Only through an explicit, versioned, separately approved contract PR |
| OBSERVED_ONLY | Seen on the wire today but no policy, contract or test requires it | Preserve by default; D0 may promote it to REQUIRED or release it |
| ACCIDENTAL | Side effect of a framework default, code ordering or omission that nobody chose | Do not freeze blindly; D0 decides fix, defer or document |
| PROPOSED | Not true today; a recommended target state | Only after D0 acceptance and the stated test gate |
| UNKNOWN | Not established by this evidence | Needs a named experiment before it is relied on |

Evidence IDs used below:

- **E-LIST:** `tools/list` captured through `fastmcp.Client` against
  `create_server()` with injected fakes (this session and
  `docs/host-fastmcp-baseline-tools.json`).
- **E-CALL:** 73 `tools/call` invocations with fake ADB, covering 53
  application envelopes and 20 framework-level errors (counts in section 9).
- **E-SCHEMA:** every application envelope from E-CALL validated with
  `jsonschema.Draft202012Validator` against the matching file in
  `contracts/`; `adb-development-action.v1` compared with the runtime action
  parser by differential test.
- **E-CODE:** read of `server.py`, `status.py`, `adb.py`, `probes.py`,
  `operations.py`, `command_plan.py`, `device_guard.py`, `command_runner.py`.
- **E-FW:** disposable FastMCP 4.1.0 experiments that never touch Host code
  (annotation fields, advertise-versus-enforce, `StrictBool`,
  `strict_input_validation`, `mask_error_details`, client-side output
  validation).
- **E-TEST:** `host/tests` focused run, 15 passed (section 9).

## 2. Decision summary for D0

Each row is a proposal. "Default" is the recommended choice if D0 has no
stronger reason. Nothing below is accepted until D0 records it.

| ID | Topic | Recommended default | Main alternative | Compatibility or security risk of the alternative |
| --- | --- | --- | --- | --- |
| D-CAT | Catalog | Freeze exactly `device_status`, `adb_observe`, `adb_develop`; protect names and count by test | None in this scope | A new or split Tool needs its own contract decision |
| D-ERR-1 | Application outcomes versus `is_error` | Keep every deliberate application outcome, including `status="error"`, as a normal result with `is_error=false` and the canonical envelope | Raise `ToolError` for denials (`is_error=true`) | Loses typed `errors[].code` and structured content; breaks callers that read `status`; SDK clients skip output validation for error results |
| D-ERR-2 | Where domain limits are enforced once schemas are published | Advertise limits in `tools/list` but keep enforcement in the application, so domain denials stay typed envelopes | Enforce at the FastMCP boundary (`Literal`, `min_length`) | Unknown probe, bad count, bad serial become `is_error=true` text-only framework errors: an external contract change |
| D-ERR-3 | Uncaught exceptions | Adopt FastMCP error masking (E1) and treat server-log hygiene as a separate item | Leave as is | Exception text reaches the client today (section 4.1) |
| D-SCH-1 | Output schemas | Publish the canonical v1 output schemas, verified by tests against `contracts/` | Keep the permissive `{"type":"object","additionalProperties":true}` | Low breaking risk now; but nothing then protects consumers from drift |
| D-SCH-2 | Input schemas | `action` follows `adb-development-action.v1`; `device_id`, `probes` and `dry_run` constraints derive from Host code and are labelled PROPOSED because no canonical input schema exists | Leave `action` as any object | The model gets no typed guidance about the four action variants |
| D-DRY | `dry_run="true"` coercion | Defer. Do not document it as supported, do not assert it in tests, do not change it now. Require strict boolean parsing before any mutating path can execute | Narrow `StrictBool` on `dry_run` now | Rejects clients that stringify booleans; error shape is a framework error |
| D-ANN | Annotations | `device_status` and `adb_observe`: `readOnlyHint=true`, `openWorldHint=false`, with the daemon side effect disclosed in the description. `adb_develop`: `readOnlyHint=false`, `destructiveHint=true`, `idempotentHint=false`, `openWorldHint=false` | Conservative non-read-only hints on all three, or no annotations | Extra approval prompts versus an overclaim; see section 4.4 |
| D-META | Titles, descriptions, server instructions | Replace auto-generated titles and inaccurate wording (section 5) | Keep as is | `adb_develop` description promises an APK install preview that the default server never produces |
| D-VER | Wire version | No `schema_version` bump for the recommended set | n/a | Any envelope field change or `status` enum change requires a bump |
| D-SEC | Security observations found during inspection | Route to separate, independently reviewed security fixes (section 4.7) | Fix inside the schema PRs | Bundles behavior changes with metadata work |

## 3. Cross-cutting facts that apply to all three Tools

### 3.1 Two levels of "error" must not be confused

Evidence: E-CALL, E-FW, `mcp/client/session.py` in the locked SDK.

| Level | Trigger | MCP `is_error` | Body | Handler ran | Stable contract? |
| --- | --- | --- | --- | --- | --- |
| Application success | Request valid and completed | false | Canonical envelope, `status` `ok` or `planned` where the Tool has one | Yes | REQUIRED (canonical schemas) |
| Application partial | Output cap, timeout after some data, unconfirmed result | false | Canonical envelope, `status="partial"`, typed `errors[]` | Yes | REQUIRED (canonical schemas) |
| Application denial or failure | Bad serial, unknown probe or action, device absent or unauthorized, ADB missing, `MUTATION_DISABLED`, timeouts, command failure | false | Canonical envelope, `status="error"`, at least one typed `errors[]` entry | Yes (often before any ADB call) | Envelope REQUIRED; `is_error=false` is OBSERVED_ONLY, recommended for promotion (D-ERR-1) |
| Framework validation error | Wrong JSON type, missing or unknown argument name, uninterpretable `dry_run` | true | Text only (Pydantic message, no `structuredContent`) | **No** | Only "`is_error=true` and the handler did not run" is stable; the text is not |
| Framework uncaught error | Unexpected exception in a handler | true | Text `Error calling tool '<name>': <exception text>` | Yes, then raised | Exception text leak is ACCIDENTAL (section 3.1.2) |
| Protocol or transport error | Unknown Tool name, malformed JSON-RPC, HTTP failure | n/a | JSON-RPC or HTTP error | No | Owned by FastMCP and the SDK; out of scope |

Rules proposed for D0:

1. A caller must read `structuredContent.status` (or `errors` for
   `device_status`) to learn whether the *operation* succeeded. `is_error=false`
   means only "the Tool ran and returned its documented envelope".
2. `is_error=true` means "the request never reached application logic or the
   Host failed unexpectedly". Callers fix the request or report a Host bug.
   They must not treat `is_error=true` as a typed denial.
3. A refactor must not silently move an outcome from one level to the other.
   Every such move is an external contract change.

#### 3.1.1 Why `is_error=false` for application denials should be promoted

- The canonical schemas define `status="error"` with required typed errors
  (`adb-observation.v1`, `adb-development.v1`). Those schemas are only
  meaningful if denials are delivered as structured results.
- The pinned SDK client validates `structuredContent` against the advertised
  `outputSchema` **only when `is_error` is false**
  (`mcp/client/session.py`, `if ... and not result.is_error`). A denial
  delivered as `is_error=true` would carry no structured content at all
  (observed for every framework error in E-CALL).
- A hybrid result (`is_error=true` plus a structured envelope) is UNKNOWN for
  FastMCP 4.1.0 and belongs to P1. It is not proposed here.

#### 3.1.2 Uncaught exceptions

Observed (E-CALL, E-FW): with the current `FastMCP("android-mcp-host", ...)`
constructor, an injected `RuntimeError("synthetic-secret-CANARY-123")` is
returned to the client verbatim, for all three Tools. The server stderr log also
contains the full traceback with the same text. With `mask_error_details=True`
(experiment on a throwaway server) the client text became only
`Error calling tool 't'`, while validation errors were still unmasked and still
echoed `input_value`. Classification: client-visible exception text is
ACCIDENTAL; masking is PROPOSED (E1); log hygiene is a separate, still UNKNOWN
assessment, because framework masking does not touch server logs.

### 3.2 Authorized device scope (applies to `adb_observe` and `adb_develop`)

"Authorized" in the current Host means exactly the following; nothing else
exists in the default composition (E-CODE: `device_guard.py`, `probes.py`,
`operations.py`).

1. The caller supplies an explicit `device_id`. There is no default or "first"
   device. (REQUIRED: `docs/security.md`, `AGENTS.md`.)
2. The serial matches `[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}` (ASCII only).
3. A fresh `adb version` plus `adb devices -l` report shows the serial exactly
   once, with state `device` (ADB-level authorization granted on the device).
   States `unauthorized`, `offline` and the others yield `DEVICE_NOT_READY`.
4. Every subsequent ADB argv is `adb -s <device_id> ...` built from a fixed
   table. There is no raw shell, no root, no `su`, no user-supplied remote
   argument.

There is **no** Host-side operator allowlist of serials and **no** MCP caller
authentication in the default composition (loopback-only listener, no
`AuthProvider`). Any caller who can reach `127.0.0.1:8765` can name any
ADB-authorized attached device. This is a documented boundary, not a defect
found here, but D0 should record that "authorized" currently means
"ADB-authorized and attached", not "operator-approved". An operator allowlist
or caller authentication is a separate security project.

`device_status` needs no `device_id` because it is the discovery step. It lists
every serial the Host's ADB server reports, including unauthorized and offline
entries.

### 3.3 Side effects and resource bounds

| Effect | `device_status` | `adb_observe` | `adb_develop` |
| --- | --- | --- | --- |
| Spawns host subprocesses | `adb version`, `adb devices -l` | Same discovery, then fixed `adb -s <id> shell ...` commands (up to 19 for eight probes; a call is limited to 8 probes) | Same discovery, then at most one allowlisted command for non-preview read-only actions; none for `dry_run=true` |
| May start the ADB background server | Yes (`adb devices` starts it if absent; source comment in `adb.py` says so) | Yes | Yes, even for `dry_run=true` and even for `MUTATION_DISABLED` (observed: discovery ran once per call) |
| Changes device state | No | No (fixed read forms: `getprop`, `dumpsys battery`, `wm size`, `wm density`, `df -k /data`, `getenforce`, `id`, `uname -r`, `pm list packages -3`) | No in the default composition (mutating actions refused) |
| Changes host state beyond the ADB server | No | No | No (a per-device in-process lock only) |
| First-connect device prompt | May appear if ADB has not yet been authorized for this host (ADB behavior, not verified here; no real device used) | Same | Same |
| Opens a network listener from Host code | No | No | No |
| Sensitive output | Serials, device properties, `adb` path, Python and OS | Model, build, packages, battery and more | Logcat and `dumpsys package` can hold app data |

Bounds: each ADB subprocess has a 64 KiB capture cap and a process-group kill
on timeout (`command_runner.py`). Discovery and each probe command time out at
5 s (constructor defaults); read-only develop actions at 15 s; the (disabled)
mutating actions at 120 s. There is **no overall per-call wall-clock cap** and
no FastMCP request timeout configured. Worst-case `adb_observe` with the
eight largest probes is about 10 s of discovery plus 19 commands at 5 s each. Whether a
client disconnect or cancellation stops an in-flight child process is UNKNOWN
(P1 owns the experiment; HTTP cancellation must not be assumed to reach the
subprocess).

### 3.4 Retry and idempotency (shared model)

- No Tool accepts an idempotency key. The planned key for future mutations
  (`docs/contracts.md`) is not implemented.
- All three Tools are safe to repeat in the default composition: no device or
  host state beyond the ADB server is changed. Results are time-varying.
- A retry after a framework validation error is meaningful only after changing
  the arguments. A retry after `ADB_TIMEOUT`, `PROBE_TIMEOUT` or
  `OPERATION_TIMEOUT` is safe for the read-only paths. `DEVICE_BUSY` is safe
  to retry later.
- For any **future** mutating action, a timeout, `partial` or unconfirmed
  result (`APK_RESULT_UNCONFIRMED`, `TEST_RESULT_UNCONFIRMED`) means the final
  state is unknown. Callers must re-observe before retrying, and automatic
  retry must not be enabled. This is a gating requirement for the separate
  mutation project, not a current behavior.

### 3.5 What FastMCP can and cannot publish (E-FW)

- `FastMCP.tool` in 4.1.0 accepts `title`, `description`, `annotations`,
  `output_schema`, `meta`, `tags`, `timeout` and `run_in_thread`. It has **no**
  separate `input_schema` parameter: the input schema is derived from the
  function signature, so any constraint expressed with types also becomes an
  enforced validator.
- Constraints can be *advertised without enforcement*: for example
  `Field(json_schema_extra={"enum": [...], "minItems": 1, "maxItems": 8,
  "uniqueItems": true})` produced the intended `tools/list` schema while an
  unknown probe and an empty list still reached the handler (`is_error=false`).
- Constraints expressed as `Literal[...]` or `min_length` are enforced and
  turn an unknown probe into `is_error=true` text (`literal_error`).
- `StrictBool` on a single parameter leaves the advertised schema as
  `{"type":"boolean"}` and rejects `"true"`. `strict_input_validation=True`
  rejects it too but applies to every parameter of every Tool.
- A non-conforming structured result (extra property, wrong enum) was returned
  by the server as a normal result, and the **SDK client** then raised
  `RuntimeError: Invalid structured content`. Publishing the canonical output
  schemas therefore turns any future envelope drift into a hard failure for
  validating clients, which is why conformance tests are mandatory (section 8).

## 4. Policy decisions in detail

### 4.1 Differences between the advertised schemas and the canonical files

Evidence: E-LIST against `contracts/*.v1.schema.json` (E-SCHEMA).

| Surface | Advertised by FastMCP 4.1.0 today | Canonical on disk | Verdict |
| --- | --- | --- | --- |
| `device_status` output | `{"type":"object","additionalProperties":true}` | `device-status.v1`: five required fields, `additionalProperties:false`, nested `host`, `adb`, `devices`, diagnostics | Advertised is a non-binding superset. All 3 observed envelopes (devices present, `ADB_NOT_FOUND`, `ADB_TIMEOUT`) validate canonically |
| `adb_observe` output | Same permissive object | `adb-observation.v1`: `status` in `ok`, `partial`, `error`; probe enum; `truncated_fields`; conditional rules | All 14 observed envelopes validate canonically |
| `adb_develop` output | Same permissive object | `adb-development.v1`: statuses `ok`, `planned`, `partial`, `error`; `result` null or object; command at most 12 entries; conditional rules | All 36 observed envelopes validate canonically, including the 25,000-character display cap and truncated capture |
| `adb_develop.action` input | `{"type":"object","additionalProperties":true}` | `adb-development-action.v1`: `oneOf` four closed variants | Advertised is far wider than both canonical and runtime; see differential below |
| `adb_observe.device_id`, `probes` input | `string`; array of `string` | **No canonical input schema exists.** The nine-name enum exists only inside the output schema (`results[].probe`) and in `PROBES`; the 1 to 8 count and uniqueness exist only in code | Input limits are REQUIRED behavior (code and tests) but their *published schema form* is PROPOSED |
| `dry_run` input | `boolean`, default `false` | No canonical input schema | Advertised type is narrower than what is accepted (section 4.5) |
| `device_id` grammar | plain `string` | Not in contracts; regex in `adb.py` | PROPOSED to advertise |

**Do not assume the current permissive schemas are desired** and do not assume
the canonical schemas are complete: they describe outputs and the `action`
object only.

#### Differential: canonical action schema versus the runtime parser

92 non-install action dictionaries (every variant, boundary lengths, wrong
types, extra keys, trailing newlines) were run through
`prepare_action` and `adb-development-action.v1`. Result: 5 disagreements, all
explained, none making the runtime *looser* than the schema.

| Case | Schema | Runtime | Explanation | Proposed handling |
| --- | --- | --- | --- | --- |
| `logcat_snapshot` with `lines: 10.0` | valid (integer-valued float) | `INVALID_ARGUMENTS` | Runtime requires Python `int` | Runtime stricter. Document; no change |
| Four identifiers ending in `\n` (package or runner) | valid under Python `re` | rejected | Python `$` matches before a final newline; the runtime uses `\Z`. ECMA-262 `$` would reject, so this is a validator-library artifact | Any Python-side schema check must not be treated as the enforcement; keep the runtime check |

`install_apk` is deliberately outside the pure-schema differential because the
runtime adds filesystem, root and signature checks: schema-valid actions are
refused with `INVALID_APK_PATH` (path absent) or `APK_NOT_ALLOWED` (path present)
in the default composition, where `allowed_apk_roots` is empty (section 5.3).

Two contract gaps for the contracts owner (not for P2 to edit): the runtime
defaults `lines=200`, `replace=true`, `allow_test=false` are absent from the
canonical schemas. Adding `default` annotations does not change validation but
is a shared-contract edit that needs Native coordination.

### 4.2 Where limits live (D-ERR-2)

Today, a malformed *type* is a framework error and a malformed *value* is an
application denial:

| Input | Today | Level |
| --- | --- | --- |
| `probes: "boot"` (string) | `is_error=true`, `list_type` | Framework |
| `probes: [1]` | `is_error=true`, `string_type` | Framework |
| `probes: ["bogus"]` | `status=error`, `INVALID_PROBE`, `is_error=false` | Application |
| `probes: []`, nine names, duplicates | `status=error`, `INVALID_PROBES`, `is_error=false` | Application |
| `device_id: "BAD SERIAL"` | `status=error`, `INVALID_DEVICE_ID`, `is_error=false` | Application |
| `action: "logcat_snapshot"`, a list, `null` | `is_error=true`, `dict_type` | Framework |
| `action: {}` or `{"type": 1}` or unknown `type` | `INVALID_ACTION` or `UNKNOWN_OPERATION`, `is_error=false` | Application |
| `action` with extra key, bad `lines`, bad package | `INVALID_ARGUMENTS`, `INVALID_PACKAGE`, `INVALID_COMPONENT` | Application |
| Unknown top-level argument such as `approved: true` | `is_error=true`, `unexpected_keyword_argument` | Framework |

Recommendation (D-ERR-2, option A): keep this split. Publish value constraints
(enum, count, uniqueness, serial pattern, action variants) in `tools/list` as
advertised metadata, using the non-enforcing mechanism verified in E-FW, and
keep enforcement in the application. Compatibility: no response changes;
clients that pre-validate get earlier feedback. Risk: advertised metadata can
drift from enforcement, so a differential test between the advertised schema and
the runtime accept/reject set is mandatory.

Alternative B: enforce at the boundary (`Literal`, count limits). More idiomatic
FastMCP, but every value-level denial above becomes `is_error=true` text with no
typed code and no `structuredContent`. That is an external contract change that
needs D0 approval, updated characterization tests and a release note. The
refactor plan's I1b wording ("enumerated nine probes, 1-8 selection, duplicate
rejection") reads like B while its Section A review focus reads like A; D0 must
resolve that tension explicitly.

Alternative C: keep permissive schemas. No risk, no benefit.

### 4.3 Output cap, partial and timeout semantics

| Condition | Tool | Status | Code | Result content |
| --- | --- | --- | --- | --- |
| One command's output over its per-command or remaining total budget (cut, not failed) | `adb_observe` | `ok` | none | field present, name added to `truncated_fields` |
| Total 25,000-character budget exhausted before next command | `adb_observe` | `partial` (`error` if no probe finished) | `OUTPUT_LIMIT` | completed probes only |
| Capture exceeded 64 KiB | `adb_observe` | `partial` or `error` | `OUTPUT_LIMIT` | completed probes only |
| Command timed out or could not start or exited nonzero | `adb_observe` | `partial` or `error` | `PROBE_TIMEOUT`, `PROBE_EXEC_FAILED`, `PROBE_FAILED` | completed probes only; failing probe contributes nothing, even if some of its commands succeeded; later probes are not attempted |
| Capture exceeded 64 KiB | `adb_develop` | `partial` | `OUTPUT_LIMIT` | `result` present, `truncated=true` |
| Output over 25,000 characters after control-character stripping | `adb_develop` | `partial` | `OUTPUT_LIMIT` | `stdout` cut to 25,000, `truncated=true` |
| Action timed out | `adb_develop` | `error` | `OPERATION_TIMEOUT` | `result: null` |
| Process could not start | `adb_develop` | `error` | `OPERATION_EXEC_FAILED` | `result: null` |
| ADB exited nonzero | `adb_develop` | `error` | `ADB_OPERATION_FAILED` | `result` present with `exit_code` and `stdout` (stderr is never returned) |
| Discovery failed or timed out | all | `device_status`: no `status`, populated `errors`; others: `error` | `ADB_NOT_FOUND`, `ADB_TIMEOUT`, `ADB_EXEC_FAILED`, `ADB_OUTPUT_LIMIT`, `ADB_VERSION_FAILED`, `ADB_LIST_FAILED` | none |

Rules: a `partial` result is never a success; callers must read `errors` and,
for `adb_observe`, `truncated_fields`. `ok` with non-empty `truncated_fields`
is valid and means "complete but shortened"; descriptions must say so.
Probe and command stderr text, exception text and ADB stderr are never echoed
in application messages (verified with synthetic canaries: none reached any
envelope). These properties are REQUIRED (`docs/security.md`, section on bounded
captures).

### 4.4 Annotations (D-ANN)

The MCP annotation fields are `title`, `readOnlyHint`, `destructiveHint`,
`idempotentHint` and `openWorldHint`; the SDK states they are **hints, not
guarantees**, and clients must not use them for security decisions. Per the
MCP specification (not re-verified in this session), `destructiveHint` and
`idempotentHint` are meaningful only when `readOnlyHint` is false. How ChatGPT or any other client reacts to these hints
(for example approval prompts) is UNKNOWN here and belongs to V1. Annotations
never replace Host-side device authorization and must never be cited as
authorization.

Facts that drive the choice:

- Discovery may start the ADB server (a host process and loopback listener of
  ADB's own). Nothing user-visible or device-side changes, and the effect is
  idempotent, but it is not literally "no effect on the environment".
- `adb_observe` runs commands on the device but only fixed read forms.
- `adb_develop` accepts four action types. Two (`instrument_test`,
  `install_apk`) are mutating in the contract and are refused only because no
  trusted coordinator is injected. A future injected coordinator changes
  behavior without changing the registered Tool.

| Tool | Recommended hints | Rationale | Alternative | Risk of the alternative |
| --- | --- | --- | --- | --- |
| `device_status` | `readOnlyHint=true`, `openWorldHint=false`; description discloses the ADB server start | No device or user data changes; ADB server start is an incidental, idempotent infrastructure cache | `readOnlyHint=false`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=false` (strict reading of "modifies environment") | Safest literal truth, but clients that gate non-read-only Tools will prompt for a status check |
| `adb_observe` | Same as `device_status` | Fixed read-only device commands plus the same discovery | Same strict alternative | Same |
| `adb_develop` | `readOnlyHint=false`, `destructiveHint=true`, `idempotentHint=false`, `openWorldHint=false` | Schema admits mutating actions; hints are per Tool, not per action; the plan forbids labelling it read-only just because mutation is currently disabled | `readOnlyHint=true` for the default composition | Becomes false the moment a coordinator is injected, and `dry_run` is a caller flag, not a Host guarantee; **not recommended** |
| `adb_develop` (variant) | `destructiveHint=false` | Default composition cannot destroy anything | n/a | Understates capability; **not recommended** unless the Tool is later split (separate decision) |

`openWorldHint=false` reflects that the Host talks only to a local ADB server and
USB-attached devices. It says nothing about the trustworthiness of text coming
back from a device (log lines and package data are untrusted data and may
contain prompt-injection text); the descriptions should say so.

A cost to record for D0: with the recommended `adb_develop` hints, harmless
`logcat_snapshot` and `package_details` calls share the approval treatment of
the mutating actions. Fixing that requires splitting the Tool, which is outside
this scope. A test must assert that no Tool is annotated `readOnlyHint=true`
unless every code path of that Tool, with any injectable collaborator, is
read-only.

### 4.5 The `dry_run="true"` string conversion (D-DRY)

Observed (E-CALL, E-FW, matches Wave 0): FastMCP's default lax Pydantic
validation converts string and integer values to boolean before the handler
runs.

| Sent as `dry_run` | Handler receives | Result |
| --- | --- | --- |
| `true`, `"true"`, `"TRUE"`, `"yes"`, `"on"`, `"1"`, `1` | `True` | `status="planned"` (preview) |
| `false`, `"false"`, `0` | `False` | real execution path |
| `2`, `"maybe"`, `null`, `[]` | not called | `is_error=true`, `bool_parsing` or `bool_type`, no ADB call |
| omitted | `False` | real execution path |

Related facts:

- The advertised schema says only `{"type":"boolean","default":false}`. The
  accepted set is a wider, Pydantic-version-dependent superset (the exact
  strings come from Pydantic, not from this project).
- No repository test or document asserts the string forms (grep of
  `host/tests` for string `dry_run` values found none).
- `OperationService.execute` has its own `INVALID_DRY_RUN` guard
  (`type(dry_run) is not bool`). It is **unreachable through MCP** because the
  framework has already coerced or rejected the value; it is reachable only by
  direct service calls and is useful defense in depth.
- Safety direction: today a coerced value can only select a *preview* or the
  *same* refused-or-read-only path the caller could have chosen with a real
  boolean, so there is no present privilege escalation. The concern is future:
  `dry_run` is a safety control for mutating actions, and a tolerant parser
  decides what counts as "not a preview".

Classification: the conversion is **ACCIDENTAL in origin** (nobody chose it; it
is a framework default) and **OBSERVED_ONLY in behavior**. It is not REQUIRED.

Options:

| Option | Effect | Compatibility risk |
| --- | --- | --- |
| 1. Defer, preserve, leave unspecified (**recommended**) | No change. Do not claim support, do not test acceptance. I1c typed models must keep a plain lax `bool` so the refactor does not change it by accident | None now. Future clients could come to depend on it; accepted set may shift with a Pydantic upgrade |
| 2. Narrow strict now (`StrictBool` on `dry_run` only) | `"true"`, `"yes"`, `1` become framework errors; advertised schema unchanged | Breaks any client that stringifies booleans; client population is UNKNOWN |
| 3. Global `strict_input_validation=True` | Rejects string booleans for every parameter of every Tool | Largest blast radius; plan says never flip the global default silently |
| 4. Declare the lax conversion supported | Documents Pydantic's table as contract | Couples the wire contract to a library table; **not recommended** |

Recommended gate (bounded): choose option 1 for the metadata and schema
slices; add a hard precondition to the future mutation project that `dry_run`
(and every other safety flag) be parsed strictly and tested for rejection of
non-boolean input *before* a coordinator can be injected. If D0 prefers option
2 now, it must ship alone as I2 with deterministic wire tests, since it is an
external contract change.

### 4.6 Annotations, titles and wording to correct (D-META)

- Titles are auto-generated today: `Device Status`, `Adb Observe`,
  `Adb Develop`. This is OBSERVED_ONLY/ACCIDENTAL and the product-visible title
  should be chosen deliberately (proposals in section 5).
- Server `instructions` begin with "Android host device tools are read-only."
  That is true of the default composition but conflicts with annotating
  `adb_develop` as non-read-only. Proposed wording: "In the default
  configuration the Host performs read-only operations only."
- The `adb_develop` description says "preview APK installation". In the default
  composition `install_apk` **never previews**: `OperationService` is created
  with no `allowed_apk_roots`, so every `install_apk` action is refused during
  planning (section 5.3). Accuracy fix is PROPOSED.
- Tool `meta` is `{"fastmcp": {"tags": []}}` (empty). Not a contract.

### 4.7 Security observations to route separately (not changed here)

These were found while characterizing, are not fixed here, and each would alter
observable behavior, so D0 should assign them to independently reviewed work.

1. **Host path existence oracle in `adb_develop`.** For `install_apk`, the APK
   path checks run before device discovery and need no attached or authorized
   device (observed with `device_id="NOT-ATTACHED"` and zero discovery calls).
   With no approved roots, an existing regular `.apk` file (or a symlink) yields
   `APK_NOT_ALLOWED`; a missing path or directory yields `INVALID_APK_PATH`.
   A caller can therefore test whether an absolute `.apk` path exists. Impact is
   low (loopback only, one bit per call, `.apk` suffix only) but it is a host
   filesystem disclosure reachable by a model. Remedy options: deny before any
   filesystem access when no root is configured, or return one uniform code.
   Either changes error codes and needs D0.
2. **Unbounded echo of caller strings.** On denial the response echoes
   `device_id` and, for `adb_develop`, the raw `action.type` string unvalidated
   and unbounded in length. The canonical schemas allow any string, so this is
   schema-valid but ACCIDENTAL. Consider bounding or blanking on invalid input.
3. **Framework validation messages echo `input_value`**, also with masking on.
   Whether that matters for the Host's sensitivity rules is a D0 call.
4. **Server log traceback** contains the exception text (section 3.1.2).

## 5. Per-Tool public contract inventory

Each inventory is implementer-ready: field values marked PROPOSED are the text
or schema an implementer may use once D0 accepts it. Values marked REQUIRED or
OBSERVED_ONLY already hold.

### 5.1 `device_status`

**User goal.** Find out whether the Host and Android Platform Tools (ADB) are
usable and which devices are attached, with their connection state, so the
caller can choose a `device_id` for the other Tools.

| Item | Value | Class |
| --- | --- | --- |
| Name | `device_status` | REQUIRED |
| Title | Observed `Device Status` (auto). Proposed `Android Device Status` | OBSERVED_ONLY; PROPOSED |
| Observed description | `Inspect host platform and ADB device states; never change a device.` | OBSERVED_ONLY |
| Proposed description | `Report the Host operating system, Android Platform Tools (ADB) availability and every ADB-visible Android device with its connection state. Use it first to obtain a device_id. It does not change any device, but the ADB lookup may start the local ADB background server. Problems are reported inside the result errors, not as a tool failure. Output includes device serials and the ADB path and is sensitive.` | PROPOSED |
| Input | Empty object, `additionalProperties:false`. Unknown arguments are framework errors | OBSERVED_ONLY; keep (PROPOSED to protect) |
| Output (canonical) | `contracts/device-status.v1.schema.json` | REQUIRED |
| Output (advertised) | `{"type":"object","additionalProperties":true}` | OBSERVED_ONLY; replace per D-SCH-1 |
| Device scope | None required. Lists all ADB-visible devices | REQUIRED |
| Annotations | Recommended `readOnlyHint=true`, `openWorldHint=false`; today none | PROPOSED |
| Application `status` field | None: this envelope has no `status`. Failure is `errors` plus `adb.error`, `adb.available`, `capabilities` | REQUIRED (canonical) |

Cases for this Tool:

| Case | `is_error` | Observable result | Class |
| --- | --- | --- | --- |
| Devices attached | false | `devices` populated, `errors` empty | REQUIRED |
| No device attached | false | `devices: []` is valid | REQUIRED (`docs/contracts.md`) |
| Device `unauthorized` or `offline` | false | Listed with that `state`; not an error | REQUIRED (state is data) |
| ADB not installed | false | `adb.available=false`, `errors[0].code="ADB_NOT_FOUND"` | REQUIRED (existing test) |
| ADB timeout, exec failure, output limit, version or list failure | false | `errors[0].code` is `ADB_TIMEOUT`, `ADB_EXEC_FAILED`, `ADB_OUTPUT_LIMIT`, `ADB_VERSION_FAILED` or `ADB_LIST_FAILED` | REQUIRED shape; per-code coverage PROPOSED |
| Unknown action or probe, wrong device | not applicable | The Tool has no such inputs | n/a |
| Unauthorized caller | not applicable | No caller authentication exists (loopback) | n/a |
| Extra argument | true | Pydantic `unexpected_keyword_argument`, handler not run | OBSERVED_ONLY |
| Unexpected exception | true | Text includes exception message today | ACCIDENTAL; masking PROPOSED |

**Idempotency and retry.** Idempotent read; safe to call repeatedly and
concurrently. Results change as devices connect. Retry after `ADB_TIMEOUT`
when ready. Each call performs two ADB subprocess invocations of at most 5 s
each.

**Protection tests required.** Exact discovery argv set is only `version` and
`devices -l` (this is what keeps `readOnlyHint=true` truthful).

### 5.2 `adb_observe`

**User goal.** Read a small, bounded set of diagnostics from one explicitly
selected, online, ADB-authorized device (identity, compatibility, boot,
battery, display, storage, SELinux mode, shell identity, third-party package
list) without any shell access.

| Item | Value | Class |
| --- | --- | --- |
| Name | `adb_observe` | REQUIRED |
| Title | Observed `Adb Observe` (auto). Proposed `Observe Android Device` | OBSERVED_ONLY/ACCIDENTAL; PROPOSED |
| Observed description | Lists the nine probes, says "Read-only", says the serial must match one online authorized device from `device_status` | OBSERVED_ONLY |
| Proposed description | `Read bounded diagnostics from ONE explicitly selected Android device using a fixed allowlist of read-only probes: identity, compatibility, boot, battery, display, storage, selinux, shell_identity, third_party_packages (1 to 8 unique names). device_id must be a serial from device_status whose state is "device". No arbitrary shell. Always check result.status: "ok", "partial" (earlier probes returned) or "error" with typed error codes; these are normal results, not tool failures. A field listed in truncated_fields was cut to fit the output budget. Results can contain sensitive device and installed-app information. The ADB lookup may start the local ADB background server.` | PROPOSED |
| Input (observed) | `device_id: string`, `probes: array of string`; both required | OBSERVED_ONLY |
| Input (limits, enforced by application) | `device_id` matches `^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$`; `probes` has 1 to 8 entries, each one of the nine names, no duplicates | REQUIRED (code and tests); schema form PROPOSED |
| Input (proposed advertised schema) | Same two fields with `pattern`/`maxLength` on `device_id`, and on `probes` `minItems:1`, `maxItems:8`, `uniqueItems:true`, `items.enum` of the nine names, published as non-enforcing metadata (D-ERR-2 option A) | PROPOSED |
| Output (canonical) | `contracts/adb-observation.v1.schema.json` | REQUIRED |
| Output (advertised) | Permissive object | OBSERVED_ONLY; replace per D-SCH-1 |
| Device scope | Explicit serial, fresh discovery, present once, state `device` | REQUIRED |
| Annotations | Recommended `readOnlyHint=true`, `openWorldHint=false`; today none | PROPOSED |

**Cases** (all observed in E-CALL with fake ADB unless noted)

| Case | `is_error` | `status` | Codes | ADB calls | Class |
| --- | --- | --- | --- | --- | --- |
| Valid probes, online device | false | `ok` | none | discovery plus probes | REQUIRED |
| `ok` with a truncated field | false | `ok` | none | as above | OBSERVED_ONLY; marker in `truncated_fields` |
| Unknown probe name | false | `error` | `INVALID_PROBE` | none | REQUIRED (plan review focus) |
| Empty list, nine probes, duplicate probes | false | `error` | `INVALID_PROBES` | none | REQUIRED |
| Bad serial syntax | false | `error` | `INVALID_DEVICE_ID` | none | REQUIRED |
| Serial not attached | false | `error` | `DEVICE_NOT_FOUND` | discovery only | REQUIRED |
| Device `unauthorized` or `offline` | false | `error` | `DEVICE_NOT_READY` | discovery only | REQUIRED |
| Duplicate serial in discovery | false | `error` | `AMBIGUOUS_DEVICE_ID` | discovery only | REQUIRED by code; not exercised in this run |
| ADB missing | false | `error` | `ADB_NOT_FOUND` | none | REQUIRED |
| ADB discovery failure or timeout | false | `error` | the discovery code (`ADB_TIMEOUT` etc.), message "ADB discovery is not ready" | discovery only | REQUIRED |
| First probe command times out | false | `error` | `PROBE_TIMEOUT` | partial run | REQUIRED |
| Later probe times out | false | `partial`, earlier probes returned | `PROBE_TIMEOUT` | partial run | REQUIRED |
| Output cap | false | `error` or `partial` | `OUTPUT_LIMIT` | partial run | REQUIRED |
| Command exec failure | false | `error` or `partial` | `PROBE_EXEC_FAILED` | partial run | REQUIRED by code |
| Nonzero exit | false | `error` or `partial` | `PROBE_FAILED`, fixed message, stderr not echoed | partial run | REQUIRED |
| `probes` is a string, `[1]`, `null`, missing; `device_id` not a string | true | none | Pydantic type or missing error | none | OBSERVED_ONLY |
| Unknown top-level argument | true | none | `unexpected_keyword_argument` | none | OBSERVED_ONLY |
| Unexpected exception | true | none | exception text visible today | none or partial | ACCIDENTAL |
| Unknown action | not applicable | n/a | n/a | n/a | n/a |

Validation order (OBSERVED_ONLY, relied upon by tests): serial syntax, then
probe shape and membership, then discovery, then executable lookup, then
commands. Invalid input performs zero ADB work (verified by call counters).

**Idempotency and retry.** Read-only; safe to retry and to call concurrently
(no per-device lock is taken). Not atomic: the probes are sequential and values
may be from different moments. After `partial`, retry only the missing probes.
After a timeout, retry once the device is responsive. Results are sensitive;
do not log them.

### 5.3 `adb_develop`

**User goal.** Run one typed Android developer action against one explicitly
selected device. In the default Host composition this means: take a bounded
logcat snapshot, read package details, or preview (not run) an instrumentation
test. Installing an APK is not possible by default.

| Item | Value | Class |
| --- | --- | --- |
| Name | `adb_develop` | REQUIRED |
| Title | Observed `Adb Develop` (auto). Proposed `Android ADB Developer Action` | OBSERVED_ONLY/ACCIDENTAL; PROPOSED |
| Observed description | `Perform typed read-only package/logcat diagnostics or preview APK installation and instrumentation. Mutations require trusted host approval, lease and audit gates, absent from this initial server.` | OBSERVED_ONLY |
| Proposed description | `Run ONE typed Android developer action on ONE explicitly selected online device. Actions: logcat_snapshot (optional lines 10 to 2000, default 200), package_details (package), and, as previews only with dry_run=true, instrument_test (package, runner) and install_apk (apk_path, optional replace default true, optional allow_test default false). No arbitrary shell. In this Host configuration mutating actions are refused with MUTATION_DISABLED, and install_apk is refused unless the operator has configured approved APK directories (none by default). dry_run=true returns a planned command and runs nothing on the device. Always check result.status: "ok", "planned", "partial" or "error" with typed error codes; these are normal results, not tool failures. Output (logcat, package dumps) can contain sensitive data. The ADB lookup may start the local ADB background server.` | PROPOSED |
| Input (observed) | `device_id: string`, `action: object` (any), `dry_run: boolean`, default false; `device_id` and `action` required | OBSERVED_ONLY |
| Input (canonical for `action`) | `contracts/adb-development-action.v1.schema.json`, four closed variants: `logcat_snapshot`, `package_details`, `instrument_test`, `install_apk` | REQUIRED |
| Input (proposed advertised) | `action` published from the canonical `oneOf` (non-enforcing metadata per D-ERR-2 option A, enforcement stays in `prepare_action`); `device_id` as for `adb_observe`; `dry_run` stays a lax `bool` until D-DRY is decided | PROPOSED |
| Output (canonical) | `contracts/adb-development.v1.schema.json` | REQUIRED |
| Output (advertised) | Permissive object | OBSERVED_ONLY; replace per D-SCH-1 |
| Device scope | Explicit serial, fresh discovery, present once, state `device` (checked even for `dry_run=true`) | REQUIRED |
| Annotations | Recommended `readOnlyHint=false`, `destructiveHint=true`, `idempotentHint=false`, `openWorldHint=false`; today none | PROPOSED |

The four action variants:

| `type` | Fields | Argv produced (suffix after `adb -s <id>`) | Mutating | Timeout | Default composition |
| --- | --- | --- | --- | --- | --- |
| `logcat_snapshot` | `lines` optional integer 10 to 2000, default 200 | `logcat -d -t <lines> -v threadtime` | false | 15 s | Runs; `dry_run=true` plans |
| `package_details` | `package` (dotted ASCII identifier, at most 200) | `shell dumpsys package <package>` | false | 15 s | Runs; `dry_run=true` plans |
| `instrument_test` | `package`, `runner` (dotted Java class, at most 256, no `$`) | `shell am instrument -w <package>/<runner>` | **true** | 120 s | `dry_run=false` gives `MUTATION_DISABLED`; `dry_run=true` plans |
| `install_apk` | `apk_path` absolute `.apk`, optional `replace` (default true), optional `allow_test` (default false) | `install [-r] [-t] <resolved path>` | **true** | 120 s | Refused during planning in every mode, including `dry_run=true`, because no APK root is configured |

The `mutating` field in the envelope describes the **class of the requested
action**, not whether anything changed: `MUTATION_DISABLED` carries
`mutating=true` and nothing ran (OBSERVED_ONLY; the proposed description above
and the contract notes should say so).

**Cases** (observed in E-CALL with fake ADB unless noted)

| Case | `is_error` | `status` | Codes | Device command run | Class |
| --- | --- | --- | --- | --- | --- |
| `logcat_snapshot` or `package_details`, online device | false | `ok` | none | 1 | REQUIRED |
| Same with `dry_run=true` | false | `planned`, `result: null`, `command` has at least 2 entries | none | 0 | REQUIRED |
| `instrument_test`, `dry_run=false` | false | `error` | `MUTATION_DISABLED`, `mutating=true` | 0 (and discovery ran first) | REQUIRED |
| `instrument_test`, `dry_run=true` | false | `planned`, `mutating=true` | none | 0 | REQUIRED |
| `install_apk`, path missing or a directory | false | `error` | `INVALID_APK_PATH` | 0, no discovery | OBSERVED_ONLY (default composition) |
| `install_apk`, regular existing `.apk` | false | `error` | `APK_NOT_ALLOWED` | 0, no discovery | OBSERVED_ONLY; path oracle, section 4.7 |
| `install_apk`, non-boolean `replace` | false | `error` | `INVALID_ARGUMENTS` | 0 | REQUIRED |
| Unknown `type` (for example `arbitrary_shell`) | false | `error` | `UNKNOWN_OPERATION` | 0, no discovery | REQUIRED |
| `action` has no string `type` (`{}`, `{"foo":1}`) | false | `error` | `INVALID_ACTION` | 0, no discovery | REQUIRED |
| Extra key in action (for example `approved`) | false | `error` | `INVALID_ARGUMENTS` | 0 | REQUIRED |
| `lines` outside 10 to 2000, a string, a bool | false | `error` | `INVALID_ARGUMENTS` | 0 | REQUIRED |
| Bad package or runner | false | `error` | `INVALID_PACKAGE` or `INVALID_COMPONENT` | 0 | REQUIRED |
| Bad serial | false | `error` | `INVALID_DEVICE_ID` | 0 | REQUIRED |
| Serial not attached | false | `error` | `DEVICE_NOT_FOUND` | 0 (discovery ran) | REQUIRED |
| Device not authorized or offline | false | `error` | `DEVICE_NOT_READY` | 0 | REQUIRED |
| ADB missing or discovery failed | false | `error` | `ADB_NOT_FOUND` or the discovery code | 0 | REQUIRED |
| Another action active on the same device in this process | false | `error` | `DEVICE_BUSY` | 0 | REQUIRED by code; not exercised in this run |
| Command timeout | false | `error`, `result: null` | `OPERATION_TIMEOUT` | 1 | REQUIRED |
| Command cannot start | false | `error`, `result: null` | `OPERATION_EXEC_FAILED` | 1 | REQUIRED |
| Nonzero ADB exit | false | `error`, `result` present | `ADB_OPERATION_FAILED` | 1 | REQUIRED |
| Capture or display cap exceeded | false | `partial`, `truncated=true` | `OUTPUT_LIMIT` | 1 | REQUIRED |
| `dry_run` `"true"`, `"yes"`, `1` | false | as `dry_run=true` | none | 0 | ACCIDENTAL (section 4.5) |
| `dry_run` `2`, `"maybe"`, `null` | true | none | `bool_parsing` or `bool_type` | none | OBSERVED_ONLY |
| `action` is a string, list or `null` | true | none | `dict_type` | none | OBSERVED_ONLY |
| Missing `device_id` or unknown top-level argument | true | none | missing or unexpected argument | none | OBSERVED_ONLY |
| Unexpected exception | true | none | exception text visible today | none or 1 | ACCIDENTAL |
| Mutation with an injected secure coordinator (not default) | false | `ok`, `partial`, `error` mapped by coordinator | coordinator codes | via coordinator | Out of scope; `docs/host-native-coordination.md` |

Precedence matters for tests: serial syntax, then `dry_run` type, then action
validation, then discovery and device checks, then the executable lookup, then
`dry_run` return, then the per-device lock, then `MUTATION_DISABLED`. Therefore
`MUTATION_DISABLED` is only ever reported for an attached, authorized device;
an unattached device returns `DEVICE_NOT_FOUND` for the same action.

**Idempotency and retry.** `dry_run=true` and the two read-only actions are
safe to repeat. `logcat_snapshot` returns different content each time.
`DEVICE_BUSY` means retry later. For future mutating actions: no automatic
retry after timeout, `partial` or `*_UNCONFIRMED` (section 3.4). `replace`
defaulting to `true` is an overwrite and is the main reason the destructive
hint is recommended.

## 6. Classification register

| ID | Statement | Class | Evidence | D0 action |
| --- | --- | --- | --- | --- |
| C-01 | The catalog is exactly `device_status`, `adb_observe`, `adb_develop` | REQUIRED | Plan section A, `docs/security.md`, `test_server.py` | Protect names and count |
| C-02 | `adb_observe` and `adb_develop` need an explicit `device_id`; no implicit device | REQUIRED | `docs/security.md`, `device_guard.py`, zero-call counters | Keep tests |
| C-03 | Device must appear once in fresh discovery in state `device` | REQUIRED | `device_guard.require_online`, E-CALL | Keep |
| C-04 | Output envelopes conform to the four canonical v1 schemas | REQUIRED | Contract tests; E-SCHEMA 53 of 53 conform | Publish and test (D-SCH-1) |
| C-05 | Mutation is disabled by default; `MUTATION_DISABLED` and zero runner calls | REQUIRED | `docs/security.md`, E-CALL counters | Keep |
| C-06 | Only typed allowlisted actions; no arbitrary shell | REQUIRED | `command_plan.py`, `UNKNOWN_OPERATION` | Keep |
| C-07 | Syntactic input errors perform zero ADB work | REQUIRED | Counters (0 discovery, 0 runner) | Keep |
| C-08 | Output is bounded and truncation is visible | REQUIRED | `docs/security.md`, `OUTPUT_LIMIT`, `truncated` | Keep |
| C-09 | No stderr or exception text in application messages | REQUIRED | Synthetic canary check | Keep |
| C-10 | `dry_run=true` never runs a device command | REQUIRED | `operations.py` ordering, counters | Keep |
| C-11 | Loopback-only listener, no network opened by Host code | REQUIRED | `cli.py`, `docs/security.md` | Keep |
| C-12 | Application denials use `status="error"` with typed `errors[]` | REQUIRED (envelope) | Canonical `allOf` rules | Keep |
| C-13 | Application denials arrive with `is_error=false` | OBSERVED_ONLY | E-CALL (all 53 envelopes) | Promote (D-ERR-1) |
| C-14 | Structural type errors arrive as `is_error=true`, text only | OBSERVED_ONLY | E-CALL (20 rows) | Define level; do not freeze text |
| C-15 | Unknown top-level argument names are rejected (for example `approved`) | OBSERVED_ONLY, security-relevant | E-CALL | Promote to protected |
| C-16 | Auto-generated titles and absent annotations | OBSERVED_ONLY | E-LIST | Replace (D-META, D-ANN) |
| C-17 | Permissive output and `action` input schemas | OBSERVED_ONLY | E-LIST | Replace (D-SCH-1/2) |
| C-18 | `partial` for observe holds whole completed probes only; stops at first failure | OBSERVED_ONLY | E-CODE, E-CALL | Document |
| C-19 | `mutating` means the action class, not that anything changed | OBSERVED_ONLY | E-CALL | Document |
| C-20 | `ok` may carry non-empty `truncated_fields` | OBSERVED_ONLY | E-CODE | Document |
| C-21 | `dry_run` accepts string and integer forms of boolean | ACCIDENTAL | E-CALL, E-FW | Defer (D-DRY) |
| C-22 | Exception message reaches the client (and server log) | ACCIDENTAL | E-CALL, stderr | Mask (D-ERR-3) |
| C-23 | Invalid `device_id` and raw `action.type` are echoed unbounded | ACCIDENTAL | E-CODE | Route (4.7) |
| C-24 | `install_apk` path checks precede device discovery and reveal path existence | ACCIDENTAL | E-CALL oracle experiment | Route (4.7) |
| C-25 | Default composition never previews `install_apk`, contradicting the description | ACCIDENTAL | E-CALL, `server.py` constructs `OperationService(client)` | Fix wording (D-META) |
| C-26 | Server instructions say all tools are read-only | ACCIDENTAL | `server.py` | Reword |
| C-27 | `INVALID_DRY_RUN` and non-list `INVALID_PROBES` are unreachable through MCP | ACCIDENTAL | E-CALL | Keep as defense in depth |
| C-28 | `lines: 10.0` accepted by schema but rejected by runtime | ACCIDENTAL | Differential | Document |
| C-29 | Published output schemas equal the canonical v1 files | PROPOSED | Plan I1a to I1c | After M1 |
| C-30 | Published input limits (enum, 1 to 8, serial pattern) | PROPOSED | No canonical input schema | D-ERR-2 first |
| C-31 | Annotations per section 4.4 | PROPOSED | MCP annotation fields | Accept or alter |
| C-32 | Masked uncaught exceptions | PROPOSED | E-FW | E1 |
| C-33 | Strict boolean parsing before any mutation path | PROPOSED | E-FW | Precondition for mutation project |
| C-34 | How ChatGPT and other clients use annotations, `outputSchema` and `is_error` | UNKNOWN | Not tested | V1 |
| C-35 | Hybrid `is_error=true` plus structured envelope in FastMCP 4.1.0 | UNKNOWN | Not tested | P1 |
| C-36 | Cancellation, request timeout and child-process cleanup on client disconnect | UNKNOWN | Not tested | P1 |
| C-37 | Real-device behavior (daemon start, first-connect prompt, real probe output sizes) | UNKNOWN | Fake ADB only | Separately authorized read-only hardware run |
| C-38 | Behavior on Linux and Python 3.11, 3.12, 3.14 | UNKNOWN | macOS 3.13 only | Matrix CI at F0 |

## 7. Wire-version and compatibility impact

| Change | `schema_version` bump | Other gate |
| --- | --- | --- |
| Publish canonical output schemas, add `title`, descriptions, annotations, advertised non-enforcing input limits | No (envelopes unchanged) | Metadata change; document in release notes; conformance tests; clients that validate output now fail on any drift |
| Mask uncaught exceptions | No | E1 canary test |
| Convert application denials to `ToolError` or enforce value limits at the boundary | No envelope bump, but a **breaking external contract change** | Explicit D0 approval; updated characterization tests; release note |
| Strict `dry_run` (option 2 or 3) | No | Same as above, standalone I2 PR |
| Add, remove or rename an envelope field, change `status` enum or `errors[].code` grammar | **Yes** (canonical schemas use `additionalProperties:false`) | Native coordination for shared contracts |
| Add, split or rename a Tool | Not an envelope change | Out of scope for this plan |
| Enable mutation | Not a version bump by itself | Separate security project (grants, lease fencing, audit, strict flags) |

Because every canonical envelope forbids additional properties, even additive
fields are version-bump events once the schemas are published as `outputSchema`.

## 8. Obligations handed to later packages

These are requirements the implementer or test author must satisfy, not
approvals.

- **P3 (characterization tests).** Protect REQUIRED rows only: names and count;
  each canonical envelope validates; zero ADB calls for invalid input; zero
  runner calls for `MUTATION_DISABLED` and `dry_run=true`; wrong or unauthorized
  device denials; `is_error=false` for denials; `is_error=true` and no handler
  call for a type error. Do **not** assert Pydantic message text, titles, the
  string forms of `dry_run`, the `install_apk` path-oracle codes or section 4.7
  items, and do not assert "no annotations".
- **M1 (boundary models).** Provide a differential test between the advertised
  schema and the runtime accept/reject set (this document's 92-case differential
  is the seed) and keep the single schema source (S3). Keep `dry_run` a lax
  `bool` unless D-DRY says otherwise. Package any schema resource in the wheel;
  do not read `contracts/` at runtime.
- **V1 (metadata).** Assert titles, descriptions and annotations from a live
  `tools/list`, assert no `readOnlyHint=true` on `adb_develop`, assert the
  discovery argv set, and leave client-behavior claims UNKNOWN until observed.
- **E1.** Canary test per Tool; remember that validation errors still echo
  `input_value` under masking.
- **I1a to I1c.** Run output conformance on the real FastMCP path in-process and
  over loopback HTTP, because the SDK client will raise on any nonconforming
  `structuredContent`.
- **I2, I3.** Only after D-DRY, D-ERR-1/2 and D-ANN are recorded.
- **Documentation.** Reconcile the server `instructions`, tool descriptions and
  `docs/security.md` wording once D0 accepts the metadata.

## 9. Evidence log

All inspections were run from a throwaway virtual environment outside the
worktree (`UV_PROJECT_ENVIRONMENT=/tmp/p2-venv`, `uv sync --project host
--locked --group dev`) with scripts in a separate directory, run with
`python -I`. The inspection scripts are disposable and are not part of the
repository; the commands below reproduce the focused test run only.

| Check | Result |
| --- | --- |
| `tools/list` capture of the three Tools | 3 Tools; annotations `None`; titles auto; `meta` only empty FastMCP tags; permissive output; input schemas as in section 4.1 |
| `tools/call` matrix | 73 calls: 53 application envelopes (3 `device_status`, 14 `adb_observe`, 36 `adb_develop`), 20 framework-level errors |
| Canonical conformance of application envelopes | 53 of 53 validate with `Draft202012Validator`, 0 violations |
| Call counters | Invalid inputs: 0 discovery, 0 reader, 0 runner. `MUTATION_DISABLED` plus two dry runs: 3 discovery, 0 runner. One `package_details`: 1 runner. Two-probe observe: 2 reader |
| Action differential | 92 cases, 5 explained disagreements, 0 where the runtime is looser |
| Framework experiments | Advertise-versus-enforce, `StrictBool`, `strict_input_validation`, `mask_error_details`, client-side output validation (section 3.5) |
| Focused existing tests | `uv run --project host --locked --group dev pytest -q -p no:cacheprovider host/tests/test_server.py host/tests/test_server_observation.py host/tests/test_server_development.py host/tests/test_host_http_fake_adb.py host/tests/test_operation_contract.py host/tests/test_observation_contract.py host/tests/test_contract.py` gave 15 passed |
| Worktree state after inspections | Clean apart from this file |

Not run: the full Host gate, `scripts/dev.py check`, pre-commit or pre-push
hooks, CI, any real-device or real-ADB command, Linux, or any ChatGPT client.

## 10. Residual risks and open questions for D0

1. Choose between D-ERR-2 options A and B; the plan text supports both readings.
2. Accept or alter the annotation set in section 4.4, knowing client behavior
   is unverified (C-34).
3. Decide whether the shared `device-status` schema is published verbatim
   (recommended, single source) or as a Host-narrowed profile.
4. Decide whether the section 4.7 items become separate security fixes and who
   owns them.
5. Decide whether the lax `dry_run` conversion stays unspecified (recommended)
   and record the strict-before-mutation precondition for the future project.
6. Ask the contracts owner whether to add `default` annotations for `lines`,
   `replace` and `allow_test`, with Native coordination.
7. Confirm the intended meaning of "authorized" (ADB-authorized and attached)
   versus a future operator allowlist or caller authentication.
