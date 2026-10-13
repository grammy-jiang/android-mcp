package org.androidmcp.nativeapp

import android.content.Context
import org.androidmcp.protocol.DualHostLeaseState
import org.androidmcp.protocol.FakeLeaseReceipt
import org.androidmcp.protocol.FakeLeaseRequest

/** N6.d no real Host/Native lease has been negotiated or activated. */
internal object AndroidMultiHostLeaseBoundary {
    @Suppress("UNUSED_PARAMETER")
    fun acquire(context: Context, request: FakeLeaseRequest): FakeLeaseReceipt =
        FakeLeaseReceipt(DualHostLeaseState.DENIED)
}
