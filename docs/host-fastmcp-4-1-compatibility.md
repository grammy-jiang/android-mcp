# Host FastMCP 4.1.0 compatibility report (Wave 1 P1)

**Captured:** 2026-10-12 (Australia/Sydney). **Status:** evidence only. This
report changes no production code, tests, contracts, CI or Native files.
It supplies inputs for D0. It does not set policy.

**Base:** `feature/host-fastmcp-wave1-p1` at
`f4ebf10e3c0ad73d2b3dfbcce84dac21a7516b1f` (same as `origin/main`, Wave 0
baseline #18). Read with
[host-fastmcp-refactor-baseline.md](host-fastmcp-refactor-baseline.md) and
the plan's Section P1
(`docs/superpowers/plans/2026-10-12-host-fastmcp-progressive-refactor.md`).

## 1. Version surface tested

| Item | Value |
| --- | --- |
| Host OS | macOS 27.0.1, arm64 (Linux **not** run in P1) |
| Python | 3.13.16 (locked `host/.venv`); replayed on 3.11.17, 3.12.15, 3.14.8 |
| `fastmcp` | 4.1.0. This is a meta wheel; the code comes from `fastmcp-slim==4.1.0` |
| MCP SDK | `mcp==2.3.0`, `mcp-types==2.3.0` |
| Others | pydantic 2.14.1, pydantic-core 2.50.1, anyio 4.15.1, starlette 1.7.0, uvicorn 0.54.0, jsonschema 4.26.0 |
| Official source | Tag `v4.1.0` = commit `51b618f7d5970d2870dc351081e16600f371291f` (GitHub API). Docs used: `docs/servers/tools.mdx`, `docs/servers/server.mdx` and `docs/servers/lifespan.mdx` at that tag |

The 3.11, 3.12 and 3.14 runs used throwaway venvs under `/tmp`. They were
built from `uv export --project host --locked --no-dev`, so every interpreter
had the same versions. After normalising timings, POC outputs matched 3.13
exactly (§7). Transports: in-process `fastmcp.Client(server)` and real
loopback Streamable HTTP (`server.run(transport="http", host="127.0.0.1")`
in a subprocess). No device, ADB, network service or secret was involved.
Canaries are synthetic strings.

## 2. Error masking (`mask_error_details`)

**Hypothesis:** with `mask_error_details=True`, unhandled exceptions stop
reaching the client and `ToolError` text still does. Server logs are a
separate channel. **Pass criteria:** the canary is absent from the client
text for unhandled errors and present for `ToolError`. Log exposure is only
recorded.

Source facts:

- `FastMCP.call_tool`, `fastmcp/server/server.py` around lines 1466-1531:
  - Unhandled exceptions are logged with `logger.error(..., exc_info=True)`.
  - When masked, the client gets `ToolError("Error calling tool '<name>'")`.
  - Unmasked, the client gets `...: {e}`.
  - `FastMCPError`/`ToolError` are re-raised unchanged and logged without
    a traceback.
  - Argument `ValidationError` is logged at WARNING using
    `_validation_error_summary`, which carries counts and types but no
    input values.
- The default is `mask_error_details=None`, which falls back to
  `fastmcp.settings.mask_error_details`, i.e. env `FASTMCP_MASK_ERROR_DETAILS`
  (tagged `server.mdx`). The current `server.py` sets no value and the repo
  sets no `FASTMCP_*` variable. **The current behaviour therefore depends on
  the environment.**

Observed (POC1 in-process; POC1b over loopback HTTP; identical on 3.11-3.14):

| Case | Unset/False: client | True: client | Server log (both) |
| --- | --- | --- | --- |
| `RuntimeError` in sync tool | canary visible | `Error calling tool 'x'` | ERROR + traceback **with canary** |
| `OSError` inside `asyncio.to_thread` | canary visible | masked | ERROR + traceback with canary |
| Pydantic error raised by the tool body | full Pydantic text with canary | masked | ERROR + traceback with canary |
| Deliberate `ToolError` | canary visible | **canary visible** | ERROR line, no traceback, no canary |
| Bad argument (`probes` given as a string) | Pydantic text **echoing the client's input** | same (not masked) | WARNING summary, no input |
| `httpx2` timeout (special case) | `Upstream request timed out, please retry` | same | ERROR + traceback with canary |
| Tool `timeout=` exceeded (POC4b) | `...execution timed out after Ns` | `Error calling tool 'x'` | ERROR + traceback |

Setting `FASTMCP_MASK_ERROR_DETAILS=true` with the constructor value unset
gave the same results as `True`. Over HTTP, the
`run(transport="http")` server wrote the canary to its own stderr through
FastMCP's RichHandler traceback. That traceback shows source-line context
but no locals. Every result has `is_error=true`.

**Result: PASS for the client boundary. Server logs are NOT secret-free**:
framework masking never redacts the exception message or traceback in
logs. A masked timeout looks the same as a crash to the client.

## 3. Strict input validation (`strict_input_validation`)

Source fact: `fastmcp/tools/function_tool.py` (`_strict_input_validation`,
`_validate_input`). This reads the flag from the active request context. It
then runs Pydantic `validate_json(..., strict=True)`; non-JSON in-process
input uses `validate_python(strict=...)`. Direct Python calls to the tool
function bypass the flag.

**Discrepancy:** tagged `tools.mdx` says strict mode uses "the MCP SDK's
built-in JSON Schema validation". The installed 4.1.0 code is Pydantic strict
mode. POC2b shows this: `{"n": 3.0}` for an `int` parameter passes JSON
Schema but strict FastMCP **rejects** it. An unknown key in a default-config
model passes both and is **silently dropped**.

Observed with the current `server.py` signatures (POC2). Current behaviour
is the default (lax):

| Input | Default (lax) | Strict server |
| --- | --- | --- |
| `dry_run: "true"` / `"yes"` / `1` | accepted as `true` (with `"true"` the call returns `planned`, as in Wave 0) | rejected, `is_error=true` |
| `dry_run: "false"` | accepted as `false` | rejected |
| `device_id: 5554` (int) | rejected | rejected |
| `action` as JSON string or list | rejected | rejected |
| `action` with unknown or nested extra keys (`dict[str, object]`) | **accepted unchanged** (left to `prepare_action`) | **accepted unchanged** |
| Extra top-level argument | rejected (`unexpected_keyword_argument`) | rejected |
| `probes` as a string, `{...}`, or `["selinux", 1]` | rejected | rejected |

Typed alternatives (behaviour only, not a proposal):

- A model with the default `extra` setting **drops unknown keys in both
  modes**. Only `extra="forbid"` rejects them.
- `ConfigDict(strict=True)` or `Annotated[bool, Strict()]` makes one field
  or model strict **without** the global flag. This is the narrow option.
- `Literal` probes and `min_length` are enforced in both modes.

**Result:** the global flag changes every coercing parameter at once,
including the observed `dry_run` string coercion. It does **not** check the
contents of `action` while `action` is `dict[str, object]`, and it does not
replace `prepare_action`, which rejects unknown keys itself
(`command_plan.py:72`). Any validation moved to the framework turns a typed
application envelope (`is_error=false`) into an MCP error (`is_error=true`).
P2 owns that choice.

## 4. Output schema and typed returns

Source and doc facts:

- `@tool(output_schema=...)` takes a dict, which must have an object root.
  Otherwise the return annotation is used: `dict[str, object]` gives
  `{"type":"object","additionalProperties":true}` (the baseline's
  "permissive object").
- `output_schema=None` disables structured output.
- `@tool` in 4.1.0 has **no input-schema override**. Input schemas always
  come from the function signature.
- `dereference_schemas=True` is the default. It inlines `$ref`/`$defs` in
  `tools/list` (`server/middleware/dereference.py`).
- The server does **not** validate results against `output_schema`.
- The MCP SDK client (`mcp/client/session.py` `validate_tool_result`) checks
  `structuredContent` with `jsonschema`, choosing the draft from `$schema`.
  `jsonschema>=4.20` is a runtime dependency of `mcp`.

Observed (POC3 and POC3b, canonical `contracts/*.schema.json` read-only):

| Check | Observation |
| --- | --- |
| Register canonical device-status, development or observation as `output_schema` | Accepted. `$schema`, `$id`, `title`, `oneOf`, `allOf/if/then` and `const` kept in `tools/list` |
| `$ref`/`$defs` (device-status) | Inlined by default, so the schema is not byte-identical. With `dereference_schemas=False` it is byte-identical |
| Conforming result | Success. The fastmcp `Client` turns the result into a generated type |
| Result violating `if/then`, `additionalProperties` or `required` | **Server returns success**. The SDK client raises `RuntimeError: Invalid structured content...` |
| Pydantic return model | Schema generated with titles pruned. Expresses `const`, `enum`, `anyOf` and `additionalProperties:false`, but not conditional `if/then` |
| Pydantic discriminated union for `action` vs canonical action schema (12 samples) | Emitted as `oneOf` with 4 variants. Lax mode differs on 3 samples (`"50"` for an integer, `"true"` for a boolean, `null` for an optional integer). Strict mode differs on 1 (`null`, caused by how the model was written) |
| Wheel contents (`uv build --wheel` to `/tmp`) | 22 files, **0 JSON files**. `contracts/` is not in the wheel, and the Host tests read it from the repository path |

**Result:** complex canonical schemas can be published unchanged, but the
server never validates them. A non-conforming envelope is reported as a hard
error by SDK-based clients. Any Pydantic adapter is a second schema that
drifts (§3), so it needs parity tests against canonical fixtures.

## 5. Sync `run_in_thread` vs async + `asyncio.to_thread`

Source and doc facts:

- Sync tools run through `anyio.to_thread.run_sync` (default limiter: 40
  tokens), which cannot be abandoned on cancel.
- `asyncio.to_thread` uses the loop's default executor
  (`min(32, cpu+4)`; 22 on this Mac).
- The tool `timeout=` setting uses `anyio.fail_after`. The tagged docs say
  sync workers "cannot be interrupted", and FastMCP waits for them.
- `timeout` combined with `run_in_thread=False` is rejected when the tool is
  registered.
- On `notifications/cancelled`, the SDK dispatcher by default
  (`"interrupt"`) cancels the handler scope and sends no reply.

POC4 used a child process that mimics `bounded_run`: `/bin/sleep 2`, own
deadline, `start_new_session=True`, `killpg`. Event order was identical on
3.11-3.14:

| Scenario | Sync `def` (FastMCP thread) | Async + `asyncio.to_thread` (current) |
| --- | --- | --- |
| 8 concurrent 0.5 s calls (in-process and HTTP) | about 0.52 s; ping not blocked | about 0.52 s; ping not blocked |
| Tool `timeout=0.5`, 2 s work | Error after **about 2.1 s**, once the worker finished | Error after **about 0.5 s**; awaiter cancelled; thread and child **kept running** about 2 s |
| Client task cancel (in-process and HTTP) | Client returns at 0.4 s; worker and child run to completion | Client returns at 0.4 s; awaiter cancelled; worker and child run to completion |
| Client `call_tool(timeout=0.4)` over HTTP | `MCPError: Request 'tools/call' timed out`; work continues | Same; awaiter cancelled; work continues |
| HTTP client session closed mid-call | Work continues to completion | Not separately run |
| Child past its own deadline after a client cancel (POC4b) | Child killed by the runner's `killpg` at 1.0 s (rc -9) | Not separately run; the runner owns the same deadline either way |

**Result:** no tested mechanism (HTTP cancel, MCP cancel notification,
client timeout, disconnect or FastMCP tool timeout) terminated the live
child. Only the Host runner's own deadline did. Both variants give the same
concurrency.

The differences are in timeouts and visibility:

- **Sync:** the error arrives honestly late, after the work ends.
- **`asyncio.to_thread`:** the reply is prompt, but the work is orphaned.

Inference, not tested: an orphaned worker keeps holding the per-device
`threading.Lock` in `OperationService` until it ends. This is the same in
both variants, because neither stops the thread.

## 6. Annotations, title and lifespan

API checks:

- `@tool(title=..., annotations=ToolAnnotations(...))` appears exactly in
  `tools/list` (POC5).
- Without a title, FastMCP derives one from the name. This matches the
  baseline titles (`Device Status`, `Adb Observe`, `Adb Develop`).
  Annotations are `null`.
- `FastMCP(lifespan=...)` and `@lifespan` exist. With the in-process client,
  two sessions in a row entered and exited the lifespan twice (it is
  ref-counted).
- The Host owns no long-lived resource that needs setup or teardown.

**Need:** none shown, so no new features by default. Annotation truthfulness
belongs to P2/V1.

## 7. Reproduction

The scripts are disposable and kept outside the repository, under
`/tmp/p1-poc/`. Run each from the worktree root:

```bash
uv run --project host --locked python -I /tmp/p1-poc/<script>.py [REPO_ROOT]
```

| Script (sha256 prefix) | Purpose |
| --- | --- |
| `poc1_masking.py` (`b664de5f`) | Unset/False/True masking, client text vs captured log |
| `poc1b_http_masking.py` (`2028ea32`) | The same over loopback HTTP plus server stderr |
| `poc2_strict.py` (`0d7fb748`), `poc2b_strict_engine.py` (`d6ccde4c`) | Lax vs strict matrix; engine check against JSON Schema |
| `poc3_output_schema.py` (`85d02d0a`), `poc3b_action_parity.py` (`b350950e`) | `tools/list` and `tools/call` with canonical schemas; union parity |
| `poc4_exec.py` (`e4369567`), `poc4b_supplement.py` (`f458ea7a`) | Concurrency, timeout, cancel and disconnect; own-deadline kill |
| `poc5_meta_lifespan.py` (`6943ba69`) | Annotations, title and lifespan |

Minimal masking reproduction:

```python
import asyncio
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

CANARY = "CANARY-synthetic"
s = FastMCP("p1", mask_error_details=True)

@s.tool
def boom() -> dict[str, object]:
    raise RuntimeError(CANARY)

@s.tool
def deny() -> dict[str, object]:
    raise ToolError(CANARY)

async def main() -> None:
    async with Client(s) as c:
        for name in ("boom", "deny"):
            r = await c.call_tool(name, {}, raise_on_error=False)
            print(name, r.is_error, CANARY in r.content[0].text)
            # boom True False / deny True True; stderr still logs the boom canary

asyncio.run(main())
```

## 8. Open or inconclusive questions

- **Linux:** P1 ran on macOS only. The behaviour comes from pure-Python
  framework code, but this needs confirming through CI and P3 tests.
- **Real clients:** no ChatGPT or other third-party client was tested. It is
  unknown whether those clients validate `outputSchema`, or whether they need
  `$ref`-free schemas (tagged docs: "Most clients require flat schemas").
- **Log redaction:** not investigated. Options include
  `FASTMCP_ENABLE_RICH_TRACEBACKS`, logging filters, or Host-side exception
  wrapping. None was tried.
- **Tasks:** `task=True` and background tasks are out of scope and untested.
- **Session close:** an HTTP session closed mid-call was observed only for
  the sync variant.

## 9. Inputs for D0

Each item is evidence-based. Items marked **OPEN** need an owner decision.

1. **E1 masking.** Evidence supports explicit `FastMCP(mask_error_details=True)`
   rather than relying on the env default. The E1 test should:
   - inject a canary through a fake service, including the
     `asyncio.to_thread` path;
   - assert the canary is absent from the client text and that
     `is_error=true`;
   - assert that `ToolError` and typed envelopes are unchanged.

   E1 must not claim that logs are secret-free. **OPEN:** whether a Host
   logging or redaction policy is needed (security owner).
2. **Strict input.** The global flag would break `dry_run: "true"` and
   `"false"`, and it would not validate `action` as typed today. **OPEN
   (P2):** whether to keep the coercion. If strictness is wanted, scope it
   per field or model (`Strict()`, `extra="forbid"`). Default-config models
   must never sit in front of `prepare_action`.
3. **Schema source of truth (S3).** Canonical schemas can be passed through
   `output_schema`, but the server does not validate output, so validating
   every return path in tests is mandatory. `contracts/` is not in the wheel.
   **OPEN:**
   - packaging (package-data copy plus a drift test, versus a generated
     module);
   - `dereference_schemas` (default inlined, or byte-identical canonical);
   - input schemas, which can only come from Pydantic and so need parity
     tests against canonical fixtures.
4. **I4 dispatch.** Concurrency is equivalent. Neither variant terminates the
   ADB child or improves on cancellation. A switch only changes FastMCP
   `timeout` semantics, which are unused today. The evidence suggests I4
   should be **SKIPPED** (keep the current adapter). **OPEN** for D0
   confirmation. Do not add FastMCP `timeout=` in place of the runner
   deadlines.
5. **Annotations and lifespan.** The APIs exist but no need was shown. Do
   not add them without P2/V1 approval or an owned resource.
6. **Documentation drift.** The tagged docs' JSON Schema claim for strict
   mode is contradicted by the 4.1.0 code. Base every decision on the
   installed code and these POCs.
