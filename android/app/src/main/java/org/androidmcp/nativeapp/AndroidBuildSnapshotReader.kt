package org.androidmcp.nativeapp

import android.content.Context
import android.os.Build
import org.androidmcp.protocol.NativeBuildSnapshot
import org.androidmcp.protocol.NativeBuildSnapshots

/**
 * Internal, permission-free Android Build adapter.
 * Deliberately excludes all persistent identifiers and firmware fingerprints.
 * No public MCP Tool is registered before the later authorization gate.
 */
internal object AndroidBuildSnapshotReader {
    fun read(context: Context): NativeBuildSnapshot =
        NativeBuildSnapshots.normalize(
            apiLevel = Build.VERSION.SDK_INT,
            osRelease = safe { Build.VERSION.RELEASE },
            manufacturer = safe { Build.MANUFACTURER },
            model = safe { Build.MODEL },
            supportedAbis = safe { Build.SUPPORTED_ABIS.toList() },
            appVersion = safe {
                @Suppress("DEPRECATION")
                context.packageManager.getPackageInfo(context.packageName, 0).versionName
            },
        )

    private inline fun <T> safe(block: () -> T): T? = try {
        block()
    } catch (_: RuntimeException) {
        null
    }
}
