package org.androidmcp.nativeapp

import android.content.Context
import org.androidmcp.protocol.RootRecoveryReceipt
import org.androidmcp.protocol.RootRecoveryState
import org.androidmcp.protocol.SyntheticRootRecoveryRequest

/** N8.b: no native root, bootloader, ROM or shell recovery executor exists. */
internal object AndroidRootRecoveryBoundary {
    @Suppress("UNUSED_PARAMETER")
    fun execute(context: Context, request: SyntheticRootRecoveryRequest): RootRecoveryReceipt =
        RootRecoveryReceipt(RootRecoveryState.UNSUPPORTED)

    fun nativePrivilegeAllowed(): Boolean = false
}
