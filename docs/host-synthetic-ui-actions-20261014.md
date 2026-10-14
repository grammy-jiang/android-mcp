# Host H4.f — Bounded Synthetic Emulator UI Actions

Date: 2026-10-14. Serial roadmap: H4.f (package 27/45).
Specification: `docs/host-mcp-implementation-plan-20261013.md`,
`docs/host-mcp-serial-test-cases-20261013.md` cases T-H4F-01–06.

## Capability truth and default-denied boundary

This package implements a deterministic, safe **synthetic fixture-only**
UI action Tool. It does **not** execute Android `adb shell input`,
generic shell commands, real touch gestures, Accessibility permissions,
physical-device input, or user text entry.

Production exposes `host_ui_action` only after explicit
`--ui-action-plan` plus operator-configured, owned disposable
AVD, lifecycle, durable job and private artifact prerequisites.
The CLI supplies no independent input approval, window witness
provider or synthetic executor. Execution therefore returns
`MUTATION_DISABLED`. Normal use remains **plan-only**.

No other MCP argument, unknown Android serial, environment value,
Tool annotation, emulator display name or input string can
enable an executor or bypass that boundary.

## Exact typed synthetic intent

The Tool accepts only `plan`, `execute` and `cancel`
operations for intents `tap`, `swipe` and `key`.

The helper `compile_safe_argv` emits an inert
`fixture-ui-input` protocol with fixed positional typed fields
and one preverified private AVD name. This marker is **not a
working ADB executable**. It cannot be replaced by a user-selected
binary, shell script or target serial.

- Tap: two integer coordinates from 0–4,095.
- Swipe: four integer coordinates and a 100–2,000 ms duration.
- Key: only BACK and four DPAD directions.
- No arbitrary text, power, enter, dangerous key combos,
  negative coordinates, floats, booleans or opaque shell options.
- Coordinates must also fit the synthetic witness's bounded,
  positive display dimensions before test execution.

## Window, focus and approval fencing

Every action is bound to exact owner, trusted disposable AVD
handle, positively running H3.c synthetic emulator lifecycle,
window ID, positive generation, rotation, focused node ID, and
an SHA-256 digest of the exact action intent. An independent
short-lived `UiActionApproval` contains all those fields,
the approved purpose, expiry and finite private-receipt TTL.

A trusted test fixture supplies a `UiWitness` that is compared
against all the pinned values, including synthetic identity
and secure/locked-window flags. The Host checks it before
execution, after the injected action and before receipt commit.
A focus change, window generation change, rotation, expired
grant, protected window or disconnected emulator is blocked
or marked **uncertain**. An uncertain action must not be
silently replayed or counted as verified success.

This is **synthetic witness checking**, not an Android
WindowManager, AccessibilityNodeInfo or `FLAG_SECURE`
attestation. A real backend and independent real-device
permission/security review are not part of H4.f.

## Durable single-intent execution and replay

The private durable job store records a single slot per
lifecycle, window and intent SHA-256. The plan additionally
binds the action request ID and exact target witness. The
original successful receipt is returned on a duplicate
without re-running the synthetic input; a conflicting request
is denied. Prior failed, stale, interrupted, uncertain or
expired-receipt outcomes do not trigger blind retry.

The test harness can inject a bounded `UiActionFrame` result.
The Host verifies the frame identity, completion and applied
flags and writes a private JSON audit receipt with a finite TTL.
The MCP result contains only an opaque report handle,
SHA-256, job/action ID and bounded metadata. No untrusted
command output, raw UI hierarchy, credentials or filesystem
paths are returned.

A `cancel` action requires the same exact intent, request,
owner, target and durable job ID. It marks the job uncertain
and signals the fixture's cooperative cancellation event.
A deliberately hung test-owned child process launched through
the existing bounded runner is terminated and reaped. The
system never claims to have undone an already-applied
synthetic action when cancellation arrives late.

## MCP and acceptance evidence

The versioned output schema
`host-synthetic-ui-actions.v1.schema.json` declares:

- `synthetic_fixture_only=true`
- `real_ui_input_enabled=false`
- `physical_device_writes_enabled=false`
- `generic_shell_enabled=false`
- `target="disposable_emulator_only"`

The Tool correctly advertises write-side/sensitive
annotations rather than claiming read-only semantics.
Its public plan includes only a safe inert preview, never
a generic ADB shell surface.

T-H4F-01–06 are covered by
`test_adb_emulator_ui_actions.py`, plus adversarial
`test_adb_emulator_ui_action_faults.py`, durable
`test_adb_emulator_ui_action_receipts.py`,
`test_adb_emulator_ui_action_cancel.py`,
`test_adb_emulator_ui_action_edges.py` and
`test_adb_emulator_ui_action_http.py`.

Tests include test-first red evidence, identity and grant
denials, key/coordinate injection, stale witnesses, mid-action
focus/rotation changes, timeout/reaping, durable rollback,
partial/private receipt corruption, concurrent cancellation,
in-process FastMCP catalog compatibility and genuine localhost
Streamable HTTP default-denial.

This is **not** real Android gesture acceptance, independent
external security review, a certified MCP conformance suite
or a normal ChatGPT Chat/Work tool-selection test.
Enablement of any live UI mutation would need a separately
authorized, OS-verifiable target and window protocol,
user consent, Accessibility/privacy protections,
device-side cancellation and independent reviewed tests.
