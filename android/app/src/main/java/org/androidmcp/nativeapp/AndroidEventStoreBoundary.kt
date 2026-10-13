package org.androidmcp.nativeapp

import android.content.Context
import org.androidmcp.lifecycle.OwnEventPage
import org.androidmcp.lifecycle.OwnEventPageState

/**
 * N5.c private production boundary. No diagnostic subscription is enabled.
 *
 * The JVM-only NativeDiagnosticEventStore fixture uses an owner-locked,
 * app-private durable journal, but is not instantiated here or registered
 * with the public Native MCP server. A model/client-supplied Origin, cursor,
 * fake approval or process identifier cannot read stored diagnostics.
 */
internal object AndroidEventStoreBoundary {
    @Suppress("UNUSED_PARAMETER")
    fun read(context: Context, fakeCursor: String?): OwnEventPage =
        OwnEventPage(OwnEventPageState.DENIED)
}
