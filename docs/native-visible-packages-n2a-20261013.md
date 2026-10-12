# N2.a — Android-visible application subset contract

**Status:** implemented internal bounded Kotlin contract and inert Android
PackageManager adapter. Not a public MCP Tool. No QUERY_ALL_PACKAGES,
queries-element manifest scope, cross-user permission, signed caller credential,
Accessibility, Root, or device-owner privilege is introduced.

## Visibility and nonexistence are different

Android 11+ package visibility restrictions apply before the app receives
any PackageManager result. AndroidVisiblePackagesReader calls only
getInstalledPackages(0) on the app's own PackageManager (no MATCH_ALL,
MATCH_ANY_USER, uninstalled/cross-profile flags or hidden API). It first
inspects the currently installed app's own Manifest-declared permissions
and fails closed if an unexpectedly broadened QUERY_ALL_PACKAGES grant
is declared. If PackageManager refuses/throws, returns unavailable.
Unapproved broad visibility or cross-user intent is explicitly denied.

The result is a *platform-filtered, visible subset*, not a comprehensive
installed-app inventory. Absence means NOT_VISIBLE_OR_MISSING, never a
definitive uninstall/not-found assertion. Android API30/33/34/36 are
supported, with older APIs unsupported for this capability. The
platform is authoritative for visibility and may apply vendor
restrictions; no first-device/full-universe fallback exists.

The Kotlin normalizer uses a strict limited package-name grammar,
drops malformed/overlong/sensitive-looking entries and missing
ApplicationInfo flag/enablement values, deduplicates and sorts names,
and returns at most 64 app names after examining at most 512
platform-returned candidates. Each result has only a package name,
system flag, enablement flag, and coarse filtered/partial/denied/
unsupported/unavailable metadata. No signatures, raw application
labels, icons, permissions, account tokens, private install paths,
package-private data, device IDs or full candidate counts are
included. Truncation and visibility_restricted flags are explicit.

The internal single-worker sampler bounds the *wait* for PackageManager
to 1.5 seconds in the Android adapter. A fake OEM blocking call or
exception yields unavailable/empty, and closing the sampler interrupts
the bounded worker. A non-interruptible OEM framework call cannot be
forcibly killed by Kotlin and may run until the platform returns; this
is a remaining platform resource risk before any public activation.
There are no background scans or automatic subscriptions.

## Execution evidence, safety and deferred publication

T-N2A-01 through -06 test sorted/deduplicated visible records,
unknown hidden-vs-missing status on API30/33/34/36, broad/cross-user
denial, malformed/huge/timeout cases, denial for unpaired localhost
callers, and data minimization. On the deliberate first incomplete
implementation, five required behavioral tests failed; the
implementation passed all six, plus extra incomplete metadata,
security-exception and closed-sampler regressions. Four Python static
checks confirm no Manifest visibility escalation, no cross-user
PackageManager request and no new public Tool.

JDK17 Kotlin/JVM and actual SDK36 APK/Lint/permissions builds must
pass before PR merge. The existing one-Tool Python/Kotlin MCP smoke and
API30/33/34/36 disposable emulator matrix verify that the prior
public status, Activity/FGS, notifications and Stop behavior remain
unchanged. They **do not** show that unregistered package enumeration
works on a particular physical device or authorize a remote client to
enumerate any package.

The adapter is intentionally not invoked by the production LocalMcpGateway.
N1.d/N6 security review and actual caller identity are prerequisites
to exposing even the Android-visible subset to a client. No physical
Android device or user data is accessed in this PR. PR #39 and the
parallel Host development worktree remain untouched.
