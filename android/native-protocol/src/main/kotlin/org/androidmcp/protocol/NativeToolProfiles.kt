package org.androidmcp.protocol

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.util.UUID

/**
 * Descriptors are private planning data. No Tool is actually registered on
 * the production Kotlin MCP server except the pre-existing device_status.
 */
data class NativeToolDescriptor(
    val name: String,
    val description: String,
    val inputSchema: JsonObject,
    val outputSchema: JsonObject?,
    val readOnly: Boolean,
)

enum class PreviewStatus { SUCCESS, PARTIAL, DENIED, UNSUPPORTED }

data class PreviewResult(val status: PreviewStatus, val structuredContent: JsonObject)

/**
 * Inert synthetic fixture. Caller-controlled HTTP headers or an LLM-provided
 * "approved" field must NEVER construct a real authorization from this type.
 */
data class SyntheticPreviewPermit(
    val processEpoch: String,
    val origin: String,
    val testSignature: Boolean,
)

data class NativePreviewContext(
    val apiLevel: Int,
    val packagePermissions: Map<String, Boolean?>,
    val selectedCapabilities: Set<String>,
)

/**
 * Live catalog is unconditionally public status-only. Fake preview catalogs
 * are allowed only for local non-deployed contract tests; they do not register
 * in Android/Ktor and cannot activate any underlying platform operation.
 */
class NativeToolProfiles {
    val epoch: String = UUID.randomUUID().toString()

    fun publicTools(): List<NativeToolDescriptor> = listOf(
        NativeToolDescriptor(
            "device_status",
            "Local read-only Native MCP availability, no device data or control.",
            buildJsonObject {},
            null,
            true,
        ),
    )

    // Intentionally ignores untrusted LLM/client approval claims.
    @Suppress("UNUSED_PARAMETER")
    fun liveTools(approvedByModel: Boolean): List<NativeToolDescriptor> = publicTools()

    fun syntheticTools(
        permit: SyntheticPreviewPermit?,
        context: NativePreviewContext,
    ): List<NativeToolDescriptor> {
        val known = FOCUSED_NAMES.toSet()
        if (permit?.processEpoch != epoch || !permit.testSignature ||
            permit.origin !in setOf(
                "http://127.0.0.1:38765",
                "http://localhost:38765",
            ) ||
            context.apiLevel !in 30..100 ||
            context.selectedCapabilities.isEmpty() ||
            !context.selectedCapabilities.all { it in known } ||
            context.packagePermissions["android.permission.INTERNET"] != true ||
            context.packagePermissions["android.permission.POST_NOTIFICATIONS"] != true
        ) return publicTools()

        val tools = FOCUSED_NAMES.filter { it in context.selectedCapabilities }
            .map { name ->
                NativeToolDescriptor(
                    name = name,
                    description = "Synthetic read-only contract fixture; no Android data or action.",
                    inputSchema = STRICT_EMPTY_INPUT,
                    outputSchema = PREVIEW_OUTPUT,
                    readOnly = true,
                )
            }
        return publicTools() + tools
    }

    /**
     * A fake preview can never execute a device Tool. Fixed JSON fields only;
     * unknown names and any attempted non-preview operation fail closed.
     */
    fun previewCall(name: String, status: PreviewStatus): PreviewResult {
        val actual = if (name !in FOCUSED_NAMES) PreviewStatus.DENIED else status
        return PreviewResult(actual, buildJsonObject {
            put("schema_version", 1)
            put("status", actual.name.lowercase())
            put("synthetic_only", true)
        })
    }

    companion object {
        private val FOCUSED_NAMES = listOf(
            "native_build_snapshot",
            "native_system_snapshot",
            "native_app_health",
        )
        private val STRICT_EMPTY_INPUT = buildJsonObject {
            put("type", "object")
            put("properties", buildJsonObject {})
            put("additionalProperties", false)
        }
        private val PREVIEW_OUTPUT = buildJsonObject {
            put("type", "object")
            put("properties", buildJsonObject {
                put("schema_version", buildJsonObject { put("type", "integer") })
                put("status", buildJsonObject {
                    put("type", "string")
                    put("enum", buildJsonArray {
                        PreviewStatus.entries.forEach { add(JsonPrimitive(it.name.lowercase())) }
                    })
                })
                put("synthetic_only", buildJsonObject { put("const", true) })
            })
            put("required", buildJsonArray {
                add(JsonPrimitive("schema_version"))
                add(JsonPrimitive("status"))
                add(JsonPrimitive("synthetic_only"))
            })
            put("additionalProperties", false)
        }
    }
}
