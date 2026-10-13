package org.androidmcp.protocol

import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.security.MessageDigest
import java.util.Collections
import java.util.IdentityHashMap
import java.util.UUID

/**
 * N3.e synthetic-only UI hierarchy policy. No Android AccessibilityService,
 * window inspection, gesture API, device credentials or real UI node access.
 */
enum class UiTreeStatus {
    SYNTHETIC_ONLY, PARTIAL, DENIED, SERVICE_UNAVAILABLE, STALE, REVOKED,
    LOCKED, SECURE_WINDOW, UNSUPPORTED,
}
enum class UiNodeRole {
    ROOT, BUTTON, TEXT, IMAGE, INPUT, CHECKBOX, LIST, ITEM, REDACTED, UNKNOWN,
}

/**
 * Test fixture intentionally is NOT a data class: Any.toString() cannot
 * print raw text/contentDescription in diagnostics accidentally.
 */
class FakeUiNode(
    val sourceId: String,
    val role: UiNodeRole,
    val packageName: String,
    val text: String? = null,
    val contentDescription: String? = null,
    val isPassword: Boolean = false,
    val visible: Boolean = true,
    val focused: Boolean = false,
    val children: MutableList<FakeUiNode> = mutableListOf(),
)

/**
 * All context fields are fake locally injected test values. This is not
 * genuine Android consent or usable as an MCP caller-authentication grant.
 */
data class SyntheticTreeContext(
    val apiLevel: Int,
    val processEpoch: String,
    val callerAuthenticated: Boolean,
    val fakeUserConsent: Boolean,
    val serviceDeclared: Boolean,
    val serviceEnabled: Boolean,
    val serviceConnected: Boolean,
    val appForeground: Boolean,
    val screenUnlocked: Boolean,
    val secureWindow: Boolean,
    val windowVisible: Boolean,
    val expectedPackage: String,
    val nodeEpoch: String,
)

/** No text, descriptions, labels, positions, node IDs or other-app data. */
data class SafeUiNode(
    val handle: String,
    val role: UiNodeRole,
    val focused: Boolean,
    val parentHandle: String?,
    val depth: Int,
)

data class SyntheticTreeResult(
    val status: UiTreeStatus,
    val nodes: List<SafeUiNode>,
    val truncated: Boolean,
) {
    fun encode(): String = buildJsonObject {
        put("schema_version", 1)
        put("status", status.name.lowercase())
        put("synthetic_only", true)
        put("live_read_executed", false)
        put("read_only", true)
        put("truncated", truncated)
        put("nodes", buildJsonArray {
            for (node in nodes) {
                add(buildJsonObject {
                    put("handle", node.handle)
                    put("role", node.role.name.lowercase())
                    put("focused", node.focused)
                    put("parent_handle", node.parentHandle?.let(::JsonPrimitive) ?: JsonNull)
                    put("depth", node.depth)
                })
            }
        })
    }.toString()
}

/**
 * Bounded, process-local fake hierarchy reader. An OS Accessibility grant,
 * screen-unlock, foreground or other-app visibility can NEVER be obtained by
 * creating this object. Production reads and UI actions always remain denied.
 */
class NativeSyntheticUiTree {
    val processEpoch: String = UUID.randomUUID().toString()
    var nodeEpoch: String = UUID.randomUUID().toString()
        private set
    private val salt = UUID.randomUUID().toString()
    private var revoked = false

    private data class Pending(
        val node: FakeUiNode,
        val parent: String?,
        val depth: Int,
    )

