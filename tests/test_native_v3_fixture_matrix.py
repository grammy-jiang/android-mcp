"""E01.b fixture acceptance harness fail-closed parser tests."""

from __future__ import annotations

import unittest

from scripts.native_v3_fixture_matrix import (
    locate_button,
    match_pixel,
    parse_counter,
    parse_signer_digest,
    valid_documents_denial,
)

GOOD_UI = (
    '<hierarchy rotation="0"><node class="android.widget.Button" '
    'content-desc="android-mcp-v3-increment-counter" '
    'bounds="[300,400][500,460]" text="INCREMENT FIXTURE COUNTER" />'
    "</hierarchy>"
)


class FixtureHarnessTests(unittest.TestCase):
    def test_counter_only_single_exact_record(self) -> None:
        self.assertEqual(parse_counter("Row: 0 counter=19\n"), 19)
        for bad in (
            "No result found",
            "Row: 0 counter=-1",
            "Row: 0 counter=19\nATTACK",
            "Row: 1 counter=12",
            "Row: 0 counter=999999999999999",
            "",
        ):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                parse_counter(bad)

    def test_signer_only_one_complete_sha256(self) -> None:
        good = "Signer #1 certificate SHA-256 digest: " + "a" * 64 + "\n"
        self.assertEqual(parse_signer_digest(good), "a" * 64)
        for bad in ("", "SHA-1 digest: " + "a" * 40, good + good):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_signer_digest(bad)

    def test_ui_button_must_have_exact_accessibility_identity(self) -> None:
        self.assertEqual(locate_button(GOOD_UI), (400, 430))
        self.assertEqual(
            locate_button(GOOD_UI, "android-mcp-v3-increment-counter"), (400, 430)
        )
        with self.assertRaises(ValueError):
            locate_button(GOOD_UI, "android-mcp-v3-open-secure-fixture")
        for bad in (
            GOOD_UI.replace("android-mcp-v3-increment-counter", "bad"),
            GOOD_UI.replace(
                "</hierarchy>",
                GOOD_UI[24 : GOOD_UI.index("</hierarchy>")] + "</hierarchy>",
            ),
            "<notvalid",
        ):
            with self.subTest(bad=bad[:40]), self.assertRaises(ValueError):
                locate_button(bad)

    def test_known_pixel_colors_not_any_screenshot(self) -> None:
        self.assertTrue(match_pixel("srgba(255,64,80,1)", (255, 64, 80)))
        self.assertTrue(match_pixel("srgba(252,66,81,1)", (255, 64, 80)))
        self.assertFalse(match_pixel("srgba(16,15,26,1)", (255, 64, 80)))
        self.assertFalse(match_pixel("malformed", (255, 64, 80)))

    def test_document_denial_cannot_be_generic_adb_failure(self) -> None:
        self.assertTrue(
            valid_documents_denial(
                "java.lang.SecurityException: Permission Denial: "
                "opening FixtureDocumentsProvider requires that you obtain access using ACTION_OPEN_DOCUMENT or related APIs",
                1,
            )
        )
        self.assertFalse(valid_documents_denial("device offline", 1))
        self.assertFalse(valid_documents_denial("permission granted", 0))


if __name__ == "__main__":
    unittest.main()
