# N3.d — Accessibility eligibility, user activation and default-off policy

**Status:** implemented read-only, private, default-off eligibility model.
No Android AccessibilityService is declared or activated, no Accessibility
permission is granted, and the live Native MCP Tool catalog remains exactly
device_status. Physical Android settings and users remain untouched.

## Android eligibility and user-consent boundaries

An Android AccessibilityService is a sensitive user-enabled component.
An application cannot infer permission from its own service declaration,
a ChatGPT-approved boolean, an HTTP Origin header or a stale fake grant.
The current APK has **no** AccessibilityService and no binding permission
or accessibility metadata declaration. A user opening Android Settings
cannot activate a service the APK does not declare. The private
AndroidAccessibilityEligibilityReader therefore inspects only its own
package service list, checks for a matching bind-accessibility permission
and required accessibilityservice metadata, and reads only whether the
screen is locked from KeyguardManager. The adapter does not query
Settings.Secure, read accessibility nodes, enumerate other apps, launch
Settings or a consent screen, dispatch a gesture or modify any grant.

An absent declaration produces SERVICE_NOT_DECLARED, not
USER_ACTIVATION_REQUIRED or an enablement promise. When a separately
reviewed future build legitimately declares a service, its policy can
plan that explicit Android user activation is necessary; a declaration
alone never confirms a granted or connected service. The current
adapter supplies userEnabled=false and serviceConnected=false and
never claims active privileges. The currently reviewed purpose is
VISIBLE_UI_INSPECTION; a missing purpose fails closed. Android API
30/33/34/36 are modeled as applicable; earlier APIs and unavailable/
background or screen-locked conditions are distinct statuses.

The internal Kotlin NativeAccessibilityPolicy is process scoped, with
a random epoch and one-use bounded synthetic fixture nonce. A fake
caller and fake UI approval can produce only SIMULATED_ONLY in Kotlin
unit tests after **all injected** service-enabled/connected/purpose/
foreground/screen-unlocked preconditions pass. Replays, stale epochs,
unsigned/hostile callers, malformed nonce or absent service deny.
USER_REFUSED, USER_DISABLED, SERVICE_DISCONNECTED, FOREGROUND_STOP,
SCREEN_LOCKED and PROCESS_DEATH permanently revoke synthetic state.
Neither real UI inspection nor UI action may ever be authorized by this
policy; both live methods return false. A fake approval cannot be
converted into a real Android AccessibilityService credential.

## Test-first and deferred activation

Six required T-N3D-01..06 Kotlin tests were written first: all six
failed on the deliberately permissive scaffold, then passed against
the denial-first policy. Supplemental tests cover fake nonce replay
cache size, invalid nonce and enabled/connected/background/locked
conditions. Four additional Python source and Manifest tests assert
no direct Settings permission grant, no startActivity/Service calls,
no gesture or node read API, exactly one existing nonexported FGS,
and the unchanged public Tool and four-permission allowlist.

After local JVM and SDK36 APK compilation, the required full Host and
Native local quality/security gates, Android Lint, signing and QEMU
API30/33/34/36 matrix must pass before merging. Emulator tests validate
the old status-only MCP and user-started FGS behavior, not actual
AccessibilityService activation or UI inspection, which remains
blocked. The separate N3.e bounded fake UI-tree model is testable
without Android permission; real Accessibility execution will still
require independent N6 caller/pairing security review, a purpose-
reviewed service declaration and genuine user activation.

This slice performs no physical Android device or account operation.
It is not an independently approved Accessibility capability.
