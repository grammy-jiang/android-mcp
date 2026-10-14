"""CI must reproduce source ancestry and verify Maven metadata cold-cache."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
VERIFICATION = ROOT / "android/gradle/verification-metadata.xml"
EXPECTED_BOM_SHA256 = "1239e9dbe1397cd5971342956b2511bc3ace7b641842e4372a088dcfa8b9ad55"


class NativeCiColdCacheProvenanceTests(unittest.TestCase):
    def test_pinned_maven_coroutines_180_bom_metadata_has_verified_digest(self) -> None:
        root = ET.parse(VERIFICATION).getroot()
        ns = {"gradle": "https://schema.gradle.org/dependency-verification"}
        match = root.findall(
            ".//gradle:component[@group='org.jetbrains.kotlinx']"
            "[@name='kotlinx-coroutines-bom'][@version='1.8.0']",
            ns,
        )
        self.assertEqual(len(match), 1)
        artifact = match[0].find(
            "gradle:artifact[@name='kotlinx-coroutines-bom-1.8.0.pom']", ns
        )
        self.assertIsNotNone(artifact)
        checksums = artifact.findall("gradle:sha256", ns)
        self.assertEqual(len(checksums), 1)
        self.assertEqual(checksums[0].get("value"), EXPECTED_BOM_SHA256)
        self.assertIn("Maven Central", checksums[0].get("origin", ""))

    def test_pinned_junit_5134_bom_pom_has_independent_digest(self) -> None:
        root = ET.parse(VERIFICATION).getroot()
        ns = {"gradle": "https://schema.gradle.org/dependency-verification"}
        matches = root.findall(
            ".//gradle:component[@group='org.junit']"
            "[@name='junit-bom'][@version='5.13.4']",
            ns,
        )
        self.assertEqual(len(matches), 1)
        artifact = matches[0].find(
            "gradle:artifact[@name='junit-bom-5.13.4.pom']",
            ns,
        )
        self.assertIsNotNone(artifact)
        digests = artifact.findall("gradle:sha256", ns)
        self.assertEqual(len(digests), 1)
        self.assertEqual(
            digests[0].get("value"),
            "d7a08a99b2502f0bb68cd4e1f984f0bf69324aaa208bd0f73366c03fc3548a42",
        )
        self.assertIn("Maven Central", digests[0].get("origin", ""))

    def test_android_classpath_pom_and_junit_metadata_are_independently_pinned(
        self,
    ) -> None:
        ns = {"gradle": "https://schema.gradle.org/dependency-verification"}
        root = ET.parse(VERIFICATION).getroot()
        artifacts = (
            (
                "com.google.guava",
                "guava-parent",
                "33.4.0-jre",
                "pom",
                "3a499ed34a0d9ee0f1bcc39230021a1cd4e2f7dd0426ab6844f585465d41dcd7",
            ),
            (
                "org.junit",
                "junit-bom",
                "5.10.2",
                "module",
                "de23b114b3e4119a8fe6eb17bed5a3852816698bace67071579d6d927ebb080a",
            ),
            (
                "org.junit",
                "junit-bom",
                "5.11.0-M2",
                "module",
                "86477abcf490d6ca059aa9973cb108d22a506f49d1a5569bb32cc6cbf43c2cce",
            ),
            (
                "org.apache.groovy",
                "groovy-bom",
                "4.0.29",
                "pom",
                "c24277dec93f146bcda25f5ae4391d6527e384e2132efa32184c1e852b42bca9",
            ),
        )
        for group, name, version, suffix, digest in artifacts:
            with self.subTest(name=name, version=version, suffix=suffix):
                path = (
                    f".//gradle:component[@group='{group}'][@name='{name}']"
                    f"[@version='{version}']"
                )
                rows = root.findall(path, ns)
                self.assertEqual(len(rows), 1)
                entry = rows[0].find(
                    f"gradle:artifact[@name='{name}-{version}.{suffix}']",
                    ns,
                )
                self.assertIsNotNone(entry)
                hashes = entry.findall("gradle:sha256", ns)
                self.assertEqual(len(hashes), 1)
                self.assertEqual(hashes[0].get("value"), digest)
                self.assertIn("Maven Central", hashes[0].get("origin", ""))

    def test_history_verifier_invoked_before_real_merge_ancestry_audit(self) -> None:
        source = (ROOT / "android/tests/test_native_capability_ledger.py").read_text()
        verification = source.split(
            "def test_actual_merge_receipts_are_git_ancestral() -> None:", 1
        )[1].split("\ndef test_", 1)[0]
        self.assertIn("ensure_complete_ledger_history(ROOT)", verification)
        self.assertIn("run(strict=True)", verification)
        self.assertLess(
            verification.index("ensure_complete_ledger_history(ROOT)"),
            verification.index("run(strict=True)"),
        )
        # The check remains in the existing workflows; the local OAuth app
        # has no workflow-edit scope, so this patch changes no workflow YAML.
        for name, job_name in (
            ("native-jvm-ci.yml", "native-jvm"),
            ("native-emulator-ci.yml", "native-emulator"),
        ):
            workflow = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
            self.assertIn(job_name, workflow["jobs"])

    def test_real_shallow_checkout_cannot_assert_historical_merges(self) -> None:
        with tempfile.TemporaryDirectory(prefix="native-ci-shallow-") as tmp:
            root = Path(tmp)
            origin = root / "repo"
            shallow = root / "shallow"
            full = root / "full"
            origin.mkdir()
            subprocess.run(["git", "init", "--quiet", str(origin)], check=True)

            def git(*args: str) -> str:
                return subprocess.check_output(
                    ["git", "-C", str(origin), *args], text=True
                ).strip()

            git("config", "user.email", "native-ci@example.invalid")
            git("config", "user.name", "CI Fixture")
            source = origin / "file.txt"
            for n in range(3):
                source.write_text(str(n))
                git("add", "file.txt")
                git("commit", "--quiet", "-m", f"historical fixture {n}")
                if n == 0:
                    initial = git("rev-parse", "HEAD")
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--quiet",
                    "--depth",
                    "1",
                    origin.as_uri(),
                    str(shallow),
                ],
                check=True,
            )
            subprocess.run(
                ["git", "clone", "--quiet", origin.as_uri(), str(full)],
                check=True,
            )
            shallow_check = subprocess.run(
                [
                    "git",
                    "-C",
                    str(shallow),
                    "merge-base",
                    "--is-ancestor",
                    initial,
                    "HEAD",
                ],
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(shallow_check.returncode, 0)
            full_check = subprocess.run(
                [
                    "git",
                    "-C",
                    str(full),
                    "merge-base",
                    "--is-ancestor",
                    initial,
                    "HEAD",
                ],
                check=False,
            )
            self.assertEqual(full_check.returncode, 0)


if __name__ == "__main__":
    unittest.main()
