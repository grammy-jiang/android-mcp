package org.androidmcp.lifecycle

/**
 * N3 specialUse foreground-service mode is supported only on Android 14+.
 *
 * Android 11-13 still run the independent N2 Activity-only MCP mode. Do not
 * infer any privileged capability or caller authentication from this check.
 */
object NativeForegroundSupport {
    const val MIN_FOREGROUND_SERVICE_API = 34

    fun supported(apiLevel: Int): Boolean = apiLevel >= MIN_FOREGROUND_SERVICE_API
}
