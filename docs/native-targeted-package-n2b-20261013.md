# N2.b — strictly targeted, currently visible Android package details

**Scope:** internal-only targeted package metadata adapter; no new public
MCP Tool or Android manifest permission. This is not an inventory of
hidden/uninstalled/cross-user Android applications.

## Boundaries and returned data

AndroidTargetPackageReader accepts one explicit, grammar-checked
package name in the current Android user. Every query first requests a
**fresh** OS-filtered visible-package subset from the N2.a reader.
Only a currently visible, exact package can reach getPackageInfo.
The PackageManager query uses only GET_SIGNING_CERTIFICATES and
GET_ACTIVITIES. It never uses broad package visibility, hidden APIs,
MATCH_ALL, uninstalled packages, a different Android UserHandle or
implicit package resolution. If an app disappears from visibility,
its earlier version/digest is never re-used.

The versioned bounded result contains only a sanitized package name,
versionName, reasonable nonnegative longVersionCode, a 64-hex-character
SHA-256 of one public installed signing certificate, and a boolean
indicating at least one exported Activity. Raw cert bytes, APK/private
paths, signatures/private signing keys, package permission grants,
other users, app labels/accounts and arbitrary platform exception
messages never enter the result. Absent or malformed values produce
partial availability with explicit nulls, not invented defaults.

Known visible-but-disabled is distinct from confirmed uninstalled and
explicit wrong-user requests. Android 11+ PackageManager commonly
returns NameNotFoundException both for uninstalled **and** hidden
packages; the adapter therefore returns NOT_VISIBLE_OR_MISSING, not
an unsupported claim of certainty. The confirmed UNINSTALLED case
can arise only from synthetic/trusted explicit provider evidence, not
from a hidden package inferred via an exception. Unsupported Android
API, broad visibility, denied/unknown N2.a source and unexpected OEM
exceptions fail closed with fixed typed statuses.

There is no persistent package-info cache, background scanning, app
launch, Settings change, cross-user API, permission prompt or
PackageManager inventory endpoint. The Android adapter is private
and not invoked by the currently registered device_status Tool.
N1.d and a separately security-reviewed N6 pairing/authorization
boundary are prerequisites before this service could become public.

## Test-first implementation and truthful release evidence

Six specified T-N2B-01..06 Kotlin/JUnit behavioral tests cover exact
visible version/signing/export fields, explicit hidden/not-visible,
disabled/confirmed-uninstalled/wrong-user errors, invalid identifiers
and injected paths, API30/33/34/36 behavior, fresh visibility rechecks
and disclosure denial. The intentionally incomplete first model
failed five specified assertions before implementation and all six
later passed. Supplemental tests deny PackageManager identity
mismatches and strip malicious version strings while normalizing
public certificate fingerprints.

Additional Python source/Manifest checks require one exact target,
fresh filtered N2.a lookup before PackageManager, no elevated flags,
no raw private metadata and no extra public Native Tool or permissions.
The Mac local JDK17/SDK36 Host/Native full quality, signed debug APK,
Android Lint, dependency integrity, Kotlin/JVM and official MCP
interop gates are required. The disposable API30/33/34/36 matrix
verifies unchanged N2/N3 public lifecycle and permission behavior;
it is **not** live on-device proof of actual package-detail extraction
because the reader is intentionally unregistered. Physical Android
hardware and user accounts remain untouched.
