# H3.a — read-only Host Android Virtual Device inventory

The optional Host MCP Tool **host_avd_inventory(name=None)** reports
only local AVD name, Android API, ABI, snapshot presence and observed
process status. No Android Virtual Device can be started, stopped,
created, modified or deleted through this Tool. The default three
Host Tools remain unchanged. This package does not authorize
ADB installs, UI changes, pairing, physical device control, root,
recovery, Fastboot or APK deployment.

## Trusted operator configuration

The Host operator explicitly opts in over localhost:

    android-mcp-host serve --avd-inventory

Default paths are the local AVD store at HOME/.android/avd and the
installed Android SDK emulator executable (Library/Android/sdk on
macOS or Android/Sdk on Linux). An operator can replace them with
absolute, trusted --avd-root and --avd-emulator paths. Both flags
require --avd-inventory and cannot be changed by an MCP client.
Missing emulator binaries or AVD stores return unavailable; the
server does not auto-install, download or accept SDK licenses.

The only emulator argument vector is the pinned binary followed by
-list-avds. This bounded call receives a controlled HOME, AVD_HOME,
SDK_ROOT and PATH. For a valid local lock PID, a second fixed
/bin/ps -p PID -ww -o args= command observes but never controls it.
The reported observed process must match the fixed emulator/QEMU
directory and exact -avd name, with no automatic USB fallback.
No arbitrary shell or caller-specified CLI flags are enabled.

## Conservative filesystem, privacy and snapshot policy

AVD names are bounded ASCII with no slashes, leading options,
whitespace, traversal or embedded control characters. Output cap,
duplicate names and invalid list metadata fail closed. The root,
AVD directory, config and snapshot directories are owner-private,
non-symlinked and checked before reading. Metadata files are read
by bounded no-follow file descriptors. The matching AVD root .ini
and config.ini must agree on absolute path, Android API (16–40),
ABI, CPU architecture and system image source.

The snapshot folders are counted with a quota; binary snapshot.pb
content is not interpreted. The reported state present_unverified
is explicitly not proof of compatibility or recoverability. Missing
or stale process PIDs are stale_or_unverified, not an authority to
stop, signal or change an emulator. No snapshot or process is
modified by reading this metadata.

Versioned MCP output never contains absolute paths, snapshot blobs,
command lines, environment secrets, physical USB device identifiers,
or account information. Errors are fixed generic reason codes.
Running process matching is best-effort observation rather than
cryptographic ownership or Native authorization.

## Real read-only macOS evidence

On 2026-10-13, the installed macOS ARM64 emulator inventory observed
four existing Native project AVDs, API 30, 33, 34 and 36. Each
was observed as running with a matching QEMU command line,
arm64-v8a ABI and one unverified snapshot folder. The observer
did not start, stop, reboot, create, delete or modify any instance.
Native development remains the owner of these AVDs.

## Required acceptance and limitations

T-H3A-01 through T-H3A-06 and supplemental adversarial cases cover
valid inventory, missing SDK/AVDs, malformed or duplicate listings,
hostile names, traversal/symlinks, invalid metadata, stale PID,
timeouts, snapshots, and true FastMCP/localhost contracts.
Linux systems without an installed emulator must return unavailable,
not fabricate support. No AVD lifecycle control is enabled.

At the exact integration SHA, Python 3.11–3.14 Host gates must pass
on macOS ARM64 and sextant Linux ARM64, with hooks, clean wheel/sdist
packaging and post-merge smoke. Billing-blocked hosted Actions do not
count as executed acceptance.
