# N1.a — Native Build / API / ABI coarse snapshot

**Status:** internally implemented, publication intentionally inert.
The production Android APK still exposes only the original minimal
device_status Tool at its local MCP endpoint. N1.d and N6 authorization
must be reviewed before new system information can be listed/called
through public MCP.

## Application adapter and contract

The internal AndroidBuildSnapshotReader uses only standard Android
Build.VERSION.SDK_INT, Build.VERSION.RELEASE, Build.MANUFACTURER,
Build.MODEL, Build.SUPPORTED_ABIS and the *same application's*
PackageManager versionName. No runtime grant or special permission is
required for these coarse fields. The adapter intentionally does not
invoke device serial, Build.FINGERPRINT, Android ID, MAC address, IMEI,
ad identifier, network interfaces or other per-install persistent ID.
OEM exceptions from the app version or other Build readers cause a
partial/unavailable field, not an invented default, raw diagnostic or
permission-prompt loop.

The pure Kotlin NativeBuildSnapshots normalizer emits a bounded
version-1 internal JSON snapshot with runtime, availability,
Android API level (when API >=30), sanitized Android release,
manufacturer/model, up to eight validated ABI names, and application
version. The statuses are available, partial and unsupported. An
unsupported API (before Android 11, unknown or invalid) returns
unsupported with null OS fields and an empty ABI list. Empty strings,
control characters, lone UTF-16 surrogate code points, too-long
values and strings that could contain persistent identifiers or
secret markers are discarded; incomplete or unusual ABI input is
marked partial. All output is bounded below 4096 bytes.

Only the normalization factory can construct the Kotlin snapshot;
the adapter cannot accidentally use an unsanitized raw constructor.
This data is internal to the Android application and is not written
to normal logcat, an audit record or a public tool response.

## Test evidence and limitations

T-N1A-01..06 are six named Kotlin/JUnit tests. Initial RED phase:
five meaningful failing assertions against a deliberate pass-through
stub and one existing denial characterization passing. The corrected
implementation passes all six. Separate Python security invariants
pin the exact allowed Build inputs, absence of persistent identifiers,
and unmodified one-Tool Native MCP catalog.

The JDK17 Kotlin/JVM tests, actual API36 compiled and signed APK,
Android Lint, lockfile verification, full local Host/Native quality
gate, and disposable API30/33/34/36 Native lifecycle matrix are
independent checks. The emulator matrix is public-tool and service
regression evidence; it does not prove that an unexposed Android Build
adapter was invoked on an emulator. No claim is made about a physical
OnePlus/other device or additional Android permissions. Enabling a
public Tool requires a later caller authorization and Tool-profile
review; this slice must remain safe while the user is unavailable.
