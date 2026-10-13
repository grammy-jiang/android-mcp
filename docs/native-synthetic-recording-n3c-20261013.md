# N3.c — finite synthetic recording lifecycle, not Android screen recording

**Status:** an SDK-free, testable and **inert** Kotlin finite-recording
state machine. It does not obtain Android MediaProjection consent, create an
encoder or screen surface, record the user's display, or enable any public
MCP Tool. The current APK lacks the mediaProjection foreground-service
type and permission, and no physical Android device or user account is
accessed.

## Scope of the implemented synthetic pipeline

NativeSyntheticRecording accepts a fake, process-epoch-bound consent
fixture, one-use nonce, simulated paired caller, fake UI consent,
foreground state and API30/33/34/36 inputs. Android API34+ additionally
requires a *synthetic* mediaProjection FGS-type bit. It cannot extract
real user consent from HTTP, model claims or Android Intent extras.
Even with a valid synthetic permit, realRecordingAllowed() is always
false, and no MediaProjection, MediaRecorder, MediaCodec, VirtualDisplay
or ImageReader APIs are imported or called.

The test fixture accepts at most one synthetic session per owner,
even if restarted, stopped, or invoked simultaneously with different
nonces. Stale process epochs, reused nonces, missing fake approval,
background caller or absent API34+ FGS eligibility fail closed.
The accepted fake session must declare a maximum duration of 30 seconds,
video dimensions at most 1920×1080, frame rate 1–30 and a byte budget
at most 8 MiB. Each incoming fake encoder-chunk copy is capped at
256 KiB; all accumulated chunks remain within the session byte
budget and use a monotonic deadline. A backwards/overflowing clock
reading is rejected rather than forging successful completion.

Successful fake completion requires at least 16 bytes of a synthetic
ftyp-like MP4 header and persists these **supplied fake bytes only**
inside the N0.e private artifact store. This is a toy test header,
not a decoder, encoder, validated playable movie or Android frame.
The opaque artifact receipt has bounded size, MIME, SHA-256 and a
one-minute private TTL. The output metadata always includes
synthetic_only=true and recording_executed=false, omitting all raw
fake chunk data, private paths, credentials and artifact handles.
Only the internal store owner can access the data, and close purges it.

User cancellation, simulated MediaProjection.onStop, foreground-service
Stop, Activity destruction or simulated process death calls cancel/
close: it terminates the fake session, zeroes its accumulated memory
buffers and removes any partial/private artifact. Timeout, oversized
chunks, dropped frames, fake codec failures, invalid final header,
disk/write/lock errors and missing frames yield fixed denied,
partial, uncertain or error states; no partial result is claimed to
be a complete recording. The state has no timers or background task
and cannot spontaneously continue if the process is suspended.

## Test-first evidence and actual Android limitations

Six specified T-N3C-01..06 Kotlin/JUnit cases were developed before
production code; all six failed meaningfully on the initial inert
scaffold, then passed. Supplemental tests deny invalid limits,
a symlink/untrusted app-private root, malformed synthetic MP4 header,
repeated finalization, restored/reused nonce and monotonic clock
regressions. Multithreaded tests prove one session across concurrent
starts. Five additional Python source, Manifest, public Tool and
artifact bounds tests verify absent capture/encoder APIs and the
unchanged four approved Android permissions.

A macOS JDK17/SDK36 full Host and Native local quality gate, signed
APK, Android Lint, locked dependency policy and official cross-language
MCP tests are required before merging. The disposable QEMU API30/33/34/36
matrix checks that old local status, foreground service, notification
Stop and permission-denial behavior are unchanged. These are **not**
actual screen-recording or Android MediaProjection tests. Real
N3.c end-to-end capture remains blocked pending separate genuine
user-visible consent, mediaProjection service declarations, an
independent security review and N6 caller identity/lease rules.
No physical device or account is modified here.
