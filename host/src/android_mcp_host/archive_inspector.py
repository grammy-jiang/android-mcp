"""Private, read-only APK/AAB structure inspection with truthful signature state.

Only a trusted Host operator configures owner and verifier executables.
Public MCP supplies an opaque artifact handle; no archive data or path returns.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path
from typing import Any

from android_mcp_host.archive_validation import ArchiveValidationError, inspect_zip
from android_mcp_host.archive_vendor_metadata import parse_aapt2_badging, parse_bundletool_manifest
from android_mcp_host.command_runner import RunResult, bounded_run
from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.private_artifact_support import ArtifactStoreError

APK = "application/vnd.android.package-archive"
AAB = "application/vnd.android.aab"
Runner = Callable[[Sequence[str], float, int], RunResult]
_SAFE_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}
_VERIFIER_BYTES = 8192
_METADATA_BYTES = 65536
_APK_VERIFIED = re.compile(
    r"(?m)^Verified using v[123] scheme(?: \([^\r\n]*\))?: true\s*$", re.ASCII
)
_MESSAGES = {
    "NOT_FOUND": "Artifact is unavailable",
    "UNSUPPORTED_MIME": "Artifact is not an APK or AAB",
    "INVALID_ARCHIVE": "Archive failed validation",
    "UNTRUSTED_ARCHIVE_PATH": "Unsafe archive entry",
    "DUPLICATE_ARCHIVE_PATH": "Duplicate archive entry",
    "RESOURCE_LIMIT": "Archive resource limit exceeded",
    "COMPRESSION_LIMIT": "Archive compression limit exceeded",
    "MANIFEST_UNAVAILABLE": "Manifest metadata is unavailable",
    "SIGNATURE_UNAVAILABLE": "Signature verifier is unavailable",
    "SIGNATURE_REJECTED": "Signature was not verified",
    "VERIFY_TIMEOUT": "Verifier exceeded its time budget",
    "VERIFY_OUTPUT_LIMIT": "Verifier exceeded its output budget",
    "VERIFY_FAILED": "Signature verifier failed",
    "INSPECTION_FAILED": "Archive inspection failed",
}


def get_archive_output_schema() -> dict[str, Any]:
    value: Any = json.loads(
        files("android_mcp_host.wire_schemas")
        .joinpath("host-archive-inspection.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(value, dict):
        raise ValueError("Invalid packaged Host archive inspection schema")
    return value


def _result(status: str, archive: dict[str, Any] | None, errors: list[str]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "runtime": "host",
        "status": status,
        "archive": archive,
        "errors": [{"code": code, "message": _MESSAGES[code]} for code in errors[:3]],
    }


def _safe_verifier(executable: Path | None) -> bool:
    """The optional CLI is operator-pinned, not discovered from caller PATH."""
    if executable is None or not isinstance(executable, Path):
        return False
    if not executable.is_absolute() or ".." in executable.parts:
        return False
    try:
        if any(part.is_symlink() for part in (executable, *executable.parents)):
            return False
        info = executable.stat()
        return (
            stat.S_ISREG(info.st_mode)
            and bool(info.st_mode & 0o111)
            and info.st_size > 0
            and os.access(executable, os.X_OK)
        )
    except OSError:
        return False


def _safe_run(argv: Sequence[str], seconds: float, limit: int) -> RunResult:
    return bounded_run(argv, seconds, limit, env=_SAFE_ENV)


@contextmanager
def _private_archive(payload: bytes, mime: str) -> Iterator[Path]:
    """Temp paths are private, bounded, deterministic names under a random root."""
    with tempfile.TemporaryDirectory(prefix="android-mcp-inspect-") as directory:
        target = Path(directory) / ("input.apk" if mime == APK else "input.aab")
        fd = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
        yield target


class ArchiveInspector:
    """Never runs arbitrary tasks, installs packages or uses an Android target."""

    def __init__(
        self,
        store: PrivateArtifactStore,
        owner: str,
        *,
        apk_verifier: Path | None = None,
        aab_verifier: Path | None = None,
        apk_metadata_tool: Path | None = None,
        aab_metadata_tool: Path | None = None,
        runner: Runner = _safe_run,
        timeout_s: float = 5.0,
    ) -> None:
        if not store.validate_owner(owner):
            raise ValueError("Invalid trusted archive owner")
        if type(timeout_s) not in (int, float) or not 0 < timeout_s <= 5:
            raise ValueError("Invalid verifier execution budget")
        self._store = store
        self._owner = owner
        self._apk_verifier = apk_verifier
        self._aab_verifier = aab_verifier
        self._apk_metadata_tool = apk_metadata_tool
        self._aab_metadata_tool = aab_metadata_tool
        self._runner = runner
        self._timeout_s = timeout_s

    def _signature(self, payload: bytes, mime: str) -> tuple[dict[str, str], str | None]:
        """Signed archive verification needs a configured, working vendor CLI.

        A META-INF marker, checksum or invented text fixture is never a signature.
        Never expose untrusted tool stdout, stderr, invocation path or credentials.
        """
        executable = self._apk_verifier if mime == APK else self._aab_verifier
        tool = "apksigner" if mime == APK else "jarsigner"
        if not _safe_verifier(executable):
            return {"state": "unavailable", "tool": tool, "reason": "NOT_CONFIGURED"}, (
                "SIGNATURE_UNAVAILABLE"
            )
        assert executable is not None
        try:
            with _private_archive(payload, mime) as target:
                argv = (
                    [str(executable), "verify", "--verbose", str(target)]
                    if mime == APK
                    else [str(executable), "-verify", "-strict", str(target)]
                )
                result = self._runner(argv, self._timeout_s, _VERIFIER_BYTES)
        except subprocess.TimeoutExpired:
            return {"state": "unavailable", "tool": tool, "reason": "TIMEOUT"}, ("VERIFY_TIMEOUT")
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
            return {"state": "unavailable", "tool": tool, "reason": "FAILED"}, ("VERIFY_FAILED")
        if result.truncated:
            return {"state": "unavailable", "tool": tool, "reason": "OUTPUT_LIMIT"}, (
                "VERIFY_OUTPUT_LIMIT"
            )
        if mime == APK:
            verified = (
                result.returncode == 0
                and re.search(r"(?m)^Verifies\s*$", result.stdout) is not None
                and _APK_VERIFIED.search(result.stdout) is not None
            )
        else:
            verified = (
                result.returncode == 0
                and re.search(r"(?m)^\s*jar verified\.\s*$", result.stdout) is not None
            )
        if not verified:
            return {"state": "rejected", "tool": tool, "reason": "NOT_VERIFIED"}, (
                "SIGNATURE_REJECTED"
            )
        return {"state": "verified", "tool": tool, "reason": "VERIFIED"}, None

    def _vendor_manifest(self, payload: bytes, mime: str) -> dict[str, Any] | None:
        """Read compiled Android manifests only through operator-pinned CLIs.

        aapt2 understands compiled APK AXML; bundletool dumps AAB protobuf
        XML. Without an eligible tool the output remains explicitly partial.
        """
        executable = self._apk_metadata_tool if mime == APK else self._aab_metadata_tool
        if not _safe_verifier(executable):
            return None
        assert executable is not None
        try:
            with _private_archive(payload, mime) as target:
                argv = (
                    [str(executable), "dump", "badging", str(target)]
                    if mime == APK
                    else [
                        str(executable),
                        "dump",
                        "manifest",
                        f"--bundle={target}",
                        "--module=base",
                    ]
                )
                result = self._runner(argv, self._timeout_s, _METADATA_BYTES)
        except (
            subprocess.TimeoutExpired,
            OSError,
            ValueError,
            RuntimeError,
            subprocess.SubprocessError,
        ):
            return None
        if result.returncode != 0 or result.truncated:
            return None
        return (
            parse_aapt2_badging(result.stdout)
            if mime == APK
            else parse_bundletool_manifest(result.stdout)
        )

    def inspect(self, handle: str) -> dict[str, Any]:
        """Return only bounded synthetic/verified metadata to the caller."""
        public = self._store.public_metadata(self._owner, handle)
        if public["status"] != "ok":
            return _result("not_found", None, ["NOT_FOUND"])
        record: dict[str, Any] = public["artifact"]
        mime = record["mime_type"]
        if mime not in {APK, AAB}:
            return _result("invalid", None, ["UNSUPPORTED_MIME"])
        try:
            content = self._store.read(self._owner, handle)
            metadata, warnings = inspect_zip(content, mime)
        except ArtifactStoreError:
            return _result("not_found", None, ["NOT_FOUND"])
        except ArchiveValidationError as error:
            code = error.code if error.code in _MESSAGES else "INVALID_ARCHIVE"
            return _result("invalid", None, [code])
        if "MANIFEST_UNAVAILABLE" in warnings:
            vendor = self._vendor_manifest(content, mime)
            if vendor is not None:
                metadata.update(vendor)
                warnings.remove("MANIFEST_UNAVAILABLE")
        signature, issue = self._signature(content, mime)
        if issue is not None:
            warnings.append(issue)
        archive = {
            "handle": record["handle"],
            "mime_type": mime,
            "sha256": record["sha256"],
            "size_bytes": record["size_bytes"],
            **metadata,
            "signature": signature,
        }
        return _result("ok" if not warnings else "partial", archive, warnings)
