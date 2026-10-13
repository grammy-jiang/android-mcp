package org.androidmcp.nativeapp

import android.content.Context
import org.androidmcp.protocol.SafeLaunchReceipt
import org.androidmcp.protocol.SafeLaunchState
import org.androidmcp.protocol.SyntheticSafeLaunchRequest

/** N7.c: no production Intent dispatch or third-party app launch. */
internal object AndroidExplicitLaunchBoundary {
    @Suppress("UNUSED_PARAMETER")
    fun launch(context: Context, request: SyntheticSafeLaunchRequest): SafeLaunchReceipt =
        SafeLaunchReceipt(SafeLaunchState.DENIED)

    fun realLaunchAllowed(): Boolean = false
}
