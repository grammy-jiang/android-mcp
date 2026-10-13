package org.androidmcp.nativeapp

import android.content.Context
import org.androidmcp.protocol.FakeInstallerConsentRequest
import org.androidmcp.protocol.FakeInstallerConsentReceipt
import org.androidmcp.protocol.NativeInstallerConsentStatus

/**
 * N7.b platform-side permanent deny. Neither a synthetic QEMU claim nor
 * model approval enables PackageInstaller consent or shell-backed installs.
 */
internal object AndroidInstallerConsentBoundary {
    @Suppress("UNUSED_PARAMETER")
    fun open(context: Context, request: FakeInstallerConsentRequest): FakeInstallerConsentReceipt =
        FakeInstallerConsentReceipt(NativeInstallerConsentStatus.BLOCKED)

    fun realConsentUiEnabled(): Boolean = false
    fun activeSessions(): Int = 0
}
