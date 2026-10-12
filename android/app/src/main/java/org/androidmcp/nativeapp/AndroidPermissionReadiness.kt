package org.androidmcp.nativeapp

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import org.androidmcp.protocol.AndroidPermissionProbe
import org.androidmcp.protocol.NativePermissionReadiness
import org.androidmcp.protocol.NativePermissionSnapshot

/**
 * Re-queries Android on each call; never trusts a cached Activity callback,
 * a same-device TCP peer, a fake approval, or the absence of an exception.
 *
 * No permission prompt or profile enablement happens here.
 */
internal object AndroidPermissionReadiness {
    fun snapshot(context: Context): NativePermissionSnapshot =
        NativePermissionReadiness(
            Build.VERSION.SDK_INT,
            AndroidPermissionProbe { permission ->
                try {
                    context.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED
                } catch (_: RuntimeException) {
                    null
                }
            },
        ).snapshot()

    fun canStartForeground(context: Context): Boolean =
        snapshot(context).foregroundMayStart()
}
