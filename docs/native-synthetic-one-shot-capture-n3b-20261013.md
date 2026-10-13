# N3.b — Synthetic one-shot frame validation and private artifact lifetime

**Status:** safe internal implementation and tests of a **synthetic-only**
single-frame pipeline. This is NOT a working Android screenshot feature,
user-approved MediaProjection capture, screenshot MCP Tool, or proof of
MediaProjection readiness. All real screen-capture operations remain disabled.

## Scope and safety boundaries

NativeSyntheticOneShotCapture is a pure Kotlin fixture that takes caller-
supplied synthetic PNG bytes. No Android MediaProjection token, MediaProjection
Manager, ImageReader, VirtualDisplay, real screenshot, surface or screen
contents are obtained. A fake local SyntheticCaptureContext is not parsed
from an HTTP request or Tool input and is not an authorization grant. It
requires its own process epoch, one bounded nonce, fake synthetic caller and
UI consent, foreground state, unlocked/nonsecure synthetic screen and (API34+)
an explicitly declared mediaProjection FGS-type flag. Recognition can return
simulated_only, but captureRealIsAllowed() always returns false.

A denied, forged, stale/replayed, secure-window, locked-screen or background
context cannot publish an artifact. The per-owner one-shot nonce is consumed
when a structurally valid fake frame enters the private file path; a repeated
call cannot write a second frame. A new process gets a different epoch. An
owner Stop/projection callback is represented by calling close, which releases
and purges its N0.e NativeArtifactStore. No capture resumes on reboot,
process death or new Activity foreground automatically.

The strict synthetic frame fixture accepts only bounded 8-bit RGBA PNG
with matching 1–4096 pixel width and height, maximum 4,194,304 pixels,
8 MiB PNG bytes and 3,000 ms supplied synthetic elapsed-time bound. It
checks PNG magic, IHDR dimensions/type/compression/interlace, every PNG chunk
length and CRC-32, IDAT before IEND, exactly one IHDR, final IEND, no trailing
data, and rejects all unrecognized ancillary chunks/embedded metadata.
The fixture deliberately does not decompress or decode image pixels.
It validates a private byte snapshot rather than a mutable caller buffer,
preventing validation/write time-of-check/time-of-use substitution.

After validation, N0.e creates one private hashed artifact in an owner-only
directory below an app-private caller-supplied root (Android integrations
are required to use Context.noBackupFilesDir). The 192-bit random handle,
SHA-256 digest and expiry are held internally. Maximum single artifact and
total live bytes are both 8 MiB, maximum entries is one, and TTL is 60
seconds. A failed write returns a fixed error and closes the owner, without
exposing filesystem paths, image bytes or exception messages. Public-style
metadata contains only fixed schema/status, synthetic_only=true and
capture_executed=false; there is no public route for the artifact.

## Tests and release interpretation

The six required T-N3B-01..06 Kotlin tests and three supplemental tests
use only synthetic bytes and temporary app-private directories. The original
unimplemented scaffold produced five meaningful red failures; green tests
verify one private hashed artifact, denial without fake consent/identity,
locked/secure-window refusal, huge/malformed/timeout frames, API30/33/34/36
fake single-use lifecycle, Stop cleanup and zero raw frame in metadata.
The malformed initial PNG fixture had an invalid IDAT CRC and was replaced
with a standards-conformant synthetic 1×1 RGBA PNG rather than weakening
validation. Additional tests verify bad CRC/trailing bytes/IHDR, concurrent
requests (exactly one published artifact), symlink root rejection and no
sensitive error disclosure. Five extra SDK-free Python tests require no new
public capture Tool, manifest permission, MediaProjection FGS type or
Android capture API path.

Passing Kotlin unit tests is not proof of Android consent or screen
capture. No permission-gated disposable test APK is authorized or built in
this work package; the current production APK lacks MediaProjection FGS
permissions and type. The four-API emulator matrix checks only unchanged
existing MCP, foreground-service, notification, Home and permission denial
behavior. Actual N3.b on-device capture remains deferred pending real
system UI consent, manifest/FGS security approval, N6 paired identity and
an independent security review. Physical Android devices are never touched.
