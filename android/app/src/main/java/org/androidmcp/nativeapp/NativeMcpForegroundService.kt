package org.androidmcp.nativeapp

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import org.androidmcp.lifecycle.LifecycleDecision
import org.androidmcp.lifecycle.NativeServiceLifecycle
import org.androidmcp.lifecycle.ServicePhase
import java.util.concurrent.Executors
import java.util.concurrent.RejectedExecutionException

/**
 * Explicitly user-started, local-only MCP development service. All socket
 * effects use one worker; the pure state machine serializes START/STOP intent
 * across main-thread commands and asynchronous completion callbacks.
 *
 * Foreground notification is retained until verified listener shutdown.
 * No boot receiver, automatic restart, remote listener, or privileged tool.
 */
class NativeMcpForegroundService : Service() {
    private val worker = Executors.newSingleThreadExecutor()
    private val gateway = LocalMcpGateway()
    private val lifecycle = NativeServiceLifecycle()
    private val mainHandler = Handler(Looper.getMainLooper())

    // Accessed on Android main thread only (onStartCommand/onDestroy/posts).
    private var latestStartId = 0
    private var destroyed = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        latestStartId = startId
        when (intent?.action) {
            ACTION_START -> requestStart()
            ACTION_STOP -> requestStop()
            else -> requestStop()
        }
        return START_NOT_STICKY
    }

    private fun requestStart() {
        when (val decision = lifecycle.requestStart()) {
            is LifecycleDecision.Execute -> {
                try {
                    createNotificationChannel()
                    startForeground(
                        NOTIFICATION_ID,
                        createNotification("Read-only MCP starting; Stop available"),
                        ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE,
                    )
                } catch (_: RuntimeException) {
                    // If foreground promotion failed, the socket was not
                    // scheduled. Still run the common verified stop pathway.
                    lifecycle.startFailed(decision.generation)
                    requestStop()
                    return
                }
                submitStart(decision.generation)
            }
            LifecycleDecision.AlreadySatisfied -> Unit
            LifecycleDecision.Blocked -> Unit // STOPPING/UNKNOWN: user must retry.
        }
    }

    private fun submitStart(token: Long) {
        try {
            worker.execute {
                try {
                    gateway.start()
                    // A STOP request may have superseded this start while
                    // waiting on the same serial worker. The queued STOP
                    // remains authoritative; never undo or bypass it.
                    if (lifecycle.started(token)) {
                        mainHandler.post {
                            if (!destroyed && lifecycle.snapshot().phase == ServicePhase.RUNNING) {
                                updateNotification("Read-only loopback MCP running; tap Stop to end")
                            }
                        }
                    }
                } catch (_: Exception) {
                    if (lifecycle.startFailed(token)) {
                        when (val stop = lifecycle.requestStop()) {
                            is LifecycleDecision.Execute -> performStop(stop.generation)
                            else -> Unit
                        }
                    }
                }
            }
        } catch (_: RejectedExecutionException) {
            if (lifecycle.startFailed(token)) requestStop()
        }
    }

    private fun requestStop() {
        when (val decision = lifecycle.requestStop()) {
            is LifecycleDecision.Execute -> submitStop(decision.generation)
            LifecycleDecision.AlreadySatisfied -> {
                if (lifecycle.snapshot().phase == ServicePhase.STOPPED) finishStopped()
            }
            LifecycleDecision.Blocked -> Unit
        }
    }

    private fun submitStop(token: Long) {
        try {
            worker.execute { performStop(token) }
        } catch (_: RejectedExecutionException) {
            lifecycle.stopFailed(token)
            updateNotification("Shutdown could not be scheduled; use Android app Stop")
        }
    }

    private fun performStop(token: Long) {
        try {
            gateway.stop()
            if (lifecycle.stopped(token)) {
                mainHandler.post { finishStopped() }
            }
        } catch (_: Exception) {
            if (lifecycle.stopFailed(token)) {
                mainHandler.post {
                    updateNotification("Shutdown not confirmed; tap Stop again")
                }
            }
        }
    }

    /**
     * Stop only if no more recent START has been accepted. A STOP requested
     * during STARTING is queued behind START, never executed out of order.
     * latestStartId is accessed exclusively on Android's main thread.
     */
    private fun finishStopped() {
        if (destroyed || lifecycle.snapshot().phase != ServicePhase.STOPPED) return
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelfResult(latestStartId)
    }

    override fun onDestroy() {
        destroyed = true
        // Android may destroy the Service unexpectedly. Drain the worker after
        // any already queued work; do not block its main thread for shutdown.
        when (val decision = lifecycle.requestStop()) {
            is LifecycleDecision.Execute -> submitStop(decision.generation)
            else -> Unit
        }
        worker.shutdown()
        super.onDestroy()
    }

    private fun createNotificationChannel() {
        val notificationManager = getSystemService(NotificationManager::class.java)
        notificationManager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ID,
                "Android MCP local developer service",
                NotificationManager.IMPORTANCE_LOW,
            )
        )
    }

    private fun updateNotification(message: String) {
        if (destroyed) return
        getSystemService(NotificationManager::class.java)
            .notify(NOTIFICATION_ID, createNotification(message))
    }

    private fun createNotification(message: String): Notification {
        val stop = Intent(this, NativeMcpForegroundService::class.java).apply {
            action = ACTION_STOP
        }
        val pendingStop = PendingIntent.getService(
            this,
            0,
            stop,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        return Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("Android MCP local service")
            .setContentText(message)
            .setOngoing(true)
            .setCategory(Notification.CATEGORY_SERVICE)
            .addAction(Notification.Action.Builder(null, "Stop", pendingStop).build())
            .build()
    }

    companion object {
        const val ACTION_START = "org.androidmcp.nativeapp.START_LOCAL_SERVICE"
        const val ACTION_STOP = "org.androidmcp.nativeapp.STOP_LOCAL_SERVICE"
        private const val CHANNEL_ID = "android_mcp_local_developer"
        private const val NOTIFICATION_ID = 23166
    }
}
