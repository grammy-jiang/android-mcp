package org.androidmcp.nativeapp

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView

/**
 * User-visible service mode. Activity visibility is NOT the service's lifetime.
 * Explicit permission, Start and Stop must remain under user control.
 */
class BackgroundMcpActivity : Activity() {
    private lateinit var status: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val pad = (24 * resources.displayMetrics.density).toInt()
            setPadding(pad, pad, pad, pad)
        }
        content.addView(TextView(this).apply {
            text = "Android MCP — persistent local service preview"
            textSize = 21f
        })
        status = TextView(this).apply {
            text = "Not started by this screen. User action and notifications required."
            textSize = 15f
        }
        content.addView(status)
        content.addView(Button(this).apply {
            text = "Start background local MCP"
            setOnClickListener { requestNotificationPermissionOrStart() }
        })
        content.addView(Button(this).apply {
            text = "Stop background local MCP"
            setOnClickListener { stopLocalService() }
        })
        setContentView(content)
    }

    private fun requestNotificationPermissionOrStart() {
        if (
            Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            status.text = "Approve notifications to show the service's persistent Stop action."
            requestPermissions(
                arrayOf(Manifest.permission.POST_NOTIFICATIONS),
                REQUEST_NOTIFICATIONS,
            )
            return
        }
        startLocalService()
    }

    private fun startLocalService() {
        try {
            val intent = Intent(this, NativeMcpForegroundService::class.java).apply {
                action = NativeMcpForegroundService.ACTION_START
            }
            startForegroundService(intent)
            status.text = "Start requested. Verify the ongoing notification; service is local-only."
        } catch (_: RuntimeException) {
            status.text = "Android refused foreground service startup."
        }
    }

    private fun stopLocalService() {
        stopService(Intent(this, NativeMcpForegroundService::class.java))
        status.text = "Stop requested; local MCP service will shut down."
    }

    @Suppress("DEPRECATION")
    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQUEST_NOTIFICATIONS) {
            if (grantResults.singleOrNull() == PackageManager.PERMISSION_GRANTED) {
                startLocalService()
            } else {
                status.text = "Notification permission denied; persistent service not started."
            }
        }
    }

    companion object {
        private const val REQUEST_NOTIFICATIONS = 183
    }
}
