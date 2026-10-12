package org.androidmcp.nativeapp

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.IBinder
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Explicitly user-started, local-only MCP development service. It cannot be
 * launched by other apps, auto-boot, or silently restart after process death.
 * Foreground notification always includes a user-visible Stop action.
 *
 * The only MCP tool is synthetic, bounded and read-only: device_status.
 */
class NativeMcpForegroundService : Service() {
    private val worker = Executors.newSingleThreadExecutor()
    private val gateway = LocalMcpGateway()
    private val started = AtomicBoolean(false)

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> {
                if (started.compareAndSet(false, true)) {
                    createNotificationChannel()
                    try {
                        startForeground(
                            NOTIFICATION_ID,
                            createNotification(),
                            ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE,
                        )
                    } catch (_: RuntimeException) {
                        started.set(false)
                        stopSelf()
                        return START_NOT_STICKY
                    }
                    worker.execute {
                        try {
                            gateway.start()
                        } catch (_: Exception) {
                            // Report neither transport errors nor device contents
                            // through an Android notification or MCP response.
                            gateway.stop()
                            started.set(false)
                            stopSelf()
                        }
                    }
                }
            }
            ACTION_STOP -> {
                started.set(false)
                stopForeground(STOP_FOREGROUND_REMOVE)
                worker.execute {
                    gateway.stop()
                    stopSelf()
                }
            }
            else -> stopSelf(startId)
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        started.set(false)
        worker.execute { gateway.stop() }
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

    private fun createNotification(): Notification {
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
            .setContentText("Read-only loopback server — tap Stop to end")
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
