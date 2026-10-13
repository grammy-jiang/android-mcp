package org.androidmcp.nativeapp

import android.app.admin.DevicePolicyManager
import android.content.Context
import android.os.Build
import org.androidmcp.protocol.FakeManagedDeviceEnvironment
import org.androidmcp.protocol.ManagedPolicyReceipt
import org.androidmcp.protocol.NativeManagedDevicePolicy

/**
 * N8.a own-app DeviceOwner check ONLY, no Device Admin receiver declared.
 * The installed ordinary Native APK cannot provision itself or change policy.
 */
internal object AndroidManagedDeviceBoundary {
    fun observeOwnApp(context: Context): ManagedPolicyReceipt {
        val isOwner = try {
            context.getSystemService(DevicePolicyManager::class.java)
                ?.isDeviceOwnerApp(context.packageName)
        } catch (_: RuntimeException) {
            null
        }
        // This APK deliberately has no DeviceAdminReceiver or provisioning,
        // so even an observed true is NOT treated as an authorized capability.
        return NativeManagedDevicePolicy().inspect(
            FakeManagedDeviceEnvironment(
                apiLevel = Build.VERSION.SDK_INT,
                ownDeviceOwnerVerified = isOwner,
                declaredAdminReceiver = false,
                ownedDisposableDevice = false,
                fakeUserConfirmed = false,
                fakeCallerVerified = false,
            ),
        )
    }

    fun realPolicyMutationAllowed(): Boolean = false
}
