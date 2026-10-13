package org.androidmcp.nativeapp

import android.content.Context
import org.androidmcp.lifecycle.SafImportState
import org.androidmcp.lifecycle.SyntheticSafImportPlan
import org.androidmcp.lifecycle.SyntheticSafImportRequest

/**
 * N4.e production-denying Android import boundary. No ContentResolver,
 * OutputStream, startActivity, ACTION_CREATE_DOCUMENT or file mutation.
 *
 * The Kotlin private-artifact verification is only a synthetic plan.
 * Genuine user selected WRITE URI and N6 caller authorization are necessary
 * before a separately reviewed Android writer could ever be enabled.
 */
internal object AndroidSafImportBoundary {
    @Suppress("UNUSED_PARAMETER")
    fun plan(context: Context, request: SyntheticSafImportRequest): SyntheticSafImportPlan =
        SyntheticSafImportPlan(
            state = SafImportState.DENIED,
            planId = null,
            bytesToWrite = null,
            sha256 = null,
        )
}
