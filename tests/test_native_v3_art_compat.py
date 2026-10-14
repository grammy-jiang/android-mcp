"""Real Android ART must never call unsupported java.nio.Files.readString."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART_SOURCES = (
    ROOT
    / "android/native-lifecycle/src/main/kotlin/org/androidmcp/lifecycle/NativeInstallationIdentity.kt",
    ROOT
    / "android/native-lifecycle/src/main/kotlin/org/androidmcp/lifecycle/NativeFenceState.kt",
)


class RealAndroidArtCompatTests(unittest.TestCase):
    def test_persisted_owner_and_fence_use_bounded_android_supported_read(self) -> None:
        for file in ART_SOURCES:
            with self.subTest(source=file.name):
                text = file.read_text(encoding="utf-8")
                self.assertNotIn(
                    "Files.readString(",
                    text.replace(
                        "// Files.readString",
                        "// unsupported_jdk_method",
                    ),
                )
                self.assertIn("Files.readAllBytes(", text)
                self.assertIn(".size !in", text)
                self.assertIn("LinkOption.NOFOLLOW_LINKS", text)

    def test_product_runtime_does_not_infer_grant_from_jvm_fence(self) -> None:
        source = ART_SOURCES[1].read_text()
        self.assertIn("fun realMutationAllowed(): Boolean = false", source)
        self.assertIn("synthetic_only", source)


if __name__ == "__main__":
    unittest.main()
