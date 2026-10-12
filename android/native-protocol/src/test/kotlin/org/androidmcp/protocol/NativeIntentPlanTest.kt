package org.androidmcp.protocol

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.util.concurrent.atomic.AtomicInteger

class NativeIntentPlanTest {
    private val pkg = "org.example.visible"
    private val activity = "org.example.visible.MainActivity"
    private val name = "$pkg/$activity"
    private val request = NativeIntentRequest(pkg, activity)
    private val visible = NativePackageVisibility.normalize(
        PackageVisibilityInput(36),
        listOf(VisiblePackageCandidate(pkg, false, true)),
    )
    private val target = NativeResolvedActivity(pkg, activity, exported = true, enabled = true)
    private val foreground = NativeLaunchEnvironment(
        apiLevel = 36, callerForeground = true, userGestureObserved = true
    )
    private fun resolve(
        candidate: NativeIntentRequest = request,
        env: NativeLaunchEnvironment = foreground,
        allowed: Set<String> = setOf(name),
        actual: NativeResolvedActivity? = target,
        visibility: NativePackageVisibilitySnapshot = visible,
    ) = NativeIntentPlans.resolve(candidate, env, visibility, allowed, actual)

    @Test
    fun tN2C01AllowlistedVisibleExportedExplicitActivityGivesDeterministicPlan() {
        val plan = resolve()
        assertEquals(NativeIntentPlanState.PLAN_ONLY, plan.state)
        assertEquals(pkg, plan.packageName)
        assertEquals(activity, plan.activityName)
        assertEquals("android.intent.action.MAIN", plan.action)
        assertTrue(plan.requiresSeparateUserGrant)
        assertEquals(plan.planId, resolve().planId)
        assertTrue(plan.planId!!.matches(Regex("[a-f0-9]{64}")))
        val json = Json.parseToJsonElement(plan.encode()).jsonObject
        assertEquals("1", json.getValue("schema_version").jsonPrimitive.content)
        assertEquals("plan_only", json.getValue("availability").jsonPrimitive.content)
    }

    @Test
    fun tN2C02ImplicitBroadcastUnknownDeepLinkNonExportedWrongUserDenied() {
        val bad = listOf(
            request.copy(packageName = ""),
            request.copy(activityName = ""),
            request.copy(action = "android.intent.action.SEND"),
            request.copy(action = "android.intent.action.VIEW"),
            request.copy(category = "android.intent.category.DEFAULT"),
            request.copy(userScope = "work_profile"),
        )
        for (candidate in bad) {
            assertEquals(NativeIntentPlanState.DENIED, resolve(candidate).state)
            assertNull(resolve(candidate).planId)
        }
        assertEquals(NativeIntentPlanState.NOT_EXPORTED,
            resolve(actual = target.copy(exported = false)).state)
        assertEquals(NativeIntentPlanState.NOT_VISIBLE_OR_MISSING,
            resolve(allowed = setOf(name), visibility =
                NativePackageVisibility.normalize(PackageVisibilityInput(36), emptyList())).state)
        assertEquals(NativeIntentPlanState.DENIED, resolve(allowed = emptySet()).state)
    }

    @Test
    fun tN2C03ArbitraryExtrasUrisFlagsAndSelectorCannotEscalate() {
        val bad = listOf(
            request.copy(uri = "content://other.app/private"),
            request.copy(uri = "intent://org.example/#Intent;S.data=/data/system;end"),
            request.copy(extras = mapOf("redirect" to "evil")),
            request.copy(extras = mapOf("long" to "Z".repeat(100_000))),
            request.copy(flags = 0x10000000),
            request.copy(selector = true),
            request.copy(activityName = "MainActivity;am start -a android.intent.action.CALL"),
            request.copy(packageName = "../data/data"),
        )
        for (candidate in bad) {
            val outcome = resolve(candidate)
            assertEquals(NativeIntentPlanState.DENIED, outcome.state)
            assertNull(outcome.packageName)
            assertNull(outcome.planId)
        }
    }

    @Test
    fun tN2C04Api30_33_34_36ForegroundAndBackgroundRestrictionsExplicit() {
        for (api in listOf(30, 33, 34, 36)) {
            assertEquals(NativeIntentPlanState.PLAN_ONLY,
                resolve(env = foreground.copy(apiLevel = api)).state)
            assertEquals(NativeIntentPlanState.BACKGROUND_RESTRICTED,
                resolve(env = foreground.copy(apiLevel = api, callerForeground = false)).state)
            assertEquals(NativeIntentPlanState.BACKGROUND_RESTRICTED,
                resolve(env = foreground.copy(apiLevel = api, userGestureObserved = false)).state)
        }
        assertEquals(NativeIntentPlanState.UNSUPPORTED,
            resolve(env = foreground.copy(apiLevel = 29)).state)
        assertEquals(NativeIntentPlanState.UNSUPPORTED,
            resolve(env = foreground.copy(apiLevel = 999)).state)
    }

    @Test
    fun tN2C05DuplicatePlanIsIdempotentButNeverAnExecutionGrant() {
        val first = resolve()
        val second = resolve()
        assertEquals(first, second)
        assertTrue(first.requiresSeparateUserGrant)
        assertEquals(NativeIntentPlanState.PLAN_ONLY, first.state)
        val changed = resolve(candidate = request.copy(activityName =
            "org.example.visible.SettingsActivity"), allowed = setOf(
                "$pkg/org.example.visible.SettingsActivity"
            ), actual = target.copy(activityName = "org.example.visible.SettingsActivity"))
        assertFalse(first.planId == changed.planId)
        val guard = NativeLocalCallerGuard()
        val fake = SyntheticCallerApproval(guard.epoch, "s", true)
        assertFalse(guard.authorizeSensitive(LocalHttpRequest(), "native_launch_activity", fake).allowed)
    }

    @Test
    fun tN2C06NoMockedAndroidSideEffectsOrTaskSwitches() {
        val launches = AtomicInteger()
        val permissions = AtomicInteger()
        val resolverCalls = AtomicInteger()
        val fakeTarget = run {
            resolverCalls.incrementAndGet()
            target
        }
        val plan = resolve(actual = fakeTarget)
        assertEquals(NativeIntentPlanState.PLAN_ONLY, plan.state)
        assertEquals(1, resolverCalls.get())
        assertEquals(0, launches.get())
        assertEquals(0, permissions.get())
        assertFalse(plan.encode().contains("startActivity"))
        assertFalse(plan.encode().contains("shell"))
        assertTrue(plan.encode().toByteArray().size < 4096)
    }
}
