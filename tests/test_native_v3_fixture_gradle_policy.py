"""E01.b new fixture modules must be part of static provenance policy."""

import unittest
from pathlib import Path

from scripts.audit_native_gradle_policy import COORDINATE, policy_for

ROOT = Path(__file__).resolve().parents[1]


class FixtureGradlePolicyTests(unittest.TestCase):
    def test_fixture_modules_are_lockfile_checked(self) -> None:
        result = policy_for(ROOT, strict=True)
        self.assertEqual(result["module_count"], 6)
        self.assertEqual(result["lockfile_count"], 6)
        self.assertGreaterEqual(result["explicit_coordinate_count"], 15)
        self.assertEqual(result["gaps"], [])

    def test_android_test_dependencies_cannot_escape_policy(self) -> None:
        src = 'androidTestImplementation("androidx.test:runner:1.7.0")'
        self.assertEqual(COORDINATE.findall(src), ["androidx.test:runner:1.7.0"])


if __name__ == "__main__":
    unittest.main()
