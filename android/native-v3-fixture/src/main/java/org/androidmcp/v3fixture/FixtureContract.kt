package org.androidmcp.v3fixture

object FixtureContract {
    const val DOCUMENT_AUTHORITY = "org.androidmcp.v3fixture.documents"
    const val ORACLE_AUTHORITY = "org.androidmcp.v3fixture.oracle"
    const val ROOT_ID = "v3-root"
    const val KNOWN_ID = "known-document"
    const val FILE_NAME = "android-mcp-v3-fixture.txt"
    const val COUNTER_PREFS = "fixture-counter"
    const val COUNTER_KEY = "count"
    const val BUTTON_ID = 1002
    const val TEXT_ID = 1003
    const val SURFACE_ID = 1004
    const val SECURE_OPEN_BUTTON_ID = 2000
    const val SECURE_PASSWORD_ID = 2001
    const val SECURE_SURFACE_ID = 2002
    const val SECURE_MARKER_COLOR = 0xFFF20BF2.toInt()
    const val SYNTHETIC_SECRET = "MCPV3-SYNTHETIC-SECRET-NO-USER-DATA"

    const val MAIN_COLOR = 0xFF102030.toInt()
    const val RED_COLOR = 0xFFFF4050.toInt()
    const val GREEN_COLOR = 0xFF15CB83.toInt()
    const val BLUE_COLOR = 0xFF1689FF.toInt()

    fun knownBytes(): ByteArray = "ANDROID-MCP-V3-FIXTURE-DOCUMENT-v1\n".toByteArray(Charsets.UTF_8)
}
