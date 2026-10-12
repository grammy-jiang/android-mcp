package org.androidmcp.nativeapp

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
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
                network = networkReadiness(context),
            ),
        )
    }

    private fun networkReadiness(context: Context): NativeNetworkReadiness {
        // ACCESS_NETWORK_STATE is not on the current four-permission
        // Manifest allowlist. Return permission-denied instead of querying
        // ConnectivityManager speculatively or adding an implicit grant.
        val granted = safely {
            context.checkSelfPermission(Manifest.permission.ACCESS_NETWORK_STATE) ==
                PackageManager.PERMISSION_GRANTED
        }
        if (granted != true) return NativeNetworkReadiness.PERMISSION_DENIED
        return safely {
            val manager = context.getSystemService(ConnectivityManager::class.java)
                ?: return@safely NativeNetworkReadiness.UNAVAILABLE
            val active = manager.activeNetwork
                ?: return@safely NativeNetworkReadiness.OFFLINE
            val caps = manager.getNetworkCapabilities(active)
                ?: return@safely NativeNetworkReadiness.UNAVAILABLE
            when {
                caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) ->
                    NativeNetworkReadiness.VALIDATED
                caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) ->
                    NativeNetworkReadiness.INTERNET_CAPABLE
                else -> NativeNetworkReadiness.OFFLINE
            }
        } ?: NativeNetworkReadiness.UNAVAILABLE
    }

    private inline fun <T> safely(read: () -> T): T? = try {
        read()
    } catch (_: RuntimeException) {
        null
    }
}
