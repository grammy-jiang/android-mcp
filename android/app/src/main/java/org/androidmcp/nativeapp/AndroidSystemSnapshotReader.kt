package org.androidmcp.nativeapp

import android.content.Context
import android.os.BatteryManager
import android.os.Build
import android.os.StatFs
import android.os.SystemClock
import org.androidmcp.protocol.NativeNetworkReadiness
import org.androidmcp.protocol.NativeSystemInputs
import org.androidmcp.protocol.NativeSystemSnapshot
import org.androidmcp.protocol.NativeSystemSnapshots

/**
 * Internal one-shot, on-demand, app-scoped observation. Does not monitor
 * connectivity, request permission, or inspect nearby networks/devices.
 */
internal object AndroidSystemSnapshotReader {
    fun read(context: Context): NativeSystemSnapshot {
        val storage = safely {
            val stat = StatFs(context.filesDir.absolutePath)
            stat.availableBytes to stat.totalBytes
        }
        val display = safely {
            context.resources.displayMetrics.let { it.widthPixels to it.heightPixels }
        }
        val battery = safely {
            context.getSystemService(BatteryManager::class.java)
                ?.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
        }
        return NativeSystemSnapshots.normalize(
            NativeSystemInputs(
                apiLevel = Build.VERSION.SDK_INT,
                elapsedMs = safely { SystemClock.elapsedRealtime() },
                batteryPercent = battery,
                appStorageAvailableBytes = storage?.first,
                appStorageTotalBytes = storage?.second,
                displayWidthPx = display?.first,
                displayHeightPx = display?.second,
                network = NativeNetworkReadiness.PERMISSION_DENIED,
            ),
        )
    }

    private inline fun <T> safely(read: () -> T): T? = try {
        read()
    } catch (_: RuntimeException) {
        null
    }
}
