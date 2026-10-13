package org.androidmcp.nativeapp

import android.content.Context
import android.os.Build
import android.os.Debug
import android.os.Process
import android.os.SystemClock
import org.androidmcp.protocol.NativeOwnPerformanceSession
import org.androidmcp.protocol.OwnPerformanceInput
import org.androidmcp.protocol.OwnPerformanceResult
import org.androidmcp.protocol.OwnPerformanceStop

/**
 * Private, one-shot own-process performance preflight.
 *
 * Never calls ActivityManager.getRunningAppProcesses, systemwide instrumentation, root, system
 * tracing or a cross-process memory introspection APIs. No scheduler/subscription,
 * network endpoint or public Tool registers this internal adapter.
 */
internal object AndroidOwnPerformanceReader {
    fun read(context: Context, foreground: Boolean): OwnPerformanceResult {
        val own = NativeOwnPerformanceSession()
        if (context.packageName != "org.androidmcp.nativeapp") {
            own.stop(OwnPerformanceStop.PROCESS_DEATH)
        }
        val heap = safely {
            Runtime.getRuntime().let {
                (it.totalMemory() - it.freeMemory()).coerceAtLeast(0L)
            }
        }
        return own.sample(
            OwnPerformanceInput(
                apiLevel = Build.VERSION.SDK_INT,
                epoch = own.epoch,
                sampledElapsedMs = safely { SystemClock.elapsedRealtime() } ?: -1L,
                ownProcessCpuMs = safely { Process.getElapsedCpuTime() },
                ownJavaHeapUsedBytes = heap,
                ownNativeHeapUsedBytes = safely { Debug.getNativeHeapAllocatedSize() },
                // There is no registered app-specific timed event, so an
                // event-latency sample cannot be manufactured here.
                eventLatencyMs = null,
                processAlive = context.packageName == "org.androidmcp.nativeapp",
                appForeground = foreground,
            ),
        )
    }

    private inline fun <T> safely(block: () -> T): T? = try {
        block()
    } catch (_: RuntimeException) {
        null
    }
}
