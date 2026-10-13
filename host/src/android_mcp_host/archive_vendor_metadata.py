"""Strict parsers for bounded, operator-pinned Android vendor metadata output."""

from __future__ import annotations

import re
from typing import Any

from android_mcp_host.archive_validation import (
    MAX_MANIFEST_BYTES,
    MAX_PERMISSIONS,
    _manifest,
)

_PACKAGE_LINE = re.compile(
    r"(?m)^package: +name='([A-Za-z0-9_.]{3,128})' "
    r"versionCode='([0-9]{1,10})' versionName='([A-Za-z0-9_.+\-]{1,64})'(?: .*)?$",
    re.ASCII,
)
_PACKAGE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\Z", re.ASCII)
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+\-]{0,63}\Z", re.ASCII)
_PERMISSION = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{0,127}\Z", re.ASCII)
_PERM_LINE = re.compile(r"^uses-permission: name='([^'\r\n]{1,128})'(?: .*)?$", re.ASCII)


def parse_aapt2_badging(output: str) -> dict[str, Any] | None:
    """Never promote arbitrary CLI stdout to a trusted package identifier."""
    if not 0 < len(output) <= MAX_MANIFEST_BYTES:
        return None
    match = _PACKAGE_LINE.search(output)
    if match is None:
        return None
    package, code_raw, version = match.groups()
    code = int(code_raw)
    if (
        _PACKAGE.fullmatch(package) is None
        or _VERSION.fullmatch(version) is None
        or not 1 <= code <= 2147483647
    ):
        return None
    permissions: set[str] = set()
    for line in output.splitlines():
        if line.startswith("uses-permission:"):
            permission_line = _PERM_LINE.fullmatch(line)
            if permission_line is None:
                return None
            name = permission_line.group(1)
            if _PERMISSION.fullmatch(name) is None or len(permissions) >= MAX_PERMISSIONS:
                return None
            permissions.add(name)
    return {
        "package_id": package,
        "version_name": version,
        "version_code": code,
        "permissions": sorted(permissions),
    }


def parse_bundletool_manifest(output: str) -> dict[str, Any] | None:
    """A preconfigured bundletool CLI emits a literal manifest XML snapshot."""
    if not 0 < len(output.encode("utf-8")) <= MAX_MANIFEST_BYTES:
        return None
    return _manifest(output.encode("utf-8"))
