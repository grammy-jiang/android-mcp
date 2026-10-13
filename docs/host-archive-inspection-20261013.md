# Host H2.e — local APK/AAB artifact inspection (no device mutation)

## Surface and security boundary

An optional host_archive_inspect(handle) FastMCP Tool reads only a
previously stored Host **private artifact handle** under an operator-fixed
owner. It does not upload new files, accept a file path, change the active
owner, sign packages, run Gradle, install APKs, access ADB, select devices,
or launch any arbitrary shell command. The default Host Tool catalog is
unchanged. Returned data is a bounded versioned JSON envelope, never
raw binaries, keystores, credentials, signature blobs or local paths.

Use the existing host_artifact_metadata store configuration. To enable:

    android-mcp-host serve --artifact-metadata \
      --artifact-root /operator-private/root \
      --artifact-owner approved-host-owner \
      --archive-inspect

On hosts with trusted vendor tools, the operator may supply **absolute**
fixed executable paths using --apk-verifier, --aab-verifier,
--apk-metadata-tool and --aab-metadata-tool. The two verifier options
accept an apksigner executable and a JDK jarsigner executable.
The APK metadata reader accepts aapt2 supporting dump badging.
The AAB reader accepts an operator-installed bundletool **CLI wrapper**
supporting dump manifest --bundle=FILE --module=base. A .jar path
alone is not an executable wrapper and must not be passed as such.

No model-side MCP field can select or override these paths or flags.
Missing, relative, symlinked, non-executable, failing or timed-out tools
cannot manufacture verified outcomes. This is an optional offline
workstation capability, not general trust in arbitrary archive contents.

## Bounded offline evaluation

The inspector accepts only records whose already authenticated MIME is
APK or AAB. The artifact store rechecks owner, expiry, revocation and
SHA-256 object integrity on each read. The inspector then validates:

- ZIP central directory, filenames (no traversal, absolute paths,
  backslashes, control characters, duplicates or symlinks), member
  counts and sizes, compression methods/ratios, CRC of every member,
  total uncompressed bytes and manifest byte limit.
- Android manifest package, version code/name and permission syntax
  with bounded ASCII fields. Literal synthetic XML is parsed with
  defusedxml. Real APK binary AndroidManifest.xml is decoded only
  by the optional fixed aapt2 process; AAB protobuf manifest needs
  the optional fixed bundletool wrapper.
- Bounded ABI directory names and the presence of the conventional
  resource entry. The resources_present field means a CRC-checked ZIP
  entry was present, **not** that resource content was fully decoded
  or that the package is installable.
- APK signature through apksigner verify --verbose with both exit status
  and positive vendor output. AAB JAR signature through jarsigner
  -verify -strict, checking both exit status and positive output.
  A fake META-INF/ file, file SHA-256, CRC or metadata reader
  output is never treated as signature evidence.

Any vendor tool executes as an explicit argument vector under a small
sanitized environment with timeout, combined output cap and process
group cleanup. Sensitive bytes are staged only under a temporary private
directory (0700) with a private input file (0600). The temporary
directory is removed even after failure or timeout. Outputs are parsed
and discarded; public responses contain only generic reason codes.

## Fail-closed states and limitations

The status ok requires a safely validated archive, parsed manifest and
positive trusted signature verification. Otherwise status is partial with
explicit reasons such as MANIFEST_UNAVAILABLE, SIGNATURE_UNAVAILABLE,
SIGNATURE_REJECTED or VERIFY_TIMEOUT. Malicious/invalid ZIPs return
invalid; inaccessible owner-scoped handles return not_found.

Signature verification assumes the Host operator has independently
chosen and secured genuine vendor binaries. Path validation and
sanitized execution reduce accidental misuse but are **not software
supply-chain attestation** or a cross-runtime authorization grant.
No Android installability, signing-key ownership, Play signing lineage,
device compatibility or arbitrary native resource safety is asserted.
Portable tests use controlled fakes; they do not establish that a real
APK/AAB is cryptographically signed. Optional vendor tools must be
tested with genuine artifacts before production sign-off.

This package is exclusively Host-only. It changes neither the Android
Native sources nor shared Host/Native contracts or physical-device
authorization policy.

## Test map

- T-H2E-01: scoped APK/AAB manifest/version, hash, ABIs and resource
  entry with controlled trusted-verifier responses.
- T-H2E-02: unsigned/fake signature and corrupt ZIP refusal.
- T-H2E-03: unsafe paths, symlinks, duplicate members, compression,
  size/permission limits, adversarial manifests and CRC errors.
- T-H2E-04: absent, relative and symlinked vendor-tool denial.
- T-H2E-05: CLI timeout, output limit and malformed metadata.
- T-H2E-06: default Tool compatibility, localhost HTTP, owner
  privacy and strict schema validation.

Acceptance is subject to docs/host-merge-gates.md at the exact
integration SHA: macOS ARM64 and Linux ARM64, Python 3.11–3.14,
both Git hooks, clean wheel/sdist and local merge-tree verification.

## Real compiled-APK smoke evidence (macOS ARM64)

2026-10-13, using installed Android SDK build-tools 36.0.0,
AAPT2 linked a generated package manifest into a real binary Android
manifest APK. The plain XML parser deliberately returned
MANIFEST_UNAVAILABLE. With the operator-pinned aapt2 reader, the
private artifact inspector correctly returned package
com.example.h2eproof, version code 19, version name 0.19 and
INTERNET permission from compiled AXML. The unsigned fixture
correctly returned signature unavailable and overall partial.
No Android device, Gradle task or signing key was used.
