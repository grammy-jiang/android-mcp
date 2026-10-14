"""E01.e failure injection for ADB forward leak and exact cleanup under crash."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.native_v3_owned_avd import (
    IdentityError,
    assert_forward_cleanup,
    parse_owned_forward_routes,
)


class TestForwardCleanup(unittest.TestCase):
    def test_only_exact_serial_routes_observed(self):
        raw = (
            "emulator-5554 tcp:53001 tcp:38765\n"
            "emulator-5562 tcp:54010 tcp:38765\n"
            "emulator-5562 tcp:54011 tcp:38765\n"
        )
        self.assertEqual(
            parse_owned_forward_routes(raw, "emulator-5562"),
            ("emulator-5562 tcp:54010 tcp:38765", "emulator-5562 tcp:54011 tcp:38765"),
        )

    def test_invalid_owned_route_fails_not_generic_device(self):
        for text in (
            "emulator-5562 bad-route\n",
            "emulator-5562 tcp:54010 tcp:0\n",
            "emulator-5562 tcp:54010 tcp:38765 extra\n",
        ):
            with self.subTest(text=text), self.assertRaises(IdentityError):
                parse_owned_forward_routes(text, "emulator-5562")

    def test_leaked_forward_after_client_success_blocks(self):
        with (
            patch(
                "scripts.native_v3_owned_avd._owned_forward_snapshot",
                side_effect=[(), ("emulator-5562 tcp:54010 tcp:38765",)],
            ),
            self.assertRaises(RuntimeError),
            assert_forward_cleanup("emulator-5562"),
        ):
            pass

    def test_original_error_still_propagates_if_routes_clean(self):
        with (
            patch(
                "scripts.native_v3_owned_avd._owned_forward_snapshot",
                side_effect=[(), ()],
            ),
            self.assertRaises(TimeoutError),
            assert_forward_cleanup("emulator-5562"),
        ):
            raise TimeoutError("Native client timed out")
        with (
            patch(
                "scripts.native_v3_owned_avd._owned_forward_snapshot",
                side_effect=[(), ()],
            ),
            assert_forward_cleanup("emulator-5562"),
        ):
            pass

    def test_different_serial_cannot_hide_stale_owned_route(self):
        with self.assertRaises(IdentityError):
            parse_owned_forward_routes(
                "emulator-5562 tcp:54321 tcp:38765", "physical-Android-device"
            )


if __name__ == "__main__":
    unittest.main()
