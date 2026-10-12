package org.androidmcp.nativeapp

import android.os.Build
import android.os.SystemClock
import org.androidmcp.lifecycle.NativeServiceLifecycle
import org.androidmcp.lifecycle.PortPhase
import org.androidmcp.lifecycle.ServicePhase
import org.androidmcp.protocol.NativeAppHealth
import org.androidmcp.protocol.NativeAppHealthInput
import org.androidmcp.protocol.NativeAppHealthSnapshots
import org.androidmcp.protocol.NativeAppMode
import org.androidmcp.protocol.NativeAppPhase
import org.androidmcp.protocol.NativeHealthError
import org.androidmcp.protocol.NativeStopCause

/**
 * Own-process-only, ephemeral health adapter. The actual Activity or FGS
 * owner must supply verified listener/notification evidence. Never enumerate
 * other apps, processes, packages or private Android framework records.
 *
 * No public MCP Tool or background observer is registered.
 */
internal object AndroidAppHealthReader {
    fun activity(
        localPortPhase: PortPhase,
        startedElapsedMs: Long?,
        stopCause: NativeStopCause = NativeStopCause.NONE,
        error: NativeHealthError = NativeHealthError.NONE,
    ): NativeAppHealth = snapshot(
        NativeAppMode.ACTIVITY,
        if (localPortPhase == PortPhase.READY) NativeAppPhase.RUNNING else
            if (localPortPhase == PortPhase.FREE) NativeAppPhase.STOPPED else
                NativeAppPhase.FAILED_CLOSED,
        localPortPhase == PortPhase.READY,
        false,
        startedElapsedMs,
        stopCause,
        error,
    )

    fun foregroundService(
        lifecycle: NativeServiceLifecycle,
        localPortPhase: PortPhase,
        notificationPromoted: Boolean,
        startedElapsedMs: Long?,
        stopCause: NativeStopCause = NativeStopCause.NONE,
        error: NativeHealthError = NativeHealthError.NONE,
    ): NativeAppHealth {
        val phase = when (lifecycle.snapshot().phase) {
            ServicePhase.STOPPED -> NativeAppPhase.STOPPED
            ServicePhase.STARTING -> NativeAppPhase.STARTING
            ServicePhase.RUNNING -> NativeAppPhase.RUNNING
            ServicePhase.STOPPING -> NativeAppPhase.STOPPING
            ServicePhase.FAILED_CLOSED -> NativeAppPhase.FAILED_CLOSED
        }
        return snapshot(
            NativeAppMode.FOREGROUND_SERVICE,
            phase,
            localPortPhase == PortPhase.READY,
            notificationPromoted,
            startedElapsedMs,
            stopCause,
            error,
        )
    }

    private fun snapshot(
        mode: NativeAppMode,
        phase: NativeAppPhase,
        listenerReady: Boolean,
        notificationPromoted: Boolean,
        startedElapsedMs: Long?,
        stopCause: NativeStopCause,
        error: NativeHealthError,
    ): NativeAppHealth = NativeAppHealthSnapshots.evaluate(
        NativeAppHealthInput(
            apiLevel = Build.VERSION.SDK_INT,
            mode = mode,
            ownerPhase = phase,
            listenerReady = listenerReady,
            foregroundNotificationPresent = notificationPromoted,
            processAlive = true, // the adapter executes inside its own process
            elapsedRealtimeMs = SystemClock.elapsedRealtime(),
            startedElapsedMs = startedElapsedMs,
            stopCause = stopCause,
            error = error,
        )
    )
}
