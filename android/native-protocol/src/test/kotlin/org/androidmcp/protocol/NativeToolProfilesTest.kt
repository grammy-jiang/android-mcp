package org.androidmcp.protocol

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class NativeToolProfilesTest {
    private val selected = setOf("native_build_snapshot", "native_system_snapshot", "native_app_health")
    private fun context(api: Int = 36, granted: Boolean? = true) = NativePreviewContext(
        apiLevel = api,
        packagePermissions = mapOf(
            "android.permission.INTERNET" to granted,
            "android.permission.POST_NOTIFICATIONS" to granted,
        ),
        selectedCapabilities = selected,
    )
    private fun permit(policy: NativeToolProfiles) =
        SyntheticPreviewPermit(policy.epoch, "http://127.0.0.1:38765", true)

    @Test
    fun tN1D01UnauthenticatedPublicToolsListHasOneMinimalStatusOnly() {
        val policy = NativeToolProfiles()
        for (modelApproved in listOf(false, true)) {
            val tools = policy.liveTools(modelApproved)
            assertEquals(listOf("device_status"), tools.map { it.name })
            assertFalse(tools.any { it.name.contains("screen") || it.name.contains("package") })
            assertEquals(policy.publicTools(), tools)
            assertEquals("Local read-only Native MCP availability, no device data or control.",
                tools.single().description)
        }
    }

    @Test
    fun tN1D02SyntheticApprovedFocusedToolsHaveStrictInputAndOutputSchema() {
        val policy = NativeToolProfiles()
        val tools = policy.syntheticTools(permit(policy), context())
        assertEquals(listOf(
            "device_status", "native_build_snapshot", "native_system_snapshot", "native_app_health"
        ), tools.map { it.name })
        for (tool in tools.drop(1)) {
            assertTrue(tool.readOnly)
            assertEquals("object", tool.inputSchema.getValue("type").jsonPrimitive.content)
            assertEquals("false", tool.inputSchema.getValue("additionalProperties").jsonPrimitive.content)
            assertTrue(tool.inputSchema.getValue("properties").jsonObject.isEmpty())
            val output = tool.outputSchema!!
            assertEquals("object", output.getValue("type").jsonPrimitive.content)
            assertEquals("false", output.getValue("additionalProperties").jsonPrimitive.content)
            assertTrue(output.getValue("properties").jsonObject.containsKey("schema_version"))
            assertTrue(output.getValue("required").jsonArray.any {
                it.jsonPrimitive.content == "schema_version"
            })
            assertTrue(tool.description.contains("Synthetic"))
        }
    }

    @Test
    fun tN1D03UnapprovedProfileApiOrPermissionsCannotShowFocusedTool() {
        val policy = NativeToolProfiles()
        assertEquals(1, policy.syntheticTools(null, context()).size)
        assertEquals(1, policy.syntheticTools(permit(policy), context(29)).size)
        assertEquals(1, policy.syntheticTools(permit(policy), context(granted = false)).size)
        assertEquals(1, policy.syntheticTools(permit(policy), context(granted = null)).size)
        assertEquals(1, policy.syntheticTools(permit(policy), context().copy(
            selectedCapabilities = setOf("native_screen_capture")
        )).size)
        assertEquals(1, policy.liveTools(approvedByModel = true).size)
    }

    @Test
    fun tN1D04OriginProfileEpochAndReconnectCannotReuseStaleSyntheticGrant() {
        val previous = NativeToolProfiles()
        val next = NativeToolProfiles()
        assertEquals(4, previous.syntheticTools(permit(previous), context()).size)
        assertEquals(1, next.syntheticTools(permit(previous), context()).size)
        assertEquals(1, next.syntheticTools(permit(next).copy(origin = "https://evil.example"),
            context()).size)
        assertEquals(1, next.syntheticTools(permit(next).copy(testSignature = false),
            context()).size)
        val revoked = context().copy(packagePermissions =
            mapOf("android.permission.INTERNET" to false))
        assertEquals(1, next.syntheticTools(permit(next), revoked).size)
    }

    @Test
    fun tN1D05TypedPreviewErrorsAndMetadataNeverClaimMutatingExecution() {
        val policy = NativeToolProfiles()
        for (status in PreviewStatus.entries) {
            val result = policy.previewCall("native_system_snapshot", status)
            assertEquals(status, result.status)
            assertEquals(status.name.lowercase(),
                result.structuredContent.getValue("status").jsonPrimitive.content)
            assertEquals("true",
                result.structuredContent.getValue("synthetic_only").jsonPrimitive.content)
            assertFalse(result.structuredContent.toString().contains("device_id"))
            assertTrue(result.structuredContent.toString().toByteArray().size < 4096)
        }
        val unknown = policy.previewCall("native_tap", PreviewStatus.SUCCESS)
        assertEquals(PreviewStatus.DENIED, unknown.status)
        assertFalse(policy.syntheticTools(permit(policy), context()).any { !it.readOnly })
    }

    @Test
    fun tN1D06PublicV1StatusAndHostCatalogRemainUnmodified() {
        val policy = NativeToolProfiles()
        val names = policy.publicTools().map { it.name }
        assertEquals(listOf("device_status"), names)
        val status = Json.parseToJsonElement(NativeLocalStatus.encode()).jsonObject
        assertEquals("1", status.getValue("schema_version").jsonPrimitive.content)
        assertEquals("android", status.getValue("runtime").jsonPrimitive.content)
        assertEquals(5, status.size)
        assertEquals(0, status.getValue("devices").jsonArray.size)
        assertEquals(0, status.getValue("errors").jsonArray.size)
        val guard = NativeLocalCallerGuard()
        assertFalse(guard.authorizeSensitive(LocalHttpRequest(), "native_build_snapshot").allowed)
    }
}
