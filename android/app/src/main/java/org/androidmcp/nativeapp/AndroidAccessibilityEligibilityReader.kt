package org.androidmcp.nativeapp

import android.Manifest
import android.app.KeyguardManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import org.androidmcp.protocol.AccessibilityEnvironment
import org.androidmcp.protocol.AccessibilityEligibilityPlan
import org.androidmcp.protocol.AccessibilityPurpose
import org.androidmcp.protocol.NativeAccessibilityPolicy

/**
 * Read-only, own-APK accessibility service declaration preflight.
 * NEVER opens Settings, grants a service, inspects UI, or performs gestures.
 * Current APK has no AccessibilityService and therefore reports absent.
 */
internal object AndroidAccessibilityEligibilityReader {
    fun plan(context: Context, foreground: Boolean): AccessibilityEligibilityPlan {
        val ownServiceDeclared = try {
            @Suppress("DEPRECATION")
            val info = context.packageManager.getPackageInfo(
                context.packageName,
                PackageManager.GET_SERVICES or PackageManager.GET_META_DATA,
            )
            info.services?.any { service ->
                service.permission == Manifest.permission.BIND_ACCESSIBILITY_SERVICE &&
                    service.metaData?.containsKey("android.accessibilityservice") == true
            } ?: false
        } catch (_: RuntimeException) {
            false
        }
        val unlocked = try {
            context.getSystemService(KeyguardManager::class.java)?.isDeviceLocked == false
        } catch (_: RuntimeException) {
            false
        }
        // Service declared != user-enabled or connected. This APK has no
        // registered AccessibilityService callback or approved caller grant;
        // neither state is ever inferred from a model or Settings string.
        return NativeAccessibilityPolicy(
            AccessibilityEnvironment(
                apiLevel = Build.VERSION.SDK_INT,
                serviceDeclared = ownServiceDeclared,
                userEnabled = false,
                serviceConnected = false,
                foreground = foreground,
                screenUnlocked = unlocked,
                reviewedUserPurpose = AccessibilityPurpose.VISIBLE_UI_INSPECTION,
            ),
        ).plan()
    }
}
