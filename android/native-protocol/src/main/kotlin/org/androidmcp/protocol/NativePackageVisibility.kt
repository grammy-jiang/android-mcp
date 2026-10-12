package org.androidmcp.protocol

import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.util.concurrent.ExecutionException
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException

/**
 * PackageManager on Android 11+ returns an OS-filtered *visible* subset.
 * The absence of a package from that subset never proves it is uninstalled.
 */
enum class PackageVisibilityState { FILTERED, PARTIAL, DENIED, UNSUPPORTED, UNAVAILABLE }
enum class VisiblePackageLookup { VISIBLE, NOT_VISIBLE_OR_MISSING, DENIED }

data class VisiblePackageCandidate(
    val packageName: String,
    val isSystem: Boolean?,
    val enabled: Boolean?,
)

data class VisiblePackageRecord(
    val packageName: String,
    val isSystem: Boolean,
    val enabled: Boolean,
)

data class PackageVisibilityInput(
    val apiLevel: Int,
    val broadPermissionDeclared: Boolean = false,
    val crossUserRequested: Boolean = false,
)

class NativePackageVisibilitySnapshot internal constructor(
    val schemaVersion: Int,
    val state: PackageVisibilityState,
    val visibleApps: List<VisiblePackageRecord>,
    val truncated: Boolean,
    val visibilityRestricted: Boolean,
) {
    fun encode(): String = buildJsonObject {
        put("schema_version", schemaVersion)
        put("scope", "android_filtered_package_manager")
        put("availability", state.name.lowercase())
        put("visibility_restricted", visibilityRestricted)
        put("truncated", truncated)
        put("apps", buildJsonArray {
            for (app in visibleApps) {
                add(buildJsonObject {
                    put("package_name", app.packageName)
                    put("system", app.isSystem)
                    put("enabled", app.enabled)
                })
            }
        })
    }.toString()

    fun lookup(packageName: String): VisiblePackageLookup = when {
        state in setOf(PackageVisibilityState.UNSUPPORTED, PackageVisibilityState.DENIED,
            PackageVisibilityState.UNAVAILABLE) -> VisiblePackageLookup.DENIED
        visibleApps.any { it.packageName == packageName } -> VisiblePackageLookup.VISIBLE
        else -> VisiblePackageLookup.NOT_VISIBLE_OR_MISSING
    }
}

/** Bounded pure normalization of entries already filtered by Android. */
object NativePackageVisibility {
    private const val MAX_SCAN = 512
    private const val MAX_RESULT = 64
    private val PACKAGE_NAME = Regex("[A-Za-z_][A-Za-z0-9_]*(?:\\.[A-Za-z_][A-Za-z0-9_]*)+")
    private val REDACT = listOf("secret", "password", "token", "private_key", "credential", "signature")

    fun normalize(
        input: PackageVisibilityInput,
        source: List<VisiblePackageCandidate>,
    ): NativePackageVisibilitySnapshot {
        if (input.broadPermissionDeclared || input.crossUserRequested) {
            return NativePackageVisibilitySnapshot(
                1, PackageVisibilityState.DENIED, emptyList(), false, true
            )
        }
        if (input.apiLevel !in 30..100) {
            return NativePackageVisibilitySnapshot(
                1, PackageVisibilityState.UNSUPPORTED, emptyList(), false, true
            )
        }

        val limitedScan = source.asSequence().take(MAX_SCAN).toList()
        val filtered = limitedScan
            .asSequence()
            .filter { record ->
                record.packageName.length in 3..160 &&
                    record.isSystem != null && record.enabled != null &&
                    PACKAGE_NAME.matches(record.packageName) &&
                    REDACT.none { marker ->
                        record.packageName.contains(marker, ignoreCase = true)
                    }
            }
            .map { VisiblePackageRecord(it.packageName, it.isSystem!!, it.enabled!!) }
            .toList()
        val valid = filtered.asSequence()
            .distinctBy { it.packageName }
            .sortedBy { it.packageName }
            .toList()
        val truncated = source.size > MAX_SCAN || valid.size > MAX_RESULT
        val partial = truncated || filtered.size < limitedScan.size
        return NativePackageVisibilitySnapshot(
            1,
            if (partial) PackageVisibilityState.PARTIAL else PackageVisibilityState.FILTERED,
            valid.take(MAX_RESULT),
            truncated,
            true,
        )
    }

    fun unavailable(): NativePackageVisibilitySnapshot =
        NativePackageVisibilitySnapshot(
            1, PackageVisibilityState.UNAVAILABLE, emptyList(), false, true
        )
}

/**
 * One bounded, cancellable sampling attempt. Only app-internal code may
 * construct this; the live MCP caller is not authorized to enumerate apps.
 *
 * A blocking OEM platform call may ignore thread interruption. The sampler
 * uses at most one isolated worker, and never queues an unlimited backlog.
 */
class NativePackageVisibilitySampler : AutoCloseable {
    private val executor = Executors.newSingleThreadExecutor { task ->
        Thread(task, "native-visible-apps").apply { isDaemon = true }
    }
    private var closed = false

    @Synchronized
    fun sample(
        input: PackageVisibilityInput,
        deadlineMs: Long,
        source: () -> List<VisiblePackageCandidate>,
    ): NativePackageVisibilitySnapshot {
        if (closed || deadlineMs !in 1..5_000) return NativePackageVisibility.unavailable()
        if (input.broadPermissionDeclared || input.crossUserRequested ||
            input.apiLevel !in 30..100
        ) return NativePackageVisibility.normalize(input, emptyList())

        val future = executor.submit<List<VisiblePackageCandidate>> { source() }
        return try {
            NativePackageVisibility.normalize(input, future.get(deadlineMs, TimeUnit.MILLISECONDS))
        } catch (_: TimeoutException) {
            future.cancel(true)
            NativePackageVisibility.unavailable()
        } catch (_: InterruptedException) {
            future.cancel(true)
            Thread.currentThread().interrupt()
            NativePackageVisibility.unavailable()
        } catch (_: ExecutionException) {
            NativePackageVisibility.unavailable()
        } catch (_: RuntimeException) {
            future.cancel(true)
            NativePackageVisibility.unavailable()
        }
    }

    @Synchronized
    override fun close() {
        if (closed) return
        closed = true
        executor.shutdownNow()
    }
}
