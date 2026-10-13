package org.androidmcp.nativeapp

import android.content.Context
import org.androidmcp.protocol.UiActionIntent
import org.androidmcp.protocol.UiActionPlanResult
import org.androidmcp.protocol.UiActionPlanState

/**
 * Explicitly disabled Android gesture/key dispatch boundary.
 *
 * No AccessibilityService is declared or enabled, and no live client Tool
 * may submit arbitrary taps, swipes, keyboard input or shell commands.
 * The pure Kotlin planner is for synthetic contract tests only.
 */
internal object AndroidUiActionPlanBoundary {
    @Suppress("UNUSED_PARAMETER")
    fun plan(context: Context, intent: UiActionIntent): UiActionPlanResult =
        UiActionPlanResult(
            state = UiActionPlanState.SERVICE_UNAVAILABLE,
            digest = null,
            requiresFreshAuthorization = false,
            idempotent = false,
        )
}
