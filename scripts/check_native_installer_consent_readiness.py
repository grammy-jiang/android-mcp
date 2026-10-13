#!/usr/bin/env python3
"""N7.b read-only QEMU preflight; never opens a PackageInstaller UI.

A returned BLOCKED status is NOT an executed Android consent-flow test.
Missing owner-proof and signed dedicated test APK are deliberate safety gates.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable

from verify_native_api_matrix import (
    API_VERSIONS,
    MatrixSafetyError,
    adb_read,
    verify_all_before_any_mutation,
)


def inspect_consent_readiness(
    assignments: dict[int, str],
    adb_reader: Callable[..., str] = adb_read,
) -> dict[str, object]:
    """Read QEMU properties only, never perform ADB install/intent commands."""
    verify_all_before_any_mutation(assignments, adb_reader)
    return {
        "result": "blocked",
        "reason": "owned disposable AVD proof and separately signed test APK / real Android consent route unavailable",
        "api_levels_verified": list(API_VERSIONS),
        "target_kind": "verified_qemu_read_only",
        "real_consent_ui_opened": False,
        "user_confirmation_observed": False,
        "package_installed": False,
        "installation_attempted": False,
        "physical_device_touched": False,
        "request_install_packages_permission_enabled": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for api in API_VERSIONS:
        parser.add_argument(f"--api{api}", required=True)
    args = parser.parse_args()
    assignments = {api: getattr(args, f"api{api}") for api in API_VERSIONS}
    try:
        result = inspect_consent_readiness(assignments)
    except MatrixSafetyError as error:
        print(json.dumps({"result": "denied", "reason": str(error)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    # Do not let a shell script confuse verified QEMU with proven real consent.
    return 3


if __name__ == "__main__":
    sys.exit(main())
