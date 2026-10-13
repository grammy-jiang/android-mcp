package org.androidmcp.nativeapp

import android.content.Context

/**
 * N6.a remains unpaired and disabled in the production MCP server.
 * Only later independently reviewed enrollment can initialize a signing
 * owner using context.noBackupFilesDir and AndroidInstallationKeystoreProvider.
 * Merely connecting localhost or supplying an ADB serial cannot enroll.
 */
internal object AndroidInstallationIdentityBoundary {
    @Suppress("UNUSED_PARAMETER")
    fun publicStatus(context: Context): String =
        """{"schema_version":1,"identity_status":"unpaired","pairing_enabled":false,"mutation_enabled":false}"""
}
