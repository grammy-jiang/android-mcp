# H1.c — bounded typed system diagnostic snapshot

The optional Host MCP Tool `adb_system_snapshot` reads five **fixed**
diagnostic groups without modifying the existing `adb_observe`
Tool or its nine version-1 group identifiers. The new Tool is disabled
by default and enabled explicitly by the Host operator:

```bash
uv run --project host --locked android-mcp-host serve --adb-system-snapshot
```

The server remains on `127.0.0.1`; public, unauthenticated remote
access is not provided.

Each request requires one explicitly selected authorized online ADB
`device_id` and one to five distinct group identifiers:
`identity`, `battery`, `storage`, `display`, `network`.
Invalid groups, duplicate selections and ambiguous or offline device
identifiers fail before any device-side probe. There is **no** arbitrary
`dumpsys`, raw property-key selection, free-form `adb shell`, USB
reconnect, input, install, grant or device mutation.

Commands and their typed output:

| Group | Fixed ADB read | Returned structured values |
| --- | --- | --- |
| identity | `getprop ro.build.version.sdk`, `ro.product.model` | validated API level, bounded ASCII model |
| battery | `dumpsys battery` | validated percentage, temperature in °C, AC powered |
| storage | `df -k /data` | nonnegative total/free storage in KiB |
| display | `wm size`, `wm density` | validated width/height in pixels, density in dpi |
| network | `dumpsys connectivity` | only the presence/absence of a parsed default network, no IP address |

The response has the Host-only, packaged JSON Schema
`urn:android-mcp:host-system-snapshot:v1` and returns a
`schema_version: 1` envelope containing a typed `results` list
and stable errors. Invalid UTF-8, impossible numeric ranges, absent
dumpsys keys and unknown formats **never become invented measurements**:
the valid subset is kept and the result becomes `partial` with
`PARTIAL_DATA`. Errors never include untrusted stdout/stderr, secrets,
private network endpoints or raw diagnostics.

The Host limits each subprocess to 64 KiB combined stdout/stderr,
a finite deadline, and process-group cleanup on timeout/overflow.
Each invocation uses a fixed argv vector with exactly
`adb -s DEVICE shell ...` and no host shell. Discovery may start the
local ADB daemon, so the Tool advertises `readOnlyHint: false`
rather than implying absolute Host-system noninterference.

The H1.c six required behavior tests plus focused negative and parser
tests use only synthetic ADB input. Tests validate actual FastMCP
`tools/list`, structured Tool results and localhost HTTP, plus exact
backward compatibility for the original three public Tools and nine
existing diagnostic groups. No real Android device or account was
touched; external authenticated MCP and physical mutation remain
separate security gates.
