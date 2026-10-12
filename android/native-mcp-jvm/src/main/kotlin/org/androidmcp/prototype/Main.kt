package org.androidmcp.prototype

import io.ktor.server.cio.CIO
import io.ktor.http.ContentType
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.server.application.ApplicationCallPipeline
import io.ktor.server.request.httpMethod
import io.ktor.server.request.path
import io.ktor.server.engine.embeddedServer
import io.ktor.server.response.respondText
import io.modelcontextprotocol.kotlin.sdk.server.Server
import io.modelcontextprotocol.kotlin.sdk.server.ServerOptions
import io.modelcontextprotocol.kotlin.sdk.server.mcpStreamableHttp
import io.modelcontextprotocol.kotlin.sdk.types.CallToolResult
import io.modelcontextprotocol.kotlin.sdk.types.Implementation
import io.modelcontextprotocol.kotlin.sdk.types.ServerCapabilities
import io.modelcontextprotocol.kotlin.sdk.types.TextContent
import io.modelcontextprotocol.kotlin.sdk.types.ToolSchema
import kotlinx.serialization.json.buildJsonObject
import org.androidmcp.protocol.LocalHttpRequest
import org.androidmcp.protocol.NativeLocalCallerGuard

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
    val localCallerGuard = NativeLocalCallerGuard()
    embeddedServer(CIO, host = "127.0.0.1", port = port) {
        intercept(ApplicationCallPipeline.Call) {
            val request = LocalHttpRequest(
                method = context.request.httpMethod.value,
                path = context.request.path(),
                host = context.request.headers[HttpHeaders.Host],
                origin = context.request.headers[HttpHeaders.Origin],
                remoteHost = context.request.local.remoteHost,
                contentLength = context.request.headers[HttpHeaders.ContentLength],
                transferEncoding = context.request.headers[HttpHeaders.TransferEncoding],
                headerCount = context.request.headers.names().size,
                headerBytes = context.request.headers.names().sumOf { name ->
                    name.length + (context.request.headers.getAll(name)?.sumOf {
                        it.length + 2
                    } ?: 0)
                },
                duplicateSecurityHeaders = listOf(
                    HttpHeaders.Host, HttpHeaders.Origin, HttpHeaders.ContentLength,
                    HttpHeaders.TransferEncoding,
                ).any { (context.request.headers.getAll(it)?.size ?: 0) > 1 },
            )
            val ticket = localCallerGuard.begin(request)
            try {
                if (!ticket.verdict.allowed) {
                    val response = "{\"error\":\"" + ticket.verdict.code + "\"}"
                    context.respondText(
                        response,
                        ContentType.Application.Json,
                        HttpStatusCode.fromValue(ticket.verdict.httpStatus),
                    )
                    finish()
                } else {
                    proceed()
                }
            } finally {
                ticket.close()
            }
        }
        mcpStreamableHttp {
            developmentServer()
        }
    }.start(wait = true)
}
