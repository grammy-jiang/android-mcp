# H3.c synthetic emulator lifecycle and durable recovery

## Scope

The optional Host tool host_emulator_lifecycle supports plan, start,
status, and stop for exact private H3.b-owned disposable AVD handles.
The production CLI enables the tool only with explicitly pinned AVD
provisioning and a matching durable-job owner. Production configuration
has no real emulator executor. Real emulator execution and all physical
device writes are disabled, including when the tool is enabled.

A synthetic subprocess backend is available only when explicitly
injected into the Python test harness. It verifies an owned, digest-
pinned fake executable with a fixed synthetic marker and exact binary
name. It does not execute Android SDK/QEMU or use USB devices.

## Ownership, state, and failure policy

Every operation rechecks the private H3.b owner handle, AVD name,
API, ABI, image hash, and existing license receipt. H2.d persists the
exact job plan and one worker claim. Duplicate requests return the
original state without launching another child. Conflicting and
unresolved jobs block new execution.

Synthetic readiness requires exact name, API, ABI, boot completion,
correct simulator serial format, and the launched child process ID.
Results expose only opaque handles, bounded metadata, and generic
errors. No process commands, private host paths, or owner secrets
appear in the tool response. The parent controls its own fake child
and cleans up on timeout, failure, shutdown, or stop. After restart,
unknown old processes are never adopted by PID; uncertain jobs remain
blocked pending trusted reconciliation.

The tool truthfully marks lifecycle operations as potentially
state-changing. It does not enable actual Android boot checks, real
emulator port reservation, ADB operations, install, shutdown of
existing user instances, or physical device fallback. Those remain
separate safety and ownership gates for future packages.

## Test and acceptance

The six mandatory T-H3C cases and additional fault-injection tests
cover synthetic start/readiness/stop, owner denial, duplicate request,
invalid identity, corrupt output, slow/crashed workers, resource caps,
cleanup, durable recovery, production CLI default denial, and MCP
wire contracts including a local HTTP fixture. Existing Native AVDs
are not changed. Full acceptance requires Python 3.11 through 3.14
Host test/quality matrices on macOS ARM64 and Linux ARM64, Git hooks,
clean wheel and source package checks, and post-merge verification.
