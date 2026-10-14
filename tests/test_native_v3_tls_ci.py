"""E02.a release-safe TLS POC composition and manifest security gates."""

from __future__ import annotations

import unittest
from pathlib import Path

from scripts.audit_native_gradle_policy import policy_for

ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android/native-v3-tls-fixture"


class TestOnlyTlsComposition(unittest.TestCase):
    def test_opt_in_instrumentation_stays_outside_native_production_app(self) -> None:
        native = (ROOT / "android/app/src/main/AndroidManifest.xml").read_text()
        self.assertNotIn("native-v3-tls-fixture", native)
        self.assertNotIn("SSLServerSocket", native)
        settings = (ROOT / "android/settings.gradle.kts").read_text()
        self.assertIn("enableV3TlsPoc", settings)
        self.assertIn("native-v3-tls-fixture", settings)
        module = (ANDROID / "src/main/AndroidManifest.xml").read_text()
        self.assertIn('android:usesCleartextTraffic="false"', module)
        self.assertIn("android.permission.INTERNET", module)
        for fragment in (
            'android:exported="true"',
            "android.permission.ACCESSIBILITY_SERVICE",
            "android.permission.QUERY_ALL_PACKAGES",
            "android.permission.MANAGE_EXTERNAL_STORAGE",
        ):
            self.assertNotIn(fragment, module)

    def test_tls_fixture_lockfile_added_to_checksums(self) -> None:
        result = policy_for(ROOT, strict=True)
        self.assertEqual(result["module_count"], 7)
        self.assertEqual(result["lockfile_count"], 7)
        self.assertGreaterEqual(result["verification_sha256_count"], 500)

    def test_keystore_tls_raw_signature_digests_required(self) -> None:
        for filename in (
            "MutualTlsAndroidTest.kt",
            "MutualTlsClientAndroidTest.kt",
        ):
            path = (
                ANDROID / "src/androidTest/java/org/androidmcp/v3tlsfixture" / filename
            )
            source = path.read_text()
            self.assertIn("KeyProperties.DIGEST_NONE", source)
            self.assertIn("AndroidKeyStore", source)
            self.assertIn("store.deleteEntry(", source)
            self.assertIn("TLSv1.2", source)
        server = (
            ANDROID
            / "src/androidTest/java/org/androidmcp/v3tlsfixture/MutualTlsAndroidTest.kt"
        ).read_text()
        self.assertIn("server.needClientAuth = true", server)
        self.assertIn('InetAddress.getByName("127.0.0.1")', server)

    def test_release_gate_rejects_fake_tls_stage_completion(self) -> None:
        local = (ROOT / "scripts/check-native-local-ci.sh").read_text()
        self.assertIn("--tls-poc", local)
        self.assertIn("bash scripts/check-native-v3-tls-poc.sh", local)
        gate = (ROOT / "scripts/check-native-v3-tls-poc.sh").read_text()
        for fragment in (
            "git status --porcelain",
            "android/gradlew",
            ":native-v3-tls-fixture:assembleDebugAndroidTest",
            "scripts.run_native_v3_tls_poc",
            "scripts.run_native_v3_tls_client_poc",
            "forward --list",
            "reverse --list",
        ):
            self.assertIn(fragment, gate)
        self.assertIn("NOT_DONE", gate)


if __name__ == "__main__":
    unittest.main()
