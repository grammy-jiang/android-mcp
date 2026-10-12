package org.androidmcp.prototype

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

/**
 * JVM-only proof that the official Kotlin SDK can serve an MCP endpoint.
 * No Android device APIs are imported. No authenticated external entrypoint.
 * Not to be deployed, shipped as an APK, or treated as a device controller.
 */
fun developmentServer(): Server {
    val server = Server(
        serverInfo = Implementation(name = "android-mcp-kotlin-prototype", version = "0.1.0"),
        options = ServerOptions(
            capabilities = ServerCapabilities(
                tools = ServerCapabilities.Tools(listChanged = false),
            ),
        ),
    )
    server.addTool(
        name = "device_status",
        description = "JVM DEVELOPMENT PROTOTYPE ONLY: synthetic, no physical Android device.",
        inputSchema = ToolSchema(properties = buildJsonObject {}),
    ) { _ ->
        CallToolResult(
            content = listOf(
                TextContent(
                    text = """{"schema_version":1,"runtime":"android","capabilities":{"android.accessibility.observe":false,"android.accessibility.act":false,"android.privileged":false},"devices":[],"errors":[]}""",
                )
            )
        )
    }
    return server
}

fun main(args: Array<String>) {
    val port = args.singleOrNull()?.toIntOrNull() ?: 38765
    require(port in 1025..65535)
    embeddedServer(CIO, host = "127.0.0.1", port = port) {
        mcpStreamableHttp {
            developmentServer()
        }
    }.start(wait = true)
}
