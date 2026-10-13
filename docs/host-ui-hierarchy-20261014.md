# Host H4.b — Bounded, Redacted Synthetic UI Hierarchy

Date: 2026-10-14
Roadmap: H4.b (package 23/45), after H4.a.
Source of truth: `docs/host-mcp-implementation-plan-20261013.md` and
`docs/host-mcp-serial-test-cases-20261013.md`, cases T-H4B-01–06.

## Security and implementation boundary

This is a **complete synthetic-only contract and parser**, not a live
uiautomator/ADB implementation. Real Android UI inspection, Accessibility
access and physical device operations remain **disabled** in the production
Host CLI. Production exposes only `host_ui_hierarchy(action="plan")` after
an operator opts in with `--ui-hierarchy-plan`, together with owned AVD,
lifecycle and job-store prerequisites. It cannot supply a fixture backend or
approval through an MCP Tool argument, environment variable or unknown device.

The test harness may inject a deterministic `UiTreeFrame` reader under a
trusted, time-limited `UiApproval`. Exact private AVD ownership and the
same positive H3.c synthetic lifecycle job are verified before and after
reading. A nonblocking owner-scoped lock prevents overlapping fake operations.
A failed or missing check is a typed denial, never a fallback to any ADB serial.
A status change during observation is **uncertain**, not a successful tree.

## Untrusted input and privacy

The raw fake hierarchy is limited to **32 KiB** and is parsed with
`defusedxml`. DTDs/entities, non-UTF-8 XML, NULs, malformed tags, duplicate
or invalid node IDs, ambiguous focus, stray text, unsupported rotation, excessive
depth (12) and more than 96 nodes are rejected. The response is capped at
32 KiB, contains only a small known set of typed fields and never contains
the raw XML or backend stdout/stderr.

Safe output includes synthetic IDs, parent IDs, class names, sanitized resource
IDs, focus metadata, and selectively redacted text and content descriptions.
Password fields, EditText descendants, notification nodes/descendants,
credential-like strings, email addresses, control characters and oversized
text are **redacted**. The policy is heuristic: it is **not** certification that
all possible private user data can be detected. Real-device enablement would
require a stronger reviewed policy and independent consent checks.

The output contract explicitly labels `synthetic_fixture_only=true`,
`real_ui_access_enabled=false`, `accessibility_bypass_enabled=false`,
`physical_device_writes_enabled=false` and `raw_xml_returned=false`.
No `adb shell`, touch, input, click, swipe, privilege grant, screenshot or
unbounded XML fields are exposed by the UI tool.

## Execution and fault behavior

UI fixture readers receive only exact trusted AVD identifiers and finite
`(3 seconds, 32768 bytes)` limits. A synthetic subprocess using the existing
bounded process runner is terminated as a process group on timeout; the service
returns a generic `TIMEOUT` without leaking command paths. Truncated or malformed
XML, a window changing mode during capture, protected or locked windows, missing
UI capability, disconnected synthetic emulators and spoofed fixture metadata are
explicitly denied. No automatic retry follows an uncertain result.

## Public interface and verification

- `host_ui_hierarchy(action: "plan" | "inspect", avd_name, avd_handle,
  lifecycle_job_id, request_id?)`; `request_id` is mandatory for inspect.
- JSON Schema: `host/src/android_mcp_host/wire_schemas/host-ui-hierarchy.v1.schema.json`.
- Core parser: `host/src/android_mcp_host/ui_hierarchy_support.py`.
- Service and Tool: `synthetic_ui_hierarchy.py` and `synthetic_ui_tool.py`.
- CLI: `--ui-hierarchy-plan` added through `cli_capture_options.py`.
- Required tests: `test_adb_ui_hierarchy.py`,
  `test_adb_ui_hierarchy_faults.py`, and
  `test_adb_ui_hierarchy_http.py`.
- Tests cover the six T-H4B identifiers, explicit physical-default denial,
  a real localhost Streamable HTTP MCP contract, schema compatibility,
  synthetic secret redaction, a deliberately hung child process and cleanup.

Tests and validation are not evidence that an Android emulator or tablet has
been accessed: the release path deliberately does not have a live UI reader.
Before live UI inspection is enabled, implement and independently review an
identity-pinned uiautomator backend, exact transport ID, short user approval,
secure-window detection, foreground ownership, stronger redaction and
real-device acceptance. Do not describe the current Tool as live-capable.
