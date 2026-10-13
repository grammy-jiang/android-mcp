package org.androidmcp.nativeapp

import android.content.Context
import org.androidmcp.protocol.FallbackAvailability
import org.androidmcp.protocol.FallbackDecision
import org.androidmcp.protocol.NativeHostFallbackPlan

/**
 * N5.d production Host/Native fallback remains explicitly non-operational.
 *
 * There is no Host connector, USB/ADB transport, ADB serial identity
 * shortcut, sensitive lease or automatic Host write route in this APK.
 * Only the fake cross-provider Kotlin status policy is unit-testable.
 */
internal object AndroidHostFallbackBoundary {
    @Suppress("UNUSED_PARAMETER")
    fun read(context: Context): NativeHostFallbackPlan =
        NativeHostFallbackPlan(
            decision = FallbackDecision.DENIED,
            host = FallbackAvailability.DENIED,
            native = FallbackAvailability.DENIED,
            providers = emptyList(),
        )
}
