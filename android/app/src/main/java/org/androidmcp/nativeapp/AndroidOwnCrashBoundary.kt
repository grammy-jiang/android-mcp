package org.androidmcp.nativeapp

import android.content.Context
import org.androidmcp.lifecycle.NativeCrashResult
import org.androidmcp.lifecycle.NativeCrashState

/**
 * Private default-off N5.a diagnostic boundary. The synthetic JVM fixture
 * is not an Android exception handler or unrestricted platform-log reader.
 *
 * A future reviewed owner may explicitly initialize a private reporter;
 * this public-facing application boundary itself never reads Logcat,
 * tombstones, ANR traces, other processes, or private crash artifacts.
 */
internal object AndroidOwnCrashBoundary {
    @Suppress("UNUSED_PARAMETER")
    fun read(context: Context): NativeCrashResult =
        NativeCrashResult(NativeCrashState.DENIED)
}
