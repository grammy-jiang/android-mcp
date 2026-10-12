package org.androidmcp.nativeapp

import android.content.Context
import org.androidmcp.lifecycle.NativeArtifactStore

/** Android app-owned private storage provider, not a public MCP Tool. */
internal object AndroidPrivateArtifacts {
    fun open(context: Context): NativeArtifactStore =
        NativeArtifactStore(context.noBackupFilesDir.toPath())
}
