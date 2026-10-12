# H1.b — bounded exact-target transport and port-route inspection

**Safe mode:** read-only observation; opt-in localhost MCP Tool.
**Implementation stage:** H1.b, after the verified H1.a device-list Tool.
**Enabled with:** `android-mcp-host serve --adb-transport-inspect`.
The default `serve` command continues to register the original three
v1 Tools only. This Host-only addition changes neither `android/**`
nor `contracts/**`.

The new `adb_transport_inspect` Tool requires both an explicit ADB
`device_id` (serial) and its exact nonzero `transport_id` from trusted
discovery. It never selects a first device or guesses one from cached
state. Invalid, unknown, duplicated, unauthorized, disconnected or
changed transport IDs return domain errors with no follow-up device
command. A prior H0.c target hint is **not** an authorization lease.

## Inputs and outcomes

- `device_id`, `transport_id` are required, strictly checked.
- `target_state`: `device` (default) or `recovery` only; neither
  choice triggers reboot or recovery entry.
- `wait_seconds`: a finite bounded poll from 0 to 10 seconds. Each
  individual ADB command is also bounded. Missing/changed/disconnected
  targets stop immediately. Offline targets without an explicit wait
  return `pending`, not fabricated readiness. Timeout and caller
  cancellation return distinct domain outcomes.
- `include_routes`: optional fixed read-only `adb -s SERIAL forward
  --list` and `reverse --list`. The only output fields are direction
  and validated numeric TCP port pairs; unknown serials and Unix socket
  paths are not reflected. The response is limited to 32 routes.
- `include_mdns`: optional fixed `adb mdns services` observation.
  `mdns_endpoint` is an optional exact-match filter; malformed,
  local-zone-suffixed or injection-shaped endpoints are rejected before
  any ADB call. The output contains a bounded count and match boolean,
  **never the raw discovered addresses**. Up to 32 service rows are
  accepted; malformed output returns typed `partial`.

The packaged output contract is
`urn:android-mcp:adb-transport-inspection:v1`. It includes an exact
target, last observed state, `status`, sanitized route records,
optional redacted mDNS summary and typed error codes. It cannot
grant a native lease, operator authorization, pairing, network
forwarding or permission escalation.

All ADB commands use an argv vector without a shell and a fixed
64 KiB subprocess capture cap. The shared runner uses a new process
session and terminates/reaps the group on timeout/overflow; no
unbounded `adb wait-for-*` child is created. A caller cancellation
sets a cooperative stop flag and prevents any subsequent command.
Live ADB discovery may start the **host-side** ADB daemon, so the
Tool truthfully advertises `readOnlyHint: false`,
`destructiveHint: false`, `openWorldHint: false`.
Neither the Tool nor its tests make Android device changes.

## Verification and limitations

Six required T-H1B-01–06 cases plus focused hostile-output,
state-transition, timeout, cancellation, process cleanup, JSON Schema,
FastMCP in-process and localhost HTTP tests use synthetic ADB data.
No real hardware is necessary or touched. Loopback-only HTTP
acceptance is **not** authenticated external access. The transport
observation may become stale immediately after the response; every
future sensitive read or write must independently recheck exact
target identity and authorization. No automatic reconnect or port
creation is provided.
