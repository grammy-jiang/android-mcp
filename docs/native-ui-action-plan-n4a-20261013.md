# N4.a — strictly inert UI tap/swipe/scroll/key planning

**Status:** completed synthetic-only Kotlin UI operation planner and
production-denying Android adapter. No AccessibilityService is registered,
no Android input event is ever injected, and the live Native MCP endpoint
continues to expose only the original device_status Tool.

## Strict typed intent model

NativeUiActionPlans accepts four explicit, typed requests: TAP, SWIPE,
SCROLL and a small allowlist of application/navigation keys. No arbitrary
shell text, unsupported key code, implicit gesture, text injection, HOME,
POWER or Android event API is exposed. TAP and SWIPE coordinates must lie
inside the declared display bounds, SWIPE duration is 100–2,000 ms,
SCROLL steps 1–10, and all unused action fields must be absent.
The request and current environment must agree on Android API30+, valid
display rotation, focused window, and a currently observed synthetic
N3.e node handle in the correct node epoch. A forged handle, rotated
display, stale hierarchy, unsupported API or wrong focus fails closed.

This model accepts only injected fake client authentication, user
authorization and Accessibility availability. A real Android client
cannot construct a grant by sending an approved=true model parameter:
the AndroidUiActionPlanBoundary always returns SERVICE_UNAVAILABLE,
null digest and requiresFreshAuthorization=false. Its implementation
has no GestureDescription, dispatchGesture, InputManager, sendKeyEvent,
Instrumentation, Android Intent launch or shell execution.

An allowed fake request produces a deterministic SHA-256 *planning*
digest and a typed PLAN_ONLY result with executed=false,
synthetic_only=true, idempotent=false and
requires_fresh_authorization=true. The checksum is only a comparison
of bounded public intent fields, **not** a capability token or
approval to execute a gesture. Identical fake request/environment
reproduces the same plan ID, but actual UI input is non-idempotent.
The fake cancellation model distinguishes cancellation before a
synthetic dispatch marker (CANCELLED) from cancellation after an
already-started mock operation (UNCERTAIN); it cannot undo or repeat
an event. Even the mock dispatch marker increments **zero** real
Android events.

## Security and validation evidence

Six required T-N4A-01..06 Kotlin tests were written first. All six
failed against the deliberately permissive scaffold, then passed
after implementation. Two additional regression tests ensure
unauthorized forged node handles and changed window epochs fail closed,
and cancellation cannot be revived into a synthetic replay. Five
Python source and Manifest tests verify bounds, explicit non-
idempotence, no shell/gesture APIs, unchanged public one-Tool catalog,
and no new Android permission.

The macOS JDK17/SDK36 full Host/Native local CI, Kotlin/JVM SDK protocol,
real signed APK, Android Lint and exact four-permission allowlist
are required before merging. The preverified disposable API30/33/34/36
emulator matrix demonstrates unchanged public MCP status, N2/N3
Activity/FGS, Home, notification Stop and permission-revocation
behavior. It **does not** show a tap or swipe performed by this planner,
because no Android execution path exists.

N4.b may test safe input automation **only on explicitly verified
owned disposable Android emulators**. Actual physical-device
Accessibility gestures remain blocked pending a purpose-reviewed
service declaration, genuine user activation, independent security
review and N6 paired caller/lease requirements. No physical Android
device, third-party UI or account is modified in this work package.
