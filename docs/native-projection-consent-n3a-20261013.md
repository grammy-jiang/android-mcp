# N3.a — inert MediaProjection consent and foreground-service policy

**Status:** internally implemented and tested. Screen capture is not activated
on an Android device, physical or virtual. Public Native MCP still provides
only device_status. There is no new Android Manifest permission, MediaProjection
service type, user-consent prompt, screenshot, video, or external listener.

## Genuine user consent and platform requirements

A MediaProjection session requires explicit Android system UI approval;
localhost access, a ChatGPT/model-supplied approved flag, signature-shaped
fixture, or a previously cached Intent is **not** consent. The
AndroidProjectionConsentReader only checks whether MediaProjectionManager is
present through getSystemService and reads this application's own
declared permissions and Native foreground-service type. It deliberately
does not create a screen-capture Intent, launch system consent UI, obtain a
MediaProjection object, start/modify the foreground Service, or instantiate
ImageReader/VirtualDisplay/MediaRecorder.

The current Android APK has only the already reviewed INTERNET,
FOREGROUND_SERVICE, FOREGROUND_SERVICE_SPECIAL_USE and POST_NOTIFICATIONS
permissions. Its N3 foreground Service declares specialUse, **not**
mediaProjection. Android 14/API34 and Android 16/API36 require the
appropriate mediaProjection foreground-service type/permission for live
MediaProjection; absent type is reported FGS_TYPE_REQUIRED and cannot
be silently filled in. Android 11/API30 and Android 13/API33 still need
actual user consent, but this N3.a slice remains globally disabled
for capture across all APIs. No physically installed Android app settings
or permissions have been changed.

## Pure Kotlin lifecycle model and non-authorizing synthetic fixtures

The inert NativeProjectionConsent offers a versioned typed consent **plan**:
unsupported, unavailable, consent_required, fgs_type_required, denied,
revoked, or synthetic-only. The plan always sets can_capture_now=false
and has no credentials or data bytes. An internally constructed fake
session grant carries only a process epoch, bounded one-use nonce and
fixture boolean. It is never made from HTTP, MCP, an Android Intent extra,
a projection token or an external client's Origin. Epoch mismatch,
replay, fake refusal, malformed nonce, absent manager, missing Service
type or background caller is denied. Synthetic fixtures are limited to
256 replay entries. Even a recognized synthetic grant returns
SIMULATED_ONLY, and captureAllowed() is permanently false in this model.

USER_REFUSED, SCREEN_LOCKED, SCREEN_OFF, ACTIVITY_DESTROYED,
FGS_STOP, SYSTEM_PROJECTION_STOP and PROCESS_DEATH are explicit terminal
events in the model: each permanently revokes simulated readiness for that
session, with no silent restart or reuse. Real Android callback/lifecycle
wiring and user-consented token acquisition are intentionally deferred.
A Kotlin-simulated onStop does not prove Android MediaProjection.onStop
runs under a particular OEM implementation.

## Test and release evidence

Six named T-N3A-01..06 Kotlin/JUnit cases were introduced first; all
six meaningfully failed against an incomplete capture policy scaffold
before being corrected. They cover consent availability, single-use
per-API fake token behavior, API30/33 vs API34/36 FGS constraints,
stop/revocation, hostile unpaired calls and unchanged public grants.
Supplemental Kotlin tests check malformed/replayed nonce capacity,
denial with no manager/foreground and permanent absence of real
capture permission. Four Python Manifest/source guards check the
exact four-permission allowlist, no mediaProjection service type,
no Android token consumption, and status-only MCP catalog.

Release requires macOS JDK17 Native Kotlin/JVM and Host security gate,
signed SDK36 APK/Lint, unchanged Manifest permissions, and the actual
disposable API30/33/34/36 lifecycle matrix. These are compatibility and
denial tests, **not** proof that a screen was captured or recorded.
MediaProjection actual user approval, private-artifact capture, foreground
mediaProjection type and independent N6 pairing/security review are
separate enablement prerequisites. No physical Android is operated.
