package org.androidmcp.nativeapp

import android.content.Context
import org.androidmcp.protocol.AccessibilityEligibility
import org.androidmcp.protocol.SyntheticTreeResult
import org.androidmcp.protocol.UiTreeStatus

/**
 * An explicit production-disabled read interface. It does not use
 * AccessibilityNodeInfo, read any Android window or provide a frame or
 * gesture operation. Android's user-enabled service must be implemented
 * and independently security reviewed before real UI-tree access exists.
 */
internal object AndroidUiTreeReadiness {
    fun read(context: Context): SyntheticTreeResult {
        val eligibility = AndroidAccessibilityEligibilityReader.plan(
            context, foreground = false,
        )
        return SyntheticTreeResult(
            status = if (eligibility.state == AccessibilityEligibility.SERVICE_NOT_DECLARED) {
                UiTreeStatus.SERVICE_UNAVAILABLE
            } else {
                UiTreeStatus.DENIED
            },
            nodes = emptyList(),
            truncated = false,
        )
    }
}
