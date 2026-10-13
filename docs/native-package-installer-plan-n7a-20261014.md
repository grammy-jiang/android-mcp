# Native N7.a — user-confirmation-only APK install plan

**Status: private synthetic plan only; no APK install possible.**
The Native MCP app still publicly registers only `device_status`, and
`AndroidPackageInstallerPlanBoundary` hard-denies all real install requests.
No PackageInstaller session, user-consent Activity/Intent, new Manifest
permission, package mutation, physical device, Host Tool or shared contract.

A fake, app-private artifact carries a 32-character opaque handle, exact
trusted SHA-256 APK checksum, exact trusted signing certificate fingerprint,
package allowlist, supported ABI, API/min/target SDK range and finite size.
All trust claims are **injected test fixtures**; the production Android app
has not loaded or authenticated an APK signature. File/content URIs, arbitrary
paths, unsigned/unpinned artifacts, absent source bytes, mismatched packages,
ABI, version or certificate are denied. Synthetic `installWithoutPrompt`,
broad install permission or unverified caller is denied; `approvedByModel`
is explicitly ignored.

A positive safe input creates a deterministic hash-based **plan reference**,
never an executable grant. Each plan always requires visible, separate real
Android user confirmation. The API30/33/34/36 unknown-sources setting is
modelled as a separately required user action when not approved; even an
injected true policy signal cannot claim real consent, silent installation,
Platform PackageInstaller rights or an active session. The plan never
attempts to request `REQUEST_INSTALL_PACKAGES`.

Requests are synchronized, one-use and bounded to 64 entries; duplicates,
false caller claims, expired/unsupported versions, interrupted/cancelled
or user-Stopped plans cannot initiate an installation, and planning a
new operation after Stop is rejected. Diagnostics omit private app handles,
certificates, hashes, request IDs, and return `installation_performed=false`,
`installer_session_opened=false`, `automatic_retry=false`. There is no
persistent installation journal or actual OS installation here.

T-N7A-01..06 were all RED as genuine failed assertions on an isolated
permissive scaffold and subsequently GREEN after implementation; three
additional Kotlin tests cover capacity without eviction, hostile/redacted
metadata and 12-thread concurrent replay. Six Python source/Manifest/public
Tools gates also prove fail-closed behavior. Actual signed Android APK/Lint,
JDK17 SDK36, Host+Native local gates, Git hooks and an explicit verified
API30/33/34/36 QEMU acceptance are required before merge.

**N7.b next:** Android-mediated consent in a strictly operator-owned
throwaway emulator only (or honest blocked/inert result if it cannot be
safely demonstrated). This N7.a plan is not N7.b proof. Real device silent
install remains prohibited pending independent security review and owner
approval.
