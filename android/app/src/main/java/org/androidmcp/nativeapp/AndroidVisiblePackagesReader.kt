package org.androidmcp.nativeapp

import android.Manifest
import android.content.Context
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.os.Build
import org.androidmcp.protocol.NativePackageVisibility
import org.androidmcp.protocol.NativePackageVisibilitySampler
import org.androidmcp.protocol.NativePackageVisibilitySnapshot
import org.androidmcp.protocol.PackageVisibilityInput
import org.androidmcp.protocol.VisiblePackageCandidate

/**
 * Inert, one-shot PackageManager-visible **subset** adapter.
 * Android 11+ visibility filtering is enforced by the OS; a missing package
 * from this result may be hidden rather than absent. No public MCP Tool.
 */
internal object AndroidVisiblePackagesReader {
    fun read(context: Context): NativePackageVisibilitySnapshot {
        val manager = context.packageManager
        // Policy inspection is restricted to our own APK. If this fails,
        // never enumerate, and never infer that broad visibility is absent.
        val permissions = try {
            @Suppress("DEPRECATION")
            manager.getPackageInfo(context.packageName, PackageManager.GET_PERMISSIONS)
                .requestedPermissions ?: emptyArray()
        } catch (_: RuntimeException) {
            return NativePackageVisibility.unavailable()
        }
        val policy = PackageVisibilityInput(
            apiLevel = Build.VERSION.SDK_INT,
            broadPermissionDeclared = permissions.contains(Manifest.permission.QUERY_ALL_PACKAGES),
            crossUserRequested = false,
        )
        NativePackageVisibilitySampler().use { sampler ->
            return sampler.sample(policy, 1_500) {
                // Zero visibility-escalating flags: the platform has already
                // filtered this to apps currently visible to this app UID.
                @Suppress("DEPRECATION")
                manager.getInstalledPackages(0).map { info ->
                    val app = info.applicationInfo
                    VisiblePackageCandidate(
                        packageName = info.packageName,
                        isSystem = app?.let {
                            it.flags and ApplicationInfo.FLAG_SYSTEM != 0
                        },
                        enabled = app?.enabled,
                    )
                }
            }
        }
    }
}
