package org.androidmcp.protocol

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class NativeManagedDevicePolicyTest {
    private fun owner(api: Int = 36) = FakeManagedDeviceEnvironment(
        apiLevel = api,
        ownDeviceOwnerVerified = true,
        declaredAdminReceiver = true,
        ownedDisposableDevice = true,
        fakeUserConfirmed = true,
        fakeCallerVerified = true,
    )

    @Test
    fun tN8A01OrdinaryUnmanagedAndroidAppReportsUnsupported() {
        val policy = NativeManagedDevicePolicy()
        for (probe in listOf(null, false)) {
            val value = policy.inspect(FakeManagedDeviceEnvironment(ownDeviceOwnerVerified = probe))
            assertEquals(ManagedPolicyState.UNSUPPORTED, value.status)
            assertTrue(value.features.isEmpty())
            assertFalse(value.sideEffectsPerformed)
        }
        assertFalse(policy.realPolicyMutationAllowed())
    }

    @Test
    fun tN8A02VerifiedFakeOwnerListsCapabilityNamesButOnlyPlans() {
        val policy = NativeManagedDevicePolicy()
        val result = policy.inspect(owner())
        assertEquals(ManagedPolicyState.PLAN_ONLY, result.status)
        assertTrue(result.features.contains("policy_audit"))
        assertTrue(result.features.contains("lock_task"))
        assertTrue(result.planOnly)
        assertFalse(result.sideEffectsPerformed)
        assertEquals(ManagedPolicyState.DENIED,
            policy.evaluate(owner(), ManagedPolicyOperation.MODIFY_POLICY).status)
    }

    @Test
    fun tN8A03ForgedDeviceAdminRoleNeverSelfProvisionsOrElevates() {
        val policy = NativeManagedDevicePolicy()
        for (claimed in listOf("DeviceOwner", "device_admin", "system", "root")) {
            val forged = FakeManagedDeviceEnvironment(
                modelRoleClaim = claimed,
                fakeCallerVerified = true, fakeUserConfirmed = true,
            )
            assertEquals(ManagedPolicyState.UNSUPPORTED, policy.inspect(forged).status)
            assertEquals(ManagedPolicyState.DENIED,
                policy.evaluate(forged, ManagedPolicyOperation.SELF_PROVISION).status)
        }
        assertFalse(policy.realPolicyMutationAllowed())
    }

    @Test
    fun tN8A04FourApiLevelsRespectOwnAppOwnerStateAndOemUnknown() {
        val policy = NativeManagedDevicePolicy()
        for (api in listOf(30, 33, 34, 36)) {
            assertEquals(ManagedPolicyState.PLAN_ONLY, policy.inspect(owner(api)).status)
            assertEquals(ManagedPolicyState.UNAVAILABLE,
                policy.inspect(owner(api).copy(ownDeviceOwnerVerified = null)).status)
            assertEquals(ManagedPolicyState.UNSUPPORTED,
                policy.inspect(owner(api).copy(ownDeviceOwnerVerified = false)).status)
        }
        assertEquals(ManagedPolicyState.UNSUPPORTED, policy.inspect(owner(29)).status)
        assertEquals(ManagedPolicyState.UNSUPPORTED, policy.inspect(owner(100)).status)
    }

    @Test
    fun tN8A05WipeLockAccountsPolicyAndSilentInstallHaveZeroSideEffects() {
        val policy = NativeManagedDevicePolicy()
        for (operation in ManagedPolicyOperation.entries.filter {
            it != ManagedPolicyOperation.INSPECT_MANAGED_FEATURES
        }) {
            val receipt = policy.evaluate(owner(), operation)
            assertEquals(ManagedPolicyState.DENIED, receipt.status)
            assertFalse(receipt.sideEffectsPerformed)
            assertTrue(receipt.encode().contains("\"side_effects_performed\":false"))
        }
        policy.revoke()
        assertEquals(ManagedPolicyState.REVOKED, policy.inspect(owner()).status)
    }

    @Test
    fun tN8A06PublicMcpAndNativeManifestCannotBecomeAdmin() {
        val policy = NativeManagedDevicePolicy()
        assertEquals(listOf("device_status"), NativeToolProfiles().liveTools(true).map { it.name })
        val status = policy.inspect(owner())
        assertTrue(status.encode().contains("\"plan_only\":true"))
        assertTrue(status.encode().contains("\"mutation_allowed\":false"))
        assertFalse(policy.realPolicyMutationAllowed())
    }

    @Test
    fun missingOwnerReceiverApprovedDeviceOrRealCallerCannotCreateCapability() {
        val policy = NativeManagedDevicePolicy()
        val invalid = listOf(
            owner().copy(declaredAdminReceiver = false),
            owner().copy(ownedDisposableDevice = false),
            owner().copy(fakeUserConfirmed = false),
            owner().copy(fakeCallerVerified = false),
        )
        for (bad in invalid) {
            assertEquals(ManagedPolicyState.UNSUPPORTED, policy.inspect(bad).status)
            assertEquals(ManagedPolicyState.DENIED,
                policy.evaluate(bad, ManagedPolicyOperation.WIPE_DEVICE).status)
        }
        assertFalse(policy.realPolicyMutationAllowed())
    }

    @Test
    fun publicMetadataIsBoundedRedactedAndCannotClaimAdminExecution() {
        val policy = NativeManagedDevicePolicy()
        val environment = owner().copy(modelRoleClaim = "private_root_token_NEVER_PRINT")
        val receipt = policy.inspect(environment)
        val output = receipt.encode()
        assertEquals(ManagedPolicyState.PLAN_ONLY, receipt.status)
        assertTrue(output.contains("\"mutation_allowed\":false"))
        assertTrue(output.contains("\"side_effects_performed\":false"))
        assertTrue(output.contains("\"synthetic_only\":true"))
        assertFalse(output.contains("private_root_token"))
        assertFalse(environment.toString().contains("private_root_token"))
        assertTrue(output.toByteArray().size < 1024)
    }

    @Test
    fun concurrentFakeOwnerChecksNeverMutateOrProvision() {
        val policy = NativeManagedDevicePolicy()
        val pool = java.util.concurrent.Executors.newFixedThreadPool(8)
        try {
            val results = (1..40).map {
                pool.submit<ManagedPolicyReceipt> {
                    if (it % 2 == 0) policy.inspect(owner())
                    else policy.evaluate(owner(), ManagedPolicyOperation.MODIFY_POLICY)
                }
            }.map { it.get(5, java.util.concurrent.TimeUnit.SECONDS) }
            assertEquals(20, results.count { it.status == ManagedPolicyState.PLAN_ONLY })
            assertEquals(20, results.count { it.status == ManagedPolicyState.DENIED })
            assertTrue(results.all { !it.sideEffectsPerformed })
        } finally { pool.shutdownNow() }
    }
}
