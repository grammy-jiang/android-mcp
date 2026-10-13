package org.androidmcp.nativeapp

import android.Manifest
import android.content.ComponentName
import android.content.Context
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.media.projection.MediaProjectionManager
import android.os.Build
import org.androidmcp.protocol.NativeProjectionConsent
import org.androidmcp.protocol.ProjectionConsentPlan
import org.androidmcp.protocol.ProjectionEnvironment

/**
 * Inert MediaProjection eligibility reader, never a grant or capture owner.
 * Does not launch system consent UI, consume a projection token, or start FGS.
 * Android framework readiness is checked only through allowed read-only APIs.
 */
internal object AndroidProjectionConsentReader {
    fun plan(context: Context, callerForeground: Boolean): ProjectionConsentPlan {
        val api = Build.VERSION.SDK_INT
        val managerPresent = safely {
            context.getSystemService(MediaProjectionManager::class.java) != null
        } ?: false
        val typeDeclared = if (api >= 34) {
            safely {
                @Suppress("DEPRECATION")
                val info = context.packageManager.getPackageInfo(
                    context.packageName, PackageManager.GET_PERMISSIONS,
                )
                val permissions = info.requestedPermissions ?: emptyArray()
                @Suppress("DEPRECATION")
                val service = context.packageManager.getServiceInfo(
                    ComponentName(context, NativeMcpForegroundService::class.java), 0,
                )
                permissions.contains(Manifest.permission.FOREGROUND_SERVICE_MEDIA_PROJECTION) &&
                    (service.foregroundServiceType and
                        ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION) != 0
            } ?: false
        } else {
            false
        }
        return NativeProjectionConsent(
            ProjectionEnvironment(
                apiLevel = api,
                projectionManagerPresent = managerPresent,
                mediaProjectionFgsTypeDeclared = typeDeclared,
                callerForeground = callerForeground,
            ),
        ).plan()
    }

    private inline fun <T> safely(read: () -> T): T? = try {
        read()
    } catch (_: RuntimeException) {
        null
    }
}
