"""H2.c hostile MIME, private root and secret-file utility regressions."""

from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path
from typing import Any

import pytest

import android_mcp_host.private_artifact_support as support
from android_mcp_host.private_artifact_store import ArtifactStoreError


def fails(func: Any, code: str) -> None:
    with pytest.raises(ArtifactStoreError) as error:
        func()
    assert error.value.code == code


def test_schema_resource_requires_a_json_object(monkeypatch: pytest.MonkeyPatch) -> None:
    class Resource:
        def joinpath(self, name: str) -> Resource:
            assert name == "host-private-artifact-metadata.v1.schema.json"
            return self

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return "[]"

    monkeypatch.setattr(support, "files", lambda _: Resource())
    with pytest.raises(ValueError, match="Invalid packaged"):
        support.get_artifact_metadata_schema()


def test_private_directory_create_valid_existing_and_symlink_refusal(tmp_path: Path) -> None:
    root = tmp_path / "secure"
    support._private_directory(root)
    assert root.is_dir() and root.stat().st_mode & 0o777 == 0o700
    support._private_directory(root)
    linked = tmp_path / "linked"
    linked.symlink_to(root, target_is_directory=True)
    fails(lambda: support._private_directory(linked), "UNTRUSTED_ROOT")
    root.chmod(0o755)
    fails(lambda: support._private_directory(root), "UNTRUSTED_ROOT")
    root.chmod(0o700)
    file = tmp_path / "ordinary-file"
    file.write_bytes(b"fixture")
    fails(lambda: support._private_directory(file), "UNTRUSTED_ROOT")


def test_private_directory_wrong_owner_and_os_failure_are_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "secured"
    support._private_directory(root)
    monkeypatch.setattr(support.os, "getuid", lambda: -1)
    fails(lambda: support._private_directory(root), "UNTRUSTED_ROOT")
    with monkeypatch.context() as scoped:
        scoped.undo()
    missing = tmp_path / "missing"

    def failed_mkdir(self: Path, *args: Any, **kwargs: Any) -> None:
        raise PermissionError("SECRET HOME")

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "mkdir", failed_mkdir)
        fails(lambda: support._private_directory(missing), "UNTRUSTED_ROOT")


def test_secret_is_private_32_bytes_and_reusable_after_restart(tmp_path: Path) -> None:
    private = tmp_path / "secret"
    first = support._read_secret(private)
    assert len(first) == 32
    assert support._read_secret(private) == first
    assert private.stat().st_mode & 0o777 == 0o600


def test_secret_symlink_bad_size_public_permissions_and_hardlink_denied(tmp_path: Path) -> None:
    private = tmp_path / "secret"
    private.write_bytes(b"too short")
    fails(lambda: support._read_secret(private), "UNTRUSTED_ROOT")
    private.write_bytes(b"s" * 32)
    private.chmod(0o644)
    fails(lambda: support._read_secret(private), "UNTRUSTED_ROOT")
    private.chmod(0o600)
    hard = tmp_path / "another-link"
    os.link(private, hard)
    fails(lambda: support._read_secret(private), "UNTRUSTED_ROOT")
    hard.unlink()
    private.unlink()
    private.symlink_to(tmp_path / "untrusted-target")
    fails(lambda: support._read_secret(private), "UNTRUSTED_ROOT")


def test_secret_read_error_is_redacted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    private = tmp_path / "secret"
    private.write_bytes(b"0" * 32)
    original_read = Path.read_bytes

    def broken_read(self: Path) -> bytes:
        if self == private:
            raise PermissionError("PRIVATE PII")
        return original_read(self)

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "read_bytes", broken_read)
        fails(lambda: support._read_secret(private), "UNTRUSTED_ROOT")
    private.unlink()
    original_open = support.os.open

    def broken_open(path: Any, *args: Any, **kwargs: Any) -> int:
        if Path(path) == private:
            raise PermissionError("PRIVATE CREDENTIAL")
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(support.os, "open", broken_open)
        fails(lambda: support._read_secret(private), "UNTRUSTED_ROOT")


@pytest.mark.parametrize(
    ("mime", "data"),
    [
        ("image/png", b"\x89PNG\r\n\x1a\nimage"),
        ("image/jpeg", b"\xff\xd8\xffimage"),
        ("application/pdf", b"%PDF-1.7\nfixture"),
        ("text/plain", b"Hello, fixture!\n"),
        ("application/json", b'{"test":true}'),
        ("application/octet-stream", b"\x00\x01\xff"),
    ],
)
def test_valid_declared_mime_does_not_transform_content(mime: str, data: bytes) -> None:
    assert support._validate_mime(data, mime) is None


@pytest.mark.parametrize(
    ("mime", "data", "code"),
    [
        ("application/shellscript", b"#!/bin/sh", "UNSUPPORTED_MIME"),
        ("image/png", b"not a png", "MIME_MISMATCH"),
        ("image/jpeg", b"jpeg? not really", "MIME_MISMATCH"),
        ("application/pdf", b"pdf with no header", "MIME_MISMATCH"),
        ("text/plain", b"Binary\x00hidden", "MIME_MISMATCH"),
        ("text/plain", b"\xff invalid utf8", "MIME_MISMATCH"),
        ("application/json", b"{ invalid: json }", "MIME_MISMATCH"),
        ("application/json", b"\xff invalid json", "MIME_MISMATCH"),
        ("application/zip", b"PK\x03\x04not complete", "MIME_MISMATCH"),
        ("application/vnd.android.aab", b"not a bundle", "MIME_MISMATCH"),
        ("application/vnd.android.package-archive", b"not an apk", "MIME_MISMATCH"),
    ],
)
def test_mime_validation_refuses_forged_types(mime: str, data: bytes, code: str) -> None:
    fails(lambda: support._validate_mime(data, mime), code)


@pytest.mark.parametrize(
    "mime",
    ["application/zip", "application/vnd.android.package-archive", "application/vnd.android.aab"],
)
def test_valid_zip_backed_artifact_types(mime: str) -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("META-INF/com.example.fixture", b"synthetic")
    assert support._validate_mime(output.getvalue(), mime) is None


def test_parent_path_with_link_is_untrusted(tmp_path: Path) -> None:
    actual = tmp_path / "original"
    actual.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(actual, target_is_directory=True)
    fails(lambda: support._private_directory(link / "vault"), "UNTRUSTED_ROOT")
    assert not (actual / "vault").exists()
