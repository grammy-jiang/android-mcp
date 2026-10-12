# Host H1.a: bounded ADB device discovery (read-only)

**State:** Host-only, opt-in, no Android device mutation. Public output
Schema: `urn:android-mcp:adb-device-list:v1`.

The existing Host FastMCP server continues to register the three legacy
Tools by default. Opt in to the additional zero-argument Tool from the local
Host process:

```bash
uv run --project host --locked android-mcp-host serve --adb-devices-list
```

The optional `adb_devices_list` response preserves the current serial,
connection state and numeric transport ID of **every** reported ADB target.
`ready_for_read` only describes an online `device` with a valid
transport ID; it **does not** authorize reading or acting on that device.
Every separate probe/action must still require an explicitly selected
online authorized serial, and no first-device fallback is ever used.

The Tool accepts no serial, executable, address, command or other client
input. Discovery invokes only the existing `AdbClient.inspect()`
allowlisted `adb version` and `adb devices -l` subprocesses, with their
existing finite timeouts, 64 KiB bounded capture, shell-free argv and
process-group cleanup. It never executes `adb pair`, `adb connect`,
`adb reconnect`, port forwarding, `adb shell` or any device write.

At most 64 synthetic/real device rows are accepted. Duplicate serials or
numeric transport IDs produce a typed ambiguity error and **no usable
device rows**. Invalid serial/unknown connection states are ignored and
reported as partial. An online device without a numeric transport is
marked not ready and partial; unauthorized/offline/recovery states are
never ready. ADB unavailable, timed out or daemon errors return bounded,
typed, sanitized `partial`/`unavailable` status, not raw stderr.
The intentionally conservative `readOnlyHint: false` accounts for
possible Host-side ADB daemon startup; `destructiveHint: false` is
appropriate because no Android mutation is performed.

Synthetic in-process and real localhost HTTP MCP tests cover multi-device
states, denial/ambiguity, missing binary, 64 KiB flooding, child cleanup,
schema validation and unchanged legacy Tool metadata. No physical tablet
was changed or required by these tests.
