package org.androidmcp.nativeapp

import android.content.Context
import org.androidmcp.lifecycle.SafExportRequest
import org.androidmcp.lifecycle.SafExportResult
import org.androidmcp.lifecycle.SafExportStatus

/**
 * N4.d private deny-by-default Android SAF export boundary.
 *
 * The synthetic NativeSyntheticSafExporter intentionally has NO
 * ContentResolver/InputStream bridge. This adapter is not a live MCP Tool
 * and cannot read a real user-selected file until separately approved
 * user picker, provider identity, caller authentication and N6 fencing exist.
 */
internal object AndroidSafExportBoundary {
    @Suppress("UNUSED_PARAMETER")
    fun export(context: Context, request: SafExportRequest): SafExportResult =
        SafExportResult(status = SafExportStatus.DENIED)
}
