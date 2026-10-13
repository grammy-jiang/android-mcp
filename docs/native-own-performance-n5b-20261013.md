# N5.b — finite own-process performance counters, global profiling disabled

**Status:** private, read-only own-process performance model and one-shot
Android adapter. No public Native MCP performance Tool, background sampler,
systemwide profiler, Perfetto trace, root action or cross-app process query.

## Own-app-only measurements

The AndroidOwnPerformanceReader observes only the process executing its
own Native APK. It checks its own package identity and reads Android's
SystemClock.elapsedRealtime, Process.getElapsedCpuTime, own Java heap usage
from its own Runtime and Debug.getNativeHeapAllocatedSize. These quantities
are represented as integer milliseconds or bytes, with explicit API level.
There is no cross-process PID, package name, process enumeration, system
resource usage, kernel tracing, private stack dump or platform log access.

A latency measurement is included only when a real own-app timed event
exists. The current Android adapter has no registered event observer, so
own_event_latency_ms is null and reports partial rather than fabricating a
value. Malformed, unsupported or missing OEM readings remain null and
produce PARTIAL, UNAVAILABLE or UNSUPPORTED. Android API30/33/34/36 are
modeled in deterministic Kotlin tests. A stale/fabricated process epoch,
CPU time decreasing in one process epoch, unsupported API or a model
request for global profiling fails closed.

## Finite synthetic session and lifecycle

NativeOwnPerformanceSession is an in-memory, synthetic-testable sample
normalizer, not an Android polling service. It accepts at most sixteen
samples per instance, at least 1,000 milliseconds apart. High-rate and
unbounded stream requests are THROTTLED. An Activity sleeping or going
background clears sample history. Foreground-service Stop, process death
or client disconnect clears the history and permanently stops the session;
a new process gets a new random epoch. A rollback in cumulative own CPU
time invalidates history rather than silently treating a restarted
process as one continuous session. No thread, receiver, persistent queue,
timer or background listener is registered by this model.

## Test-first and release evidence

Six specified T-N5B-01..06 Kotlin/JUnit tests were created first; five
failed meaningfully against the incomplete scaffold and all six passed
after implementation. Two additional Kotlin regressions prove that eight
concurrent same-timestamp requests cannot bypass one-sample rate limits
and that a decreasing CPU counter does not produce a healthy result.
Six Native Python source/Manifest checks verify own-process-only API
calls, no system profiling or sensitive identifiers, finite rate limits,
unchanged four-permission manifest and one public status Tool.

The required local macOS JDK17/SDK36 Host/Native Kotlin/JVM gate,
signed APK, Android Lint, strict dependency locks, security/coverage
checks and Python/Kotlin MCP transport must pass before merge. The
preflighted disposable QEMU API30/33/34/36 acceptance matrix checks
existing MCP and Android foreground-service/notification lifecycles,
not actual long-running performance streams.

No physical Android device, user file, other app, kernel profiler,
location or personally identifying process data is accessed. A future
production diagnostic Tool needs an independent security review and
N6 paired caller authorization, not just a fake unit-test profile.
