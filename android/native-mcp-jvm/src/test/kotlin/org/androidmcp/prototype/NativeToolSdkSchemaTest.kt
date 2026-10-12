package org.androidmcp.prototype

import io.modelcontextprotocol.kotlin.sdk.types.CallToolResult
import io.modelcontextprotocol.kotlin.sdk.types.TextContent
import io.modelcontextprotocol.kotlin.sdk.types.Tool
import io.modelcontextprotocol.kotlin.sdk.types.ToolAnnotations
import io.modelcontextprotocol.kotlin.sdk.types.ToolSchema
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.androidmcp.protocol.NativePreviewContext
import org.androidmcp.protocol.NativeToolProfiles
import org.androidmcp.protocol.PreviewStatus
import org.androidmcp.protocol.SyntheticPreviewPermit
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

/** N1.d convert the inert synthetic policy into official SDK types. */
class NativeToolSdkSchemaTest {
    private fun tools(): List<Tool> {
        val policy = NativeToolProfiles()
        val preview = policy.syntheticTools(
            SyntheticPreviewPermit(policy.epoch, "http://127.0.0.1:38765", true),
            NativePreviewContext(
                36,
                mapOf(
                    "android.permission.INTERNET" to true,
                    "android.permission.POST_NOTIFICATIONS" to true,
                ),
                setOf("native_build_snapshot", "native_system_snapshot", "native_app_health"),
            ),
        )
        return preview.drop(1).map { descriptor ->
            val output = descriptor.outputSchema!!
            Tool(
                name = descriptor.name,
                description = descriptor.description,
                inputSchema = ToolSchema(properties =
                    descriptor.inputSchema.getValue("properties").jsonObject),
                outputSchema = ToolSchema(
                    properties = output.getValue("properties").jsonObject,
                    required = output.getValue("required").jsonArray.map {
                        it.jsonPrimitive.content
                    },
                ),
                annotations = ToolAnnotations(
                    readOnlyHint = true,
                    destructiveHint = false,
                    idempotentHint = true,
                    openWorldHint = false,
                ),
            )
        }
    }

    @Test
    fun fakePolicyMetadataRoundTripsThroughActualOfficialKotlinSdkTypes() {
        val tools = tools()
        assertEquals(3, tools.size)
        for (tool in tools) {
            val json = Json.encodeToJsonElement(Tool.serializer(), tool).jsonObject
            assertEquals(tool.name, json.getValue("name").jsonPrimitive.content)
            val input = json.getValue("inputSchema").jsonObject
            assertEquals("object", input.getValue("type").jsonPrimitive.content)
            assertTrue(input.getValue("properties").jsonObject.isEmpty())
            val output = json.getValue("outputSchema").jsonObject
            assertEquals("object", output.getValue("type").jsonPrimitive.content)
            assertEquals(3, output.getValue("required").jsonArray.size)
            assertEquals("true", json.getValue("annotations")
                .jsonObject.getValue("readOnlyHint").jsonPrimitive.content)
            assertEquals("false", json.getValue("annotations")
                .jsonObject.getValue("destructiveHint").jsonPrimitive.content)
        }
    }

    @Test
    fun structuredSuccessPartialAndDenialUseSdkResultConsistently() {
        val policy = NativeToolProfiles()
        for (status in PreviewStatus.entries) {
            val local = policy.previewCall("native_app_health", status)
            val isError = status in setOf(PreviewStatus.DENIED, PreviewStatus.UNSUPPORTED)
            val sdk = CallToolResult(
                content = listOf(TextContent(text = "Synthetic preview only")),
                isError = isError,
                structuredContent = local.structuredContent,
            )
            val json = Json.encodeToJsonElement(CallToolResult.serializer(), sdk).jsonObject
            assertEquals(isError.toString(), json.getValue("isError").jsonPrimitive.content)
            assertEquals(status.name.lowercase(), json.getValue("structuredContent")
                .jsonObject.getValue("status").jsonPrimitive.content)
            assertEquals("true", json.getValue("structuredContent")
                .jsonObject.getValue("synthetic_only").jsonPrimitive.content)
            assertFalse(json.toString().contains("private_path"))
        }
    }
}
