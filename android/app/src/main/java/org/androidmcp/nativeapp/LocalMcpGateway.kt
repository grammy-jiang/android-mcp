package org.androidmcp.nativeapp

import io.ktor.server.cio.CIO
import io.ktor.server.engine.embeddedServer
import io.ktor.server.response.respondText
import io.ktor.server.routing.get
import io.ktor.server.routing.routing
import io.modelcontextprotocol.kotlin.sdk.server.Server
import io.modelcontextprotocol.kotlin.sdk.server.ServerOptions
import io.modelcontextprotocol.kotlin.sdk.server.mcpStreamableHttp
import io.modelcontextprotocol.kotlin.sdk.types.CallToolResult
import io.modelcontextprotocol.kotlin.sdk.types.Implementation
import io.modelcontextprotocol.kotlin.sdk.types.ServerCapabilities
import io.modelcontextprotocol.kotlin.sdk.types.TextContent
import io.modelcontextprotocol.kotlin.sdk.types.ToolSchema
import kotlinx.serialization.json.buildJsonObject
import org.androidmcp.lifecycle.LocalPortOwner
import org.androidmcp.protocol.NativeLocalStatus
import java.io.IOException
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.UUID

/**
 * Local, read-only Android MCP gateway. Two UI modes share one fixed loopback
 * endpoint; they must never advertise a second listener while the first mode
 * still owns the port.
 *
 * Port ownership is process-local only. It is NOT a cross-process fence,
 * caller authentication, or a Host/Native distributed lease.
 */
internal class LocalMcpGateway {
    private var shutdownListener: (() -> Unit)? = null

    @Synchronized
    fun start() {
        check(shutdownListener == null) { "This gateway already has a listener" }
        check(portOwner.reserve(this)) { "Another local MCP mode owns the port" }

        // Probe identity is an ephemeral correlation marker, NOT an auth key.
        // An unrelated process on the same TCP port must not satisfy readiness.
        val nonce = UUID.randomUUID().toString().replace("-", "")
        val probePath = "/_native_internal/ready/$nonce"
        val marker = "android-mcp-native-ready-$nonce"
        try {
            val engine = embeddedServer(CIO, host = "127.0.0.1", port = LOCAL_PORT) {
                routing {
                    get(probePath) {
                        call.respondText(marker)
                    }
                }
                mcpStreamableHttp { statusServer() }
            }
            shutdownListener = {
                engine.stop(gracePeriodMillis = 100, timeoutMillis = 1000)
            }
            engine.start(wait = false)
            check(awaitOwnReadiness(probePath, marker)) {
                "Native MCP engine did not prove its own loopback readiness"
            }
            check(portOwner.confirmReady(this)) {
                "Native MCP lost the process-local port reservation"
            }
        } catch (error: Exception) {
            // Best-effort cleanup still requires verified port closure before
            // releasing ownership; suppressed cleanup errors never mask the
            // original startup problem.
            try {
                stop()
            } catch (cleanup: Exception) {
                error.addSuppressed(cleanup)
            }
            throw error
        }
    }

    @Synchronized
    fun stop() {
        // The Activity's onStop can run even when its listener was never
        // started (for example, when the separate FGS owns the TCP port).
        if (!portOwner.ownedBy(this) && shutdownListener == null) return
        check(portOwner.beginStop(this)) { "Gateway cannot own shutdown" }

        var stopFailure: Exception? = null
        try {
            shutdownListener?.invoke()
        } catch (error: Exception) {
            stopFailure = error
        }

        // Ktor returning from stop(), or throwing, does NOT alone prove that
        // the listening port has been freed. Probe the Android kernel bind
        // state before releasing the process-local port owner.
        val released = awaitPortReleased()
        // An exception in Ktor shutdown may indicate other engine resources
        // were not released even if the kernel socket is now bindable.
        // Require BOTH a clean engine stop and independently verified port
        // closure before another mode can acquire the singleton listener.
        if (!portOwner.confirmStopped(this, released && stopFailure == null)) {
            val failure = IllegalStateException(
                "Native MCP shutdown not fully confirmed; port owner retained"
            )
            stopFailure?.let(failure::addSuppressed)
            throw failure
        }
        shutdownListener = null
    }

    private fun awaitOwnReadiness(path: String, marker: String): Boolean {
        repeat(50) {
            if (probeOwnHttp(path, marker)) return true
            Thread.sleep(50)
        }
        return false
    }

    private fun probeOwnHttp(path: String, marker: String): Boolean {
        try {
            Socket().use { socket ->
                socket.connect(InetSocketAddress("127.0.0.1", LOCAL_PORT), 250)
                socket.soTimeout = 250
                val request = (
                    "GET $path HTTP/1.1\r\n" +
                    "Host: 127.0.0.1\r\n" +
                    "Connection: close\r\n\r\n"
                )
                socket.getOutputStream().write(request.toByteArray(Charsets.US_ASCII))
                val bytes = ByteArray(2048)
                val body = StringBuilder()
                repeat(8) {
                    val count = socket.getInputStream().read(bytes)
                    if (count < 0) return false
                    body.append(String(bytes, 0, count, Charsets.UTF_8))
                    if (body.length > 8192) return false
                    if (body.contains(marker)) {
                        return body.startsWith("HTTP/1.1 200") ||
                            body.startsWith("HTTP/1.0 200")
                    }
                }
            }
        } catch (_: IOException) {
            // Startup can race TCP bind; caller retries with a fixed bound.
        }
        return false
    }

    private fun awaitPortReleased(): Boolean {
        repeat(50) {
            if (canBindPort()) return true
            Thread.sleep(50)
        }
        return false
    }

    private fun canBindPort(): Boolean = try {
        ServerSocket().use { socket ->
            socket.reuseAddress = true
            socket.bind(InetSocketAddress("127.0.0.1", LOCAL_PORT), 1)
            true
        }
    } catch (_: IOException) {
        false
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
        // Loopback only. Do not change without caller-auth and security review.
        const val LOCAL_PORT: Int = 38765
        private val portOwner = LocalPortOwner()
    }
}
