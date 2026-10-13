package org.androidmcp.nativeapp

import android.content.Context
import org.androidmcp.lifecycle.FenceReceipt
import org.androidmcp.lifecycle.FenceStatus
import org.androidmcp.lifecycle.SyntheticFenceRequest

/**
 * N6.c durable synthetic fencing is not production authorization.
 * No app/Host mutation is started, and no fake lease can execute an action.
 * Real mutually accepted pairing and independently audited grant verifier
 * are necessary before any production lease can exist.
 */
internal object AndroidFenceBoundary {
    @Suppress("UNUSED_PARAMETER")
    fun check(context: Context, request: SyntheticFenceRequest): FenceReceipt =
        FenceReceipt(FenceStatus.DENIED, null)
}
