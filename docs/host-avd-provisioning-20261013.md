# H3.b — dedicated, MCP-owned disposable AVD metadata provisioning

The H3.b Host Tool host_avd_provision(action,name,handle=None) is
**off by default** and restricted to local, operator-selected
disposable AVD metadata. Its bounded actions are plan, create and
delete. It never runs an emulator, downloads a system image, accepts
an SDK license, installs an APK, selects a physical Android device,
changes Native AVDs, starts Gradle, opens an external listener or
executes a user-supplied shell command.

## Explicit operator configuration

The operator must supply **all** of the following at server startup:

    android-mcp-host serve --avd-provision \
      --avd-provision-root /private/mcp-owned-avds \
      --avd-sdk-root /trusted/installed/android-sdk \
      --avd-owner trusted-owner \
      --avd-api 36 --avd-abi arm64-v8a \
      --avd-image-sha256 64_hex_sha256_of_source_properties \
      --avd-system-image-sha256 64_hex_sha256_of_system_img \
      --avd-license-sha256 64_hex_sha256_of_existing_license_receipt

The AVD root must be an absolute, non-symlinked, private directory
outside the user's existing HOME/.android/avd. This package does not
enable adoption of an arbitrary existing root. An initially absent
dedicated root is created with mode 0700; its private 0600 owner HMAC
key is created exactly once. An existing directory without the key
is untrusted and **never adopted**.

The image is fixed to SDK/system-images/android-API/default/ABI.
The already installed system.img is opened with O_NOFOLLOW, verified
as an owned regular single-link file, and SHA-256 checked by streaming
at most 1 MiB at a time with a maximum 8 GiB size. The matching
source.properties metadata must match its separately pinned digest,
API, ABI and default tag. An already existing SDK license receipt
must match its pinned SHA-256. These checks are not Google acceptance:
no license is accepted and the mere presence of a receipt does not
prove that any developer legally accepted its terms. The operator
is accountable for that provenance. Unavailable/mismatched metadata,
image or license produces a typed unavailable result, **before any
managed root is created**.

No MCP caller can select SDK/image directories, owner or digest pins.
The Tool accepts only a bounded MCP-prefixed AVD name and opaque
handle (required for delete). A plan does not create any file.
No AVD manager CLI, image copy or system side effect occurs.

## Ownership, concurrency and deletion

The managed AVD consists of exactly one generated .ini file and a
corresponding private .avd directory holding generated config.ini
and HMAC-authenticated .mcp-owner.json. Every immutable receipt
binds the name, pseudonymous owner scope, pinned binary system
image identity and deterministic unguessable MCP AVD handle. The
handle is an HMAC output under the 0600 local private key, not a
user-supplied filename or general filesystem authority. All
filesystem names are constructed only from validated source names.

A private OS file lock serializes operations across independent Host
processes. The maximum number of disposable AVDs is 16. Duplicate
create requests return the same owned handle; unrelated pre-existing
AVD directories or .ini files are never replaced, renamed or
deleted. Interrupted creation removes only its own generated files,
not any pre-existing user content.

Delete requires a matching AVD name and exact opaque handle **and**
a correctly authenticated marker, exact generated .ini and config
bytes, a dedicated private owner root and closed, unchanged directory
layout. If snapshot data, emulator runtime files, symlinks, user
data or unexpected entries exist, deletion is blocked: this package
does not recursively delete files and never terminates an emulator.
Future H3.c–d lifecycle code must implement independently reviewed
process, ownership and teardown before handling live emulator state.

Host creation/deletion may change its own private test files, so
the opt-in Tool truthfully advertises destructiveHint=true.
emulator_execution_enabled and physical_device_writes_enabled
remain false in every result. The default Host Tool catalog and
Native workstream files are untouched.

## Test and limitations

T-H3B-01 through T-H3B-06 plus adversarial cases exercise exact owner,
name, target and system-image SHA evidence, duplicate/racing create,
foreign content, signed-marker tampering, SDK/license mismatch,
symlink/hardlink denial, quotas, injected storage failures, rollback,
safe exact deletion, default-off FastMCP and separate loopback HTTP
process. H3.a can read the synthetic AVD configuration when configured
to the same private root. No existing user or Native emulator AVD is
reconfigured, started, stopped or deleted during acceptance.

HMAC ownership and local file permissions are **not** attestations
against arbitrary code running as the same OS account or a malicious
kernel/filesystem. Even with a SHA-verified installed image, actual
emulator boot, compatibility, license compliance and installed AVD
lifecycle remain untested here. Physical Android control is outside
H3.b's permission boundary.

Required integration: exact-SHA macOS ARM64 and sextant Linux ARM64
Python 3.11–3.14 Host checks, both Mac Git hook stages, per-module
coverage, Ruff/mypy/Bandit, clean wheel/sdist, scope/security review,
main-branch race recheck and byte-identical post-merge acceptance.
Hosted GitHub Actions that fail to start due to billing do not count
as test evidence.
