# H1.d — read-only, exact-package Android diagnostics

**Status:** bounded Host-only opt-in capability. The existing
`adb_develop` `package_details` action, its v1 JSON envelope, and the
three-tool default FastMCP catalog remain unchanged. Host CLI
`serve --adb-package-inspect` adds `adb_package_inspect` on the
existing **localhost-only** HTTP endpoint.

The Tool requires an explicit, online, unambiguous `device_id` and
one strict ASCII Android package identifier (maximum 180 characters).
The only device command is a fixed argv vector:

```text
adb -s <selected_device> shell dumpsys package <validated_package>
```

There is no general ADB shell, package-list fallback, install, uninstall,
package clear, force-stop, permissions mutation, arbitrary filesystem
path, pairing, network bind change or model-controlled executable.

## Output policy and diagnostics

The Host-only, wheel-packaged schema
`urn:android-mcp:host-package-diagnostics:v1` returns `schema_version`,
`runtime`, exact `device_id` and `package`, `found`, `status`,
`version_name`, `version_code`, `target_sdk`, up to 32 allowlisted,
deduplicated requested/granted permission identifiers, truncation flag
and typed error codes. Raw dumpsys text, stderr, UIDs, unrelated packages,
addresses, credentials and other sensitive fields are never returned.

The parser only accepts one uniquely identified
`Package [the.exact.name]` block; a similarly prefixed package
cannot satisfy a request. Missing or unparseable blocks become typed
`PACKAGE_NOT_FOUND` or `PACKAGE_VISIBILITY_UNKNOWN` outcomes instead
of inventing metadata. Malformed version/SDK data, clipped permission
lists and nonempty command stderr are marked `partial`. Unknown or
duplicate permissions are filtered/deduplicated; lists are bounded
even if a fake CLI returns an oversized response.

Missing/offline/unauthorized/ambiguous devices, invalid package
names/options, process permission failures, nonzero exits, timeouts,
64 KiB output overflow and unexpected runner errors are typed
fail-closed denials. A subprocess runner starts a new process group and
terminates/reaps it on deadline or output overflow. Every failure
response is constrained by schema and avoids echoing untrusted
diagnostics.

The documented Tool annotations conservatively mark
`readOnlyHint: false` because ADB discovery may start a **Host-side
ADB daemon**, although this implementation does not issue an Android
device write. `destructiveHint` and `openWorldHint` are false.
No authenticated external ChatGPT endpoint or special Android grant
is implied by local tool visibility.

## Verification and limitations

Required T-H1D-01–06 cases and additional parser/security tests use
synthetic Android/ADB output. They assert actual in-process FastMCP
schemas and structured results and a real localhost HTTP server using
a fake executable, backwards compatibility of legacy Tool metadata,
strict pre-dispatch denials, process-group cleanup, and sensitivity to
a malformed duplicate-permission regression. No connected Android
device is used in the automated acceptance suite. The exact local
macOS/Linux ARM64, four-Python gate receipts and merged commit
identifier belong in the H1.d PR.

Package visibility differs between Android versions and OEMs. When
Dumpsys does not expose a uniquely verifiable package block or required
version information, the result remains unavailable or partial; a
successful device probe does **not** establish authority for any
subsequent package mutation.
