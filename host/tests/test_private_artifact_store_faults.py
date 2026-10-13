"""H2.c bounded persistence, concurrent handles and access-control adversarial tests."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

import android_mcp_host.private_artifact_store as artifacts
from android_mcp_host.server import create_server

OWNER = "private-owner-1"
MIME = "application/octet-stream"


def store(tmp_path: Path, **kwargs: Any) -> artifacts.PrivateArtifactStore:
    return artifacts.PrivateArtifactStore(tmp_path / "vault", **kwargs)


def denied(action: Any, code: str) -> None:
    with pytest.raises(artifacts.ArtifactStoreError) as failure:
        action()
    assert failure.value.code == code
    assert "SECRET" not in str(failure.value)


@pytest.mark.parametrize(
    "root",
    [
        Path("relative/vault"),
        Path("/tmp/" + "x" * 1100),
        Path("/tmp/a/../vault"),
    ],
)
def test_constructor_rejects_untrusted_root_form(root: Path) -> None:
    denied(lambda: artifacts.PrivateArtifactStore(root), "UNTRUSTED_ROOT")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_artifact_bytes": 0},
        {"max_artifact_bytes": 67108865},
        {"max_artifact_bytes": True},
        {"max_total_bytes": 0},
        {"max_total_bytes": 536870913},
        {"max_total_bytes": True},
        {"max_records": 0},
        {"max_records": 4097},
        {"max_records": True},
    ],
)
def test_invalid_quota_is_never_silently_accepted(tmp_path: Path, kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="quota"):
        store(tmp_path, **kwargs)


@pytest.mark.parametrize(
    "owner",
    ["", "../escaped", "a/b", "SECRET USER", "x" * 65, None, 42],
)
def test_malformed_owner_cannot_be_stored(tmp_path: Path, owner: Any) -> None:
    service = store(tmp_path)
    assert service.validate_owner(owner) is False
    denied(lambda: service.put(owner, b"test", mime_type=MIME), "INVALID_OWNER")


@pytest.mark.parametrize("content", [b"", bytearray(b"test"), "text", None, b"x" * 20])
def test_invalid_content_and_over_limit_are_denied(tmp_path: Path, content: Any) -> None:
    service = store(tmp_path, max_artifact_bytes=12)
    code = "ARTIFACT_TOO_LARGE" if isinstance(content, bytes) else "INVALID_CONTENT"
    denied(lambda: service.put(OWNER, content, mime_type=MIME), code)


@pytest.mark.parametrize("seconds", [0, -5, 604801, float("nan"), float("inf"), True, "forever"])
def test_ttl_must_be_positive_finite_and_bounded(tmp_path: Path, seconds: Any) -> None:
    service = store(tmp_path)
    denied(
        lambda: service.put(OWNER, b"private fixture", mime_type=MIME, ttl_s=seconds),
        "INVALID_TTL",
    )


@pytest.mark.parametrize("filename", [123, None, "report.txt", "logs_2026.json"])
def test_filename_is_not_stored_or_disclosed(tmp_path: Path, filename: Any) -> None:
    service = store(tmp_path)
    if filename is None or isinstance(filename, str):
        metadata = service.put(OWNER, b"generated", mime_type=MIME, filename=filename)
        assert filename is None or filename not in str(metadata)
    else:
        denied(
            lambda: service.put(OWNER, b"generated", mime_type=MIME, filename=filename),
            "INVALID_FILENAME",
        )


def test_metadata_handle_invalid_shape_and_wrong_owner_same_denial(
    tmp_path: Path,
) -> None:
    service = store(tmp_path)
    metadata = service.put(OWNER, b"private", mime_type=MIME)
    for identifier in ("bad", metadata["sha256"], "art_../", None, 13):
        denied(lambda identifier=identifier: service.read(OWNER, identifier), "NOT_FOUND")
        assert service.revoke(OWNER, identifier) is False
        assert service.public_metadata(OWNER, identifier)["status"] == "not_found"
    assert service.list_metadata("another-owner") == []
    assert service.read(OWNER, metadata["handle"]) == b"private"


def test_duplicate_handles_revoke_independently_and_bytes_survive(
    tmp_path: Path,
) -> None:
    service = store(tmp_path)
    a = service.put(OWNER, b"same bytes", mime_type=MIME)
    b = service.put(OWNER, b"same bytes", mime_type=MIME)
    assert a["handle"] != b["handle"]
    assert len(list((tmp_path / "vault" / "objects").iterdir())) == 1
    assert service.revoke(OWNER, a["handle"]) is True
    service.cleanup()
    denied(lambda: service.read(OWNER, a["handle"]), "NOT_FOUND")
    assert service.read(OWNER, b["handle"]) == b"same bytes"
    assert len(list((tmp_path / "vault" / "objects").iterdir())) == 1
    service.revoke(OWNER, b["handle"])
    service.cleanup()
    assert list((tmp_path / "vault" / "objects").iterdir()) == []


def test_same_bytes_are_isolated_physically_across_owners(tmp_path: Path) -> None:
    service = store(tmp_path)
    a = service.put(OWNER, b"same", mime_type=MIME)
    b = service.put("different-owner", b"same", mime_type=MIME)
    assert a["sha256"] == b["sha256"]
    assert a["handle"] != b["handle"]
    assert len(list((tmp_path / "vault" / "objects").iterdir())) == 2
    denied(lambda: service.read(OWNER, b["handle"]), "NOT_FOUND")
    denied(lambda: service.read("different-owner", a["handle"]), "NOT_FOUND")


def test_record_quota_even_when_content_is_deduplicated(tmp_path: Path) -> None:
    service = store(tmp_path, max_records=2)
    a = service.put(OWNER, b"a", mime_type=MIME)
    b = service.put(OWNER, b"a", mime_type=MIME)
    denied(lambda: service.put(OWNER, b"a", mime_type=MIME), "QUOTA_EXCEEDED")
    assert service.revoke(OWNER, a["handle"])
    service.cleanup()
    c = service.put(OWNER, b"a", mime_type=MIME)
    assert c["handle"] != b["handle"]


def test_recover_orphan_temp_and_content_files_without_trusting_data(
    tmp_path: Path,
) -> None:
    store(tmp_path)
    root = tmp_path / "vault"
    partial = root / "objects" / "tmp-aabbcc"
    partial.write_bytes(b"SECRET_TEMP")
    orphan = root / "objects" / ("1" * 64)
    orphan.write_bytes(b"SECRET_ORPHAN")
    reopened = store(tmp_path)
    assert reopened.list_metadata(OWNER) == []
    assert not partial.exists() and not orphan.exists()
    assert reopened.cleanup()["remaining_records"] == 0


def test_unknown_or_symlink_in_object_directory_denies_recovery(
    tmp_path: Path,
) -> None:
    store(tmp_path)
    objects = tmp_path / "vault" / "objects"
    unknown = objects / "personal-finances.txt"
    unknown.write_text("SECRET_EXAMPLE")
    denied(lambda: store(tmp_path), "INTEGRITY_FAIL")
    assert unknown.read_text() == "SECRET_EXAMPLE"
    unknown.unlink()
    outside = tmp_path / "outside-file"
    outside.write_text("SECRET_0000")
    link = objects / ("2" * 64)
    link.symlink_to(outside)
    denied(lambda: store(tmp_path), "INTEGRITY_FAIL")
    assert outside.read_text() == "SECRET_0000"


def test_recovery_scan_limit_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store(tmp_path)
    object_dir = tmp_path / "vault" / "objects"
    for n in range(4):
        (object_dir / ("tmp-" + str(n))).write_bytes(b"fixture")
    with monkeypatch.context() as scoped:
        scoped.setattr(artifacts, "SCAN_LIMIT", 3)
        denied(lambda: store(tmp_path), "RESOURCE_LIMIT")
    service = store(tmp_path)
    assert service.cleanup()["remaining_records"] == 0


def test_object_bad_mode_size_digest_and_hardlink_cannot_be_read(
    tmp_path: Path,
) -> None:
    service = store(tmp_path)
    payload = b"private bytes"
    metadata = service.put(OWNER, payload, mime_type=MIME)
    path = next((tmp_path / "vault" / "objects").iterdir())
    path.chmod(0o644)
    denied(lambda: service.read(OWNER, metadata["handle"]), "INTEGRITY_FAIL")
    path.chmod(0o600)
    link = tmp_path / "vault" / "hardlink"
    os.link(path, link)
    denied(lambda: service.read(OWNER, metadata["handle"]), "INTEGRITY_FAIL")
    link.unlink()
    path.write_bytes(b"different contents same length")
    denied(lambda: service.read(OWNER, metadata["handle"]), "INTEGRITY_FAIL")
    path.write_bytes(b"different btes")
    denied(lambda: service.read(OWNER, metadata["handle"]), "INTEGRITY_FAIL")


def test_corrupt_object_key_never_becomes_an_absolute_path(tmp_path: Path) -> None:
    service = store(tmp_path)
    denied(lambda: service._read_object("../secret", "a" * 64, 1), "INTEGRITY_FAIL")
    denied(lambda: service._read_object("b" * 64, "a" * 64, 1), "INTEGRITY_FAIL")


def test_object_create_disk_failure_leaves_no_partial_trusted_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = store(tmp_path)
    original_replace = os.replace

    def broken_replace(src: Any, dst: Any) -> None:
        raise OSError("SECRET DISK FULL")

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "replace", broken_replace)
        denied(
            lambda: service.put(OWNER, b"private failed write", mime_type=MIME),
            "STORAGE_FAILURE",
        )
    assert os.replace is original_replace
    assert service.list_metadata(OWNER) == []
    assert list((tmp_path / "vault" / "objects").iterdir()) == []


def test_invalid_or_colliding_random_token_never_becomes_live_artifact(
    tmp_path: Path,
) -> None:
    invalid = store(tmp_path, token_factory=lambda n: "/" * 32)
    denied(lambda: invalid.put(OWNER, b"bad token", mime_type=MIME), "STORAGE_FAILURE")
    fixed = store(tmp_path, token_factory=lambda n: "z" * 32)
    first = fixed.put(OWNER, b"first", mime_type=MIME)
    assert first["handle"] == "art_" + "z" * 32
    denied(lambda: fixed.put(OWNER, b"second", mime_type=MIME), "STORAGE_FAILURE")
    assert len(fixed.list_metadata(OWNER)) == 1
    recovered = store(tmp_path)
    assert len(recovered.list_metadata(OWNER)) == 1


def test_symlinked_index_and_invalid_secret_files_block_store_init(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    service = store(tmp_path)
    assert service.list_metadata(OWNER) == []
    index = root / "index.sqlite3"
    original = root / "original-index"
    index.rename(original)
    index.symlink_to(original)
    denied(lambda: store(tmp_path), "UNTRUSTED_ROOT")
    index.unlink()
    original.rename(index)
    secret = root / ".secret"
    secret.chmod(0o644)
    denied(lambda: store(tmp_path), "UNTRUSTED_ROOT")


def test_permission_or_sqlite_failure_does_not_serialize_exception_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = store(tmp_path)
    with monkeypatch.context() as scoped:

        def db_down(*args: Any, **kwargs: Any) -> Any:
            raise sqlite3.OperationalError("SECRET database unavailable")

        scoped.setattr(artifacts.sqlite3, "connect", db_down)
        denied(lambda: service.list_metadata(OWNER), "STORAGE_FAILURE")


def test_artifact_tool_only_exists_with_matching_trusted_owner_and_store(tmp_path: Path) -> None:
    service = store(tmp_path)
    with pytest.raises(ValueError, match="trusted store and owner"):
        create_server(artifact_store=service)
    with pytest.raises(ValueError, match="trusted store and owner"):
        create_server(artifact_owner=OWNER)
    with pytest.raises(ValueError, match="Invalid Host artifact owner"):
        create_server(artifact_store=service, artifact_owner="../other")


def test_injected_bogus_owner_or_invalid_token_is_not_a_metadata_oracle(
    tmp_path: Path,
) -> None:
    service = store(tmp_path)
    artifact = service.put(OWNER, b"synthetic", mime_type=MIME)
    a = service.public_metadata("../../other", artifact["handle"])
    b = service.public_metadata(OWNER, "art_" + "0" * 32)
    assert a == b
    assert "synthetic" not in str(a)
    assert str(tmp_path) not in str(a)
