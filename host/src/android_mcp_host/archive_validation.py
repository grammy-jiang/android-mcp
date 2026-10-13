"""Bounded ZIP/manifest inspection without extracting or trusting archive metadata."""

from __future__ import annotations

import io
import re
import stat
import zipfile
import zlib
from pathlib import PurePosixPath
from typing import Any

from defusedxml import ElementTree  # type: ignore[import-untyped]
from defusedxml.common import DefusedXmlException  # type: ignore[import-untyped]

MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 512
MAX_UNCOMPRESSED_BYTES = 32 * 1024 * 1024
MAX_ENTRY_BYTES = 16 * 1024 * 1024
MAX_MANIFEST_BYTES = 65536
MAX_PERMISSIONS = 64
MAX_ABIS = 16
_ANDROID = "{http://schemas.android.com/apk/res/android}"
_PACKAGE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\Z", re.ASCII)
_ABI = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,31}\Z", re.ASCII)
_PERMISSION = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{0,127}\Z", re.ASCII)
_VERSION_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+\-]{0,63}\Z", re.ASCII)


class ArchiveValidationError(Exception):
    """The given archive cannot be safely interpreted."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Archive validation denied: {code}")


def _safe_filename(name: str) -> bool:
    if (
        not name
        or len(name) > 256
        or name.startswith("/")
        or "\\" in name
        or "\x00" in name
        or ":" in name
        or any(ord(char) < 32 for char in name)
    ):
        return False
    parts = name.rstrip("/").split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return False
    return True


def _manifest(xml_data: bytes) -> dict[str, Any] | None:
    """Support only small literal manifest XML, never APK binary AXML guesses."""
    if (
        not 0 < len(xml_data) <= MAX_MANIFEST_BYTES
        or b"<!DOCTYPE" in xml_data.upper()
        or b"<!ENTITY" in xml_data.upper()
        or b"\x00" in xml_data
    ):
        return None
    try:
        root = ElementTree.fromstring(xml_data)
    except (ElementTree.ParseError, DefusedXmlException):
        return None
    if root.tag != "manifest":
        return None
    package = root.attrib.get("package")
    version_name = root.attrib.get(_ANDROID + "versionName")
    code_raw = root.attrib.get(_ANDROID + "versionCode")
    if (
        not isinstance(package, str)
        or _PACKAGE.fullmatch(package) is None
        or len(package) > 128
        or not isinstance(version_name, str)
        or _VERSION_NAME.fullmatch(version_name) is None
        or not isinstance(code_raw, str)
        or not code_raw.isascii()
        or not code_raw.isdecimal()
        or len(code_raw) > 10
    ):
        return None
    version_code = int(code_raw)
    if not 1 <= version_code <= 2147483647:
        return None
    permissions: set[str] = set()
    for element in root.iter("uses-permission"):
        permission = element.attrib.get(_ANDROID + "name")
        if (
            not isinstance(permission, str)
            or _PERMISSION.fullmatch(permission) is None
            or len(permissions) >= MAX_PERMISSIONS
        ):
            return None
        permissions.add(permission)
    return {
        "package_id": package,
        "version_name": version_name,
        "version_code": version_code,
        "permissions": sorted(permissions),
    }


def inspect_zip(data: bytes, mime_type: str) -> tuple[dict[str, Any], list[str]]:
    """No ZIP extraction and no archive-defined output paths are permitted."""
    suffix = {
        "application/vnd.android.package-archive": ("AndroidManifest.xml", "lib/"),
        "application/vnd.android.aab": ("base/manifest/AndroidManifest.xml", "base/lib/"),
    }.get(mime_type)
    if suffix is None:
        raise ArchiveValidationError("UNSUPPORTED_ARCHIVE")
    manifest_name, lib_prefix = suffix
    if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_ARCHIVE_BYTES:
        raise ArchiveValidationError("RESOURCE_LIMIT")
    try:
        with zipfile.ZipFile(io.BytesIO(data), "r") as archive:
            infos = archive.infolist()
            if not 1 <= len(infos) <= MAX_ARCHIVE_MEMBERS:
                raise ArchiveValidationError("RESOURCE_LIMIT")
            seen: set[str] = set()
            total = 0
            manifest_info: zipfile.ZipInfo | None = None
            abis: set[str] = set()
            resources_present = False
            for info in infos:
                name = info.filename
                if not _safe_filename(name):
                    raise ArchiveValidationError("UNTRUSTED_ARCHIVE_PATH")
                normalized = name.casefold()
                if normalized in seen:
                    raise ArchiveValidationError("DUPLICATE_ARCHIVE_PATH")
                seen.add(normalized)
                if info.flag_bits & 1:
                    raise ArchiveValidationError("INVALID_ARCHIVE")
                if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise ArchiveValidationError("INVALID_ARCHIVE")
                if stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK:
                    raise ArchiveValidationError("UNTRUSTED_ARCHIVE_PATH")
                if info.file_size < 0 or info.file_size > MAX_ENTRY_BYTES:
                    raise ArchiveValidationError("RESOURCE_LIMIT")
                total += info.file_size
                if total > MAX_UNCOMPRESSED_BYTES:
                    raise ArchiveValidationError("RESOURCE_LIMIT")
                if info.file_size > 4096 and info.file_size / max(info.compress_size, 1) > 200:
                    raise ArchiveValidationError("COMPRESSION_LIMIT")
                if name == (
                    "resources.arsc"
                    if mime_type.endswith("package-archive")
                    else "base/resources.pb"
                ):
                    resources_present = True
                if name == manifest_name:
                    if info.file_size > MAX_MANIFEST_BYTES:
                        raise ArchiveValidationError("RESOURCE_LIMIT")
                    manifest_info = info
                if name.startswith(lib_prefix) and name != lib_prefix:
                    parts = PurePosixPath(name[len(lib_prefix) :]).parts
                    if len(parts) >= 2 and _ABI.fullmatch(parts[0]) is not None:
                        abis.add(parts[0])
                    if len(abis) > MAX_ABIS:
                        raise ArchiveValidationError("RESOURCE_LIMIT")
            # All archive entries must be CRC-valid before returning trusted metadata.
            if archive.testzip() is not None:
                raise ArchiveValidationError("INVALID_ARCHIVE")
            metadata: dict[str, Any] = {
                "package_id": None,
                "version_name": None,
                "version_code": None,
                "permissions": [],
                "abis": sorted(abis),
                "resources_present": resources_present,
                "member_count": len(infos),
            }
            if manifest_info is None:
                return metadata, ["MANIFEST_UNAVAILABLE"]
            raw = archive.read(manifest_info)
            fields = _manifest(raw)
            if fields is None:
                return metadata, ["MANIFEST_UNAVAILABLE"]
            metadata.update(fields)
            return metadata, []
    except (zipfile.BadZipFile, EOFError, RuntimeError, ValueError, OSError, zlib.error) as error:
        raise ArchiveValidationError("INVALID_ARCHIVE") from error
