package org.androidmcp.protocol

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class NativeSyntheticUiTreeTest {
    private val ownPackage = "org.androidmcp.synthetic"
    private fun context(tree: NativeSyntheticUiTree, api: Int = 36) = SyntheticTreeContext(
        api, tree.processEpoch, true, true, true, true, true, true,
        true, false, true, ownPackage, tree.nodeEpoch,
    )
    private fun sample(): FakeUiNode {
        val root = FakeUiNode("raw-root-id", UiNodeRole.ROOT, ownPackage)
        root.children.add(FakeUiNode("private-button-id", UiNodeRole.BUTTON, ownPackage,
            text = "secret-private-label", focused = true))
        root.children.add(FakeUiNode("another-node-id", UiNodeRole.TEXT, ownPackage,
            contentDescription = "secret-description"))
        return root
    }

    @Test
    fun tN3E01ApprovedFakeTreeHasBoundedRolesVisibleFocusAndStableEphemeralHandles() {
        val tree = NativeSyntheticUiTree()
        val first = tree.read(context(tree), sample())
        assertEquals(UiTreeStatus.SYNTHETIC_ONLY, first.status)
        assertEquals(listOf(UiNodeRole.ROOT, UiNodeRole.BUTTON, UiNodeRole.TEXT),
            first.nodes.map { it.role })
        assertEquals(listOf(false, true, false), first.nodes.map { it.focused })
        assertEquals(first.nodes[0].handle, first.nodes[1].parentHandle)
        assertTrue(first.nodes.all { it.handle.matches(Regex("[a-f0-9]{32}")) })
        assertFalse(first.truncated)
        assertEquals(first.nodes.map { it.handle },
            tree.read(context(tree), sample()).nodes.map { it.handle })
        val wire = Json.parseToJsonElement(first.encode()).jsonObject
        assertEquals("true", wire.getValue("synthetic_only").jsonPrimitive.content)
        assertEquals(3, wire.getValue("nodes").jsonArray.size)
    }

    @Test
    fun tN3E02PasswordSecureLockedHiddenAndOtherAppTextAreNeverReturned() {
        val tree = NativeSyntheticUiTree()
        val root = sample()
        root.children.add(FakeUiNode("pass", UiNodeRole.INPUT, ownPackage,
            text = "password=super-secret", isPassword = true, focused = true))
        root.children.add(FakeUiNode("other", UiNodeRole.TEXT, "org.other.private",
            text = "bank account", contentDescription = "secret token"))
        root.children.add(FakeUiNode("hidden", UiNodeRole.TEXT, ownPackage,
            text = "hidden confidential data", visible = false))
        val result = tree.read(context(tree), root)
        val wire = result.encode().lowercase()
        for (forbidden in listOf("password", "super-secret", "bank account",
            "secret token", "confidential", "private-button-id",
            "secret-private-label", "secret-description", "raw-root-id")) {
            assertFalse(wire.contains(forbidden))
        }
        assertTrue(result.nodes.none { it.role == UiNodeRole.INPUT })
        assertTrue(result.nodes.none { it.role == UiNodeRole.REDACTED && it.focused })
        assertEquals(UiTreeStatus.LOCKED,
            tree.read(context(tree).copy(screenUnlocked = false), root).status)
        assertEquals(UiTreeStatus.SECURE_WINDOW,
            tree.read(context(tree).copy(secureWindow = true), root).status)
        assertTrue(tree.read(context(tree).copy(secureWindow = true), root).nodes.isEmpty())
    }

    @Test
    fun tN3E03NoServiceRevokedStaleOrUnrelatedCallerNeverGetsOldTree() {
        val tree = NativeSyntheticUiTree()
        val valid = tree.read(context(tree), sample())
        assertEquals(3, valid.nodes.size)
        for (invalid in listOf(
            context(tree).copy(serviceDeclared = false),
            context(tree).copy(serviceEnabled = false),
            context(tree).copy(serviceConnected = false),
            context(tree).copy(fakeUserConsent = false),
            context(tree).copy(callerAuthenticated = false),
            context(tree).copy(processEpoch = "stale-epoch"),
            context(tree).copy(windowVisible = false),
            context(tree).copy(appForeground = false),
        )) {
            val denied = tree.read(invalid, sample())
            assertTrue(denied.status != UiTreeStatus.SYNTHETIC_ONLY)
            assertTrue(denied.nodes.isEmpty())
        }
        tree.revoke()
        assertEquals(UiTreeStatus.REVOKED, tree.read(context(tree), sample()).status)
        assertTrue(tree.read(context(tree), sample()).nodes.isEmpty())
        val next = NativeSyntheticUiTree()
        assertNotEquals(tree.processEpoch, next.processEpoch)
        assertEquals(UiTreeStatus.STALE, next.read(context(tree), sample()).status)
    }

    @Test
    fun tN3E04HugeDeepCyclicHierarchyIsStrictlyTruncatedWithoutCrashes() {
        val tree = NativeSyntheticUiTree()
        val root = FakeUiNode("cyclic-root", UiNodeRole.ROOT, ownPackage)
        for (i in 0 until 1500) {
            root.children.add(FakeUiNode("wide-$i", UiNodeRole.ITEM, ownPackage))
        }
        var parent = root
        for (depth in 0..50) {
            val child = FakeUiNode("depth-$depth", UiNodeRole.LIST, ownPackage)
            parent.children.add(child)
            parent = child
        }
        parent.children.add(root)
        val outcome = tree.read(context(tree), root)
        assertEquals(UiTreeStatus.PARTIAL, outcome.status)
        assertTrue(outcome.truncated)
        assertTrue(outcome.nodes.size <= 64)
        assertTrue(outcome.nodes.all { it.depth <= 8 })
        assertTrue(outcome.encode().toByteArray().size <= 16_384)
    }

    @Test
    fun tN3E05Api30_33_34_36SimulatedHierarchyButNotAndroidConsentClaim() {
        for (api in listOf(30, 33, 34, 36)) {
            val tree = NativeSyntheticUiTree()
            assertEquals(UiTreeStatus.SYNTHETIC_ONLY,
                tree.read(context(tree, api), sample()).status)
            assertFalse(tree.liveReadAllowed())
            assertEquals(0, tree.dispatchCount())
        }
        val before30 = NativeSyntheticUiTree()
        assertEquals(UiTreeStatus.UNSUPPORTED,
            before30.read(context(before30, 29), sample()).status)
        assertFalse(before30.liveReadAllowed())
    }

    @Test
    fun tN3E06ReadTreeDoesNotDispatchGestureOrExposePrivilegedMcpTool() {
        val tree = NativeSyntheticUiTree()
        tree.read(context(tree), sample())
        tree.read(context(tree), sample())
        assertEquals(0, tree.dispatchCount())
        assertFalse(tree.liveReadAllowed())
        assertEquals(listOf("device_status"), NativeToolProfiles().liveTools(true).map { it.name })
        assertFalse(NativeLocalStatus.encode().contains("ui_tree"))
    }

    @Test
    fun repeatedIdsCyclicSubtreesAndOverDepthReturnPartialWithoutAlias() {
        val policy = NativeSyntheticUiTree()
        val root = FakeUiNode("root", UiNodeRole.ROOT, ownPackage)
        root.children.add(FakeUiNode("dup-id", UiNodeRole.BUTTON, ownPackage))
        root.children.add(FakeUiNode("dup-id", UiNodeRole.BUTTON, ownPackage))
        root.children.add(root)
        val result = policy.read(context(policy), root)
        assertEquals(UiTreeStatus.PARTIAL, result.status)
        assertEquals(2, result.nodes.size)
        assertTrue(result.nodes.map { it.handle }.toSet().size == result.nodes.size)
        assertTrue(result.encode().toByteArray().size <= 16_384)
    }

    @Test
    fun anotherProcessCannotGuessStableHandlesAndNoTextEverSerialized() {
        val first = NativeSyntheticUiTree()
        val second = NativeSyntheticUiTree()
        val sensitive = FakeUiNode(
            "node-sensitive", UiNodeRole.TEXT, ownPackage,
            text = "Bank access PIN: 9837",
            contentDescription = "Address: 17 Private Road",
            focused = true,
        )
        val a = first.read(context(first), sensitive)
        val b = second.read(context(second), sensitive)
        assertEquals(UiTreeStatus.SYNTHETIC_ONLY, a.status)
        assertEquals(UiTreeStatus.SYNTHETIC_ONLY, b.status)
        assertNotEquals(a.nodes.single().handle, b.nodes.single().handle)
        assertEquals(a.nodes.single().handle,
            first.read(context(first), sensitive).nodes.single().handle)
        for (result in listOf(a, b)) {
            val text = result.encode()
            assertFalse(text.contains("9837"))
            assertFalse(text.contains("Private Road"))
            assertFalse(text.contains("node-sensitive"))
            assertFalse(text.contains("Address"))
        }
    }

    @Test
    fun rotationOrWindowChangeInvalidatesOldHandlesWithoutDispatch() {
        val policy = NativeSyntheticUiTree()
        val oldContext = context(policy)
        val first = policy.read(oldContext, sample())
        val firstHandles = first.nodes.map { it.handle }
        policy.invalidateWindow()
        val denied = policy.read(oldContext, sample())
        assertEquals(UiTreeStatus.STALE, denied.status)
        assertTrue(denied.nodes.isEmpty())
        val latest = policy.read(context(policy), sample())
        assertEquals(UiTreeStatus.SYNTHETIC_ONLY, latest.status)
        assertNotEquals(firstHandles, latest.nodes.map { it.handle })
        assertEquals(0, policy.dispatchCount())
        assertFalse(policy.liveReadAllowed())
    }

    @Test
    fun extremeInputTextAndPasswordDescendantsCannotBypassNodeLimit() {
        val policy = NativeSyntheticUiTree()
        val root = FakeUiNode("root", UiNodeRole.ROOT, ownPackage)
        val password = FakeUiNode(
            "pwd", UiNodeRole.INPUT, ownPackage,
            text = "card=44332211," + "SECRET".repeat(20_000),
            isPassword = true,
            focused = true,
        )
        password.children.add(FakeUiNode("under-pwd", UiNodeRole.TEXT, ownPackage,
            text = "reveal-me"))
        root.children.add(password)
        for (i in 0..1000) {
            root.children.add(FakeUiNode("node-$i", UiNodeRole.ITEM, ownPackage,
                text = "private!".repeat(500)))
        }
        val result = policy.read(context(policy), root)
        assertEquals(UiTreeStatus.PARTIAL, result.status)
        assertTrue(result.nodes.size <= 64)
        assertTrue(result.encode().toByteArray().size <= 16_384)
        assertFalse(result.encode().contains("SECRET"))
        assertFalse(result.encode().contains("reveal-me"))
        assertFalse(result.encode().contains("44332211"))
        assertTrue(result.nodes.none { it.role == UiNodeRole.INPUT })
        assertTrue(result.nodes.none { it.role == UiNodeRole.REDACTED && it.focused })
        assertTrue(result.nodes.none { it.depth > 8 })
    }
}
