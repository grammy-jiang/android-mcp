# H1.f — fixed read-only Fastboot transport discovery

**Scope:** Host-only opt-in FastMCP Tool. This is **not** an approved
Fastboot device mutation, recovery procedure, bootloader unlock, flashing
or external endpoint. The default `serve` still registers exactly the three
original tools, with unchanged v1 Schemas and default-denied mutation.

Enable the extra Tool deliberately from a Host-local administrator:

```sh
uv run --project host --locked android-mcp-host serve --fastboot-inventory
```

The `fastboot_devices_list` Tool accepts **no arguments**. A trusted Host
constructor chooses the installed Fastboot binary only from fixed paths
(`/opt/homebrew/bin`, `/usr/local/bin`, `/usr/bin`, or the local Android
SDK platform-tools folder). An injected absolute path is supported for
Host-owned tests/configuration but is never accepted from an MCP caller.
Hostile `PATH` entries cannot override a selected binary.

The only subprocess commands are `fastboot --version` and
`fastboot devices -l`, run with argv lists and the existing bounded
64 KiB/finite-timeout process-group-managed runner. No `getvar`,
`reboot`, `flash`, `erase`, `unlock`, `oem`, `update`, `-w`
or arbitrary Fastboot flags can be called. Missing binaries, non-executable
paths, permission denials, CLI failures, malformed versions, timeout,
oversized outputs and malformed rows yield distinct typed error codes.

The Host-only packaged output Schema
`urn:android-mcp:host-fastboot-inventory:v1` reports validated Fastboot
version, an ordered list of at most 32 syntactically sound Fastboot serials,
and sanitized USB/unknown transport **category**. No raw USB path, stderr,
bootloader variable, partition image, unlocking state or personal device
capture appears in the response. Duplicate serials or excess devices
fail closed. Missing Fastboot or no connected bootloader target is distinct
from a ready and authorized device.

**A Fastboot listing is NOT ADB device enumeration, a verified device-model
identity, an approval or a lease.** Every returned device explicitly has
`mode: unverified`, `device_authorized: false`. Distinguishing kernel
bootloader Fastboot from userspace Fastbootd requires separate gated
inspection (H7); no real device operation is triggered by the baseline test.

Six required T-H1F-01–06 tests and additional adversarial/failure tests
cover macOS 37.x and Debian 34.x versions, absent tools, invalid/duplicate
rows, argv restrictions, process-group shutdown, in-process FastMCP
metadata/Schema and fake-executable localhost HTTP. Hardware-free tests
are not evidence of actual recovery safety. Future physical inspection
and any bootloader-changing action require their separate explicit
device-aware consent and security gates.
