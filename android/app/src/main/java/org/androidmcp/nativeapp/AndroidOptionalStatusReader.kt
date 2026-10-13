package org.androidmcp.nativeapp

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import org.androidmcp.protocol.NativeOptionalStatusSession
import org.androidmcp.protocol.OptionalStatusInput
import org.androidmcp.protocol.OptionalStatusSnapshot

/**
 * Internal, one-shot app-owned status only; no real sensor subscription,
 * location, microphone, contacts, notification content, Wi-Fi scan or
 * background tracking. The public Native MCP tool catalog is unchanged.
 */
internal object AndroidOptionalStatusReader {
    fun read(context: Context, appForeground: Boolean): OptionalStatusSnapshot {
        val old = AndroidSystemSnapshotReader.read(context)
        val postPermission = try {
            Build.VERSION.SDK_INT >= 33 &&
                context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) ==
                PackageManager.PERMISSION_GRANTED
        } catch (_: RuntimeException) {
            false
        }
        return NativeOptionalStatusSession().snapshot(
            OptionalStatusInput(
                apiLevel = Build.VERSION.SDK_INT,
                sampledElapsedMs = old.elapsedMs ?: -1L,
                batteryPercent = old.batteryPercent,
                displayWidthPx = old.displayWidthPx,
                displayHeightPx = old.displayHeightPx,
                // The APK deliberately does not declare ACCESS_NETWORK_STATE,
                // so never call network APIs as a fallback.
                networkPermissionGranted = false,
                networkValidated = null,
                notificationsPermissionGranted = postPermission,
                motionSensorSupported = false,
                foreground = appForeground,
            ),
        )
    }
}
