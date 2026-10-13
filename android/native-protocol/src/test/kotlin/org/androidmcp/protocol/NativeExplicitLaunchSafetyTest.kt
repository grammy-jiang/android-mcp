package org.androidmcp.protocol

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class NativeExplicitLaunchSafetyTest {
    private val pkg = "org.example.ownedfixture"
    private val activity = "$pkg.MainActivity"
    private val component = "$pkg/$activity"
    private val intent = NativeIntentRequest(pkg, activity)
    private fun request() = SyntheticSafeLaunchRequest(
        intent, actionId = "action-n7c-001", authorizedCaller = true,
        userApproved = true, signedGrantFresh = true, screenUnlocked = true,
    )
    private fun target(api: Int = 36, exported: Boolean = true) =
        SyntheticSafeLaunchTarget(
            environment = NativeLaunchEnvironment(api, true, true),
            visibility = NativePackageVisibility.normalize(
                PackageVisibilityInput(api),
                listOf(VisiblePackageCandidate(pkg, false, true)),
            ),
            target = NativeResolvedActivity(pkg, activity, exported, true),
            explicitAllowlist = setOf(component), ownDisposableQemu = true,
        )

    @Test
    fun tN7C01ExactAllowlistedExportedActivityOwnerApprovalProducesPlanOnly() {
        val coordinator = NativeExplicitLaunchSafety()
        val receipt = coordinator.plan(request(), target())
        assertEquals(SafeLaunchState.PLANNED, receipt.status)
        assertNotNull(receipt.planId)
        assertEquals(64, receipt.planId!!.length)
        assertFalse(receipt.realLaunched)
        assertFalse(receipt.realDispatchAllowed)
        assertEquals(0, coordinator.activeRealLaunchCount())
    }

    @Test
    fun tN7C02NonexportedUnknownOffUserLockedOrImplicitIntentDenied() {
        val invalid = listOf(
            request() to target(exported = false),
            request().copy(intent = intent.copy(userScope = "work")) to target(),
            request().copy(screenUnlocked = false) to target(),
            request().copy(intent = intent.copy(action = "android.intent.action.VIEW")) to target(),
            request().copy(intent = intent.copy(uri = "intent://exfiltrate")) to target(),
            request().copy(intent = intent.copy(packageName = "org.other.untrusted")) to target(),
        )
        for ((input, platform) in invalid) {
            val outcome = NativeExplicitLaunchSafety().plan(input, platform)
            assertFalse(outcome.status == SafeLaunchState.PLANNED)
            assertNull(outcome.planId)
            assertFalse(outcome.realLaunched)
        }
    }

    @Test
    fun tN7C03EveryApiRespectsForegroundAndFgsStartRestrictions() {
        for (api in listOf(30, 33, 34, 36)) {
            val platform = target(api)
            assertEquals(SafeLaunchState.PLANNED,
                NativeExplicitLaunchSafety().plan(request(), platform).status)
            assertEquals(SafeLaunchState.BACKGROUND_RESTRICTED,
                NativeExplicitLaunchSafety().plan(request(), platform.copy(
                    environment = platform.environment.copy(callerForeground = false))).status)
            assertEquals(SafeLaunchState.BACKGROUND_RESTRICTED,
                NativeExplicitLaunchSafety().plan(request().copy(foregroundServiceOnly = true), platform).status)
        }
        assertEquals(SafeLaunchState.UNSUPPORTED,
            NativeExplicitLaunchSafety().plan(request(), target(29)).status)
    }

    @Test
    fun tN7C04DuplicateActionIdAndPostDispatchUncertaintyNeverAutoReplay() {
        val coordinator = NativeExplicitLaunchSafety()
        val first = coordinator.plan(request(), target())
        assertEquals(SafeLaunchState.PLANNED, first.status)
        assertEquals(SafeLaunchState.REPLAY_DENIED, coordinator.plan(request(), target()).status)
        assertEquals(SafeLaunchState.UNCERTAIN,
            coordinator.markFakeDispatch(request().actionId, target()).status)
        assertEquals(SafeLaunchState.UNCERTAIN,
            coordinator.plan(request().copy(actionId = "new-action-n7c"), target()).status)
        assertEquals(0, coordinator.activeRealLaunchCount())
    }

    @Test
    fun tN7C05RevokedCallerOriginOrStopBetweenPlanAndDispatchFailsClosed() {
        val coordinator = NativeExplicitLaunchSafety()
        assertEquals(SafeLaunchState.PLANNED, coordinator.plan(request(), target()).status)
        assertEquals(SafeLaunchState.REVOKED,
            coordinator.markFakeDispatch(request().actionId, target(),
                originStillAuthorized = false).status)
        coordinator.revoke()
        assertEquals(SafeLaunchState.REVOKED,
            coordinator.plan(request().copy(actionId = "new-request"), target()).status)
        coordinator.stop()
        assertEquals(SafeLaunchState.STOPPED,
            coordinator.plan(request().copy(actionId = "another-request"), target()).status)
        assertFalse(coordinator.realLaunchAllowed())
    }

    @Test
    fun tN7C06NativeAppStatusOnlyAndNoArbitraryShellOrForceStop() {
        val policy = NativeExplicitLaunchSafety()
        assertEquals(listOf("device_status"), NativeToolProfiles().liveTools(true).map { it.name })
        val outcome = policy.plan(request(), target())
        assertFalse(outcome.realLaunched)
        assertFalse(policy.realLaunchAllowed())
        assertTrue(outcome.encode().contains("\"real_launched\":false"))
        assertTrue(outcome.encode().contains("\"automatic_retry\":false"))
        assertFalse(outcome.encode().contains(pkg))
        assertFalse(outcome.encode().contains(request().actionId))
    }

    @Test
    fun invalidGrantAndUnownedQemuEvenWithApprovedCallerAreDenied() {
        val original = request()
        for (bad in listOf(
            original.copy(userApproved = false),
            original.copy(authorizedCaller = false),
            original.copy(signedGrantFresh = false),
            original.copy(originRevoked = true),
        )) {
            assertEquals(SafeLaunchState.REVOKED,
                NativeExplicitLaunchSafety().plan(bad, target()).status)
        }
        assertEquals(SafeLaunchState.DENIED,
            NativeExplicitLaunchSafety().plan(original, target().copy(ownDisposableQemu = false)).status)
        assertEquals(SafeLaunchState.DENIED,
            NativeExplicitLaunchSafety().plan(original.copy(actionId = "bad id"), target()).status)
        assertFalse(original.toString().contains(pkg))
        assertFalse(target().toString().contains(pkg))
    }

    @Test
    fun concurrentSameActionCannotCreateMultipleSimulatedPlans() {
        val policy = NativeExplicitLaunchSafety()
        val executor = java.util.concurrent.Executors.newFixedThreadPool(10)
        val begin = java.util.concurrent.CountDownLatch(1)
        try {
            val calls = (1..10).map {
                executor.submit<SafeLaunchReceipt> {
                    begin.await(5, java.util.concurrent.TimeUnit.SECONDS)
                    policy.plan(request(), target())
                }
            }
            begin.countDown()
            val results = calls.map { it.get(5, java.util.concurrent.TimeUnit.SECONDS) }
            assertEquals(1, results.count { it.status == SafeLaunchState.PLANNED })
            assertEquals(9, results.count { it.status == SafeLaunchState.REPLAY_DENIED })
            assertEquals(0, policy.activeRealLaunchCount())
        } finally { begin.countDown(); executor.shutdownNow() }
    }
}
