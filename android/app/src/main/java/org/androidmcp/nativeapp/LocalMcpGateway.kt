package org.androidmcp.nativeapp

import io.ktor.server.cio.CIO
import io.ktor.server.engine.embeddedServer
import io.modelcontextprotocol.kotlin.sdk.server.Server
import io.modelcontextprotocol.kotlin.sdk.server.ServerOptions
import io.modelcontextprotocol.kotlin.sdk.server.mcpStreamableHttp
import io.modelcontextprotocol.kotlin.sdk.types.CallToolResult
import io.modelcontextprotocol.kotlin.sdk.types.Implementation
import io.modelcontextprotocol.kotlin.sdk.types.ServerCapabilities
import io.modelcontextprotocol.kotlin.sdk.types.TextContent
import io.modelcontextprotocol.kotlin.sdk.types.ToolSchema
import kotlinx.serialization.json.buildJsonObject
import org.androidmcp.protocol.NativeLocalStatus

/**
 * Local-only, read-only Android transport proof. This is not an authenticated
 * remote server, background service or privileged Android device broker.
 * Call start/stop from a dedicated worker, never from the Android UI thread.
 */
internal class LocalMcpGateway {
    private var stopListener: (() -> Unit)? = null

    @Synchronized
    fun start() {
        check(stopListener == null) { "Native MCP listener is already running" }
        val embedded = embeddedServer(CIO, host = "127.0.0.1", port = LOCAL_PORT) {
            mcpStreamableHttp { statusServer() }
        }
        embedded.start(wait = false)
        stopListener = { embedded.stop(gracePeriodMillis = 100, timeoutMillis = 1000) }
    }

    @Synchronized
    fun stop() {
        val current = stopListener
        stopListener = null
        current?.invoke()
    }

    private fun statusServer(): Server {
        val server = Server(
            serverInfo = Implementation(name = "android-mcp-native-local", version = "0.1.0"),
            options = ServerOptions(
                capabilities = ServerCapabilities(
                    tools = ServerCapabilities.Tools(listChanged = false),
                ),
            ),
        )
        server.addTool(
            name = "device_status",
            description = "Local read-only Native MCP availability, no device data or control.",
            inputSchema = ToolSchema(properties = buildJsonObject {}),
        ) { _ ->
            CallToolResult(
                content = listOf(TextContent(text = NativeLocalStatus.encode()))
            )
        }
        return server
    }

    companion object {
        // Never expose this untrusted, unpaired prototype to another network host.
        const val LOCAL_PORT: Int = 38765
    }
}