    @Synchronized
    fun read(context: SyntheticTreeContext, root: FakeUiNode?): SyntheticTreeResult {
        fun deny(status: UiTreeStatus) =
            SyntheticTreeResult(status, emptyList(), truncated = false)
        if (revoked) return deny(UiTreeStatus.REVOKED)
        if (context.processEpoch != processEpoch ||
            context.nodeEpoch != nodeEpoch
        ) return deny(UiTreeStatus.STALE)
        if (context.apiLevel !in 30..100) return deny(UiTreeStatus.UNSUPPORTED)
        if (!context.serviceDeclared || !context.serviceEnabled ||
            !context.serviceConnected
        ) return deny(UiTreeStatus.SERVICE_UNAVAILABLE)
        if (!context.screenUnlocked) return deny(UiTreeStatus.LOCKED)
        if (context.secureWindow) return deny(UiTreeStatus.SECURE_WINDOW)
        if (!context.callerAuthenticated || !context.fakeUserConsent ||
            !context.appForeground || !context.windowVisible ||
            !validPackage(context.expectedPackage)
        ) return deny(UiTreeStatus.DENIED)
        if (root == null || !root.visible ||
            root.packageName != context.expectedPackage
        ) return deny(UiTreeStatus.DENIED)

        val visited = Collections.newSetFromMap(
            IdentityHashMap<FakeUiNode, Boolean>(),
        )
        val usedHandles = HashSet<String>()
        val pending = ArrayDeque<Pending>()
        pending.add(Pending(root, null, 0))
        val output = ArrayList<SafeUiNode>(MAX_NODES)
        var truncated = false
        while (pending.isNotEmpty()) {
            if (output.size >= MAX_NODES) {
                truncated = true
                break
            }
            val item = pending.removeLast()
            val node = item.node
            if (!visited.add(node)) {
                truncated = true // cycle / duplicate object reference
                continue
            }
            if (item.depth > MAX_DEPTH) {
                truncated = true
                continue
            }
            if (!node.visible || node.packageName != context.expectedPackage ||
                !validSourceId(node.sourceId)
            ) {
                truncated = true
                continue
            }
            val handle = handleFor(context.expectedPackage, node.sourceId)
            if (!usedHandles.add(handle)) {
                truncated = true // duplicate raw ID must not alias nodes
                continue
            }
            val redacted = node.isPassword || node.role == UiNodeRole.INPUT
            output.add(
                SafeUiNode(
                    handle = handle,
                    role = if (redacted) UiNodeRole.REDACTED else node.role,
                    focused = !redacted && node.focused,
                    parentHandle = item.parent,
                    depth = item.depth,
                ),
            )
            if (redacted) continue // never traverse a password subtree
            if (item.depth >= MAX_DEPTH) {
                if (node.children.isNotEmpty()) truncated = true
                continue
            }
            // An attacker-controlled fixture can advertise millions of
            // children. Examine/push a bounded prefix without copying them.
            val remaining = MAX_NODES - output.size
            val n = minOf(node.children.size, remaining)
            if (n < node.children.size) truncated = true
            for (i in n - 1 downTo 0) {
                pending.add(Pending(node.children[i], handle, item.depth + 1))
            }
        }
        return SyntheticTreeResult(
            status = if (truncated) UiTreeStatus.PARTIAL else UiTreeStatus.SYNTHETIC_ONLY,
            nodes = output,
            truncated = truncated,
        )
    }

    private fun handleFor(packageName: String, sourceId: String): String {
        // Salt changes on every new process-scoped instance. No raw source
        // IDs or private node text are reflected in a handle or response.
        val bytes = MessageDigest.getInstance("SHA-256")
            .digest("$salt|$nodeEpoch|$packageName|$sourceId".toByteArray(Charsets.UTF_8))
        return bytes.take(16).joinToString("") { "%02x".format(it) }
    }

    private fun validSourceId(id: String): Boolean =
        id.length in 1..64 && id.all {
            it in 'A'..'Z' || it in 'a'..'z' || it in '0'..'9' ||
                it in charArrayOf('_', '-', '.')
        }

    private fun validPackage(name: String): Boolean =
        name.length in 3..160 &&
            name.matches(Regex("[A-Za-z_][A-Za-z0-9_]*(?:\\.[A-Za-z_][A-Za-z0-9_]*)+"))

    /** Synthetic rotation/focus transition invalidates previous node handles. */
    @Synchronized
    fun invalidateWindow() {
        nodeEpoch = UUID.randomUUID().toString()
    }

    @Synchronized
    fun revoke() {
        revoked = true
    }

    fun liveReadAllowed(): Boolean = false
    fun dispatchCount(): Int = 0

    companion object {
        private const val MAX_NODES = 64
        private const val MAX_DEPTH = 8
    }
}
