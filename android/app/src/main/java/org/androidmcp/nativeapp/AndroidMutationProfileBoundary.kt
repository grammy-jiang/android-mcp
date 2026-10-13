package org.androidmcp.nativeapp

import android.content.Context
import org.androidmcp.protocol.MutationDenyReceipt
import org.androidmcp.protocol.NativeMutationStatus
import org.androidmcp.protocol.SyntheticMutationAttempt

/**
 * Production hard stop: N6.e never enables action dispatch or registers
 * a mutating MCP Tool. A fake signed grant, caller claim or synthetic lease
 * is not a real Android user authorization.
 */
internal object AndroidMutationProfileBoundary {
    @Suppress("UNUSED_PARAMETER")
    fun deny(context: Context, request: SyntheticMutationAttempt): MutationDenyReceipt =
        MutationDenyReceipt(NativeMutationStatus.DISABLED)

    fun realMutationAllowed(): Boolean = false
}
