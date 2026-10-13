package org.androidmcp.nativeapp

import android.content.Context
import org.androidmcp.protocol.NativeInstallPlanReceipt
import org.androidmcp.protocol.NativeInstallPlanStatus
import org.androidmcp.protocol.SyntheticInstallPlanRequest

/**
 * N7.a never starts PackageInstaller. No Android user consent is presumed,
 * no ACTION_INSTALL_PACKAGE Intent is created, and no session is allocated.
 */
internal object AndroidPackageInstallerPlanBoundary {
    @Suppress("UNUSED_PARAMETER")
    fun deny(context: Context, request: SyntheticInstallPlanRequest): NativeInstallPlanReceipt =
        NativeInstallPlanReceipt(NativeInstallPlanStatus.DENIED)

    fun activeInstallerSessions(): Int = 0
    fun realPackageInstallAllowed(): Boolean = false
}
