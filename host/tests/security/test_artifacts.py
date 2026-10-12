import hashlib
from pathlib import Path

import pytest

from android_mcp_host.security.artifacts import (
    ArtifactError,
    remove_staged,
    stage_apk,
    verify_staged,
)


def _fixture(secure_dir: Path):
    root = secure_dir / "allowed"
    root.mkdir(mode=0o700)
    staging = secure_dir / "staging"
    staging.mkdir(mode=0o700)
    path = root / "demo.apk"
    path.write_bytes(b"PK\x03\x04" + b"approved" * 1000)
    return root, staging, path


def test_staged_artifact_binds_bytes_and_cleanup_is_idempotent(secure_dir):
    root, staging, path = _fixture(secure_dir)
    result = stage_apk(path, allowed_roots=(root,), staging_dir=staging)
    assert result.path != path
    assert result.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result.size == len(path.read_bytes())
    assert verify_staged(result)
    path.write_bytes(b"PK\x03\x04untrusted-replacement")
    assert verify_staged(result)
    remove_staged(result)
    assert not result.path.exists()
    remove_staged(result)


def test_staged_bytes_tampered_are_rejected(secure_dir):
    root, staging, path = _fixture(secure_dir)
    result = stage_apk(path, allowed_roots=(root,), staging_dir=staging)
    result.path.chmod(0o600)
    result.path.write_bytes(b"PK\x03\x04" + b"changed" * 200)
    assert not verify_staged(result)
    remove_staged(result)


def test_replacement_inode_cannot_be_deleted(secure_dir):
    root, staging, path = _fixture(secure_dir)
    result = stage_apk(path, allowed_roots=(root,), staging_dir=staging)
    result.path.unlink()
    result.path.write_bytes(b"replacement")
    remove_staged(result)
    assert result.path.exists()


def test_no_path_outside_allowed_roots(secure_dir):
    root, staging, path = _fixture(secure_dir)
    rogue = secure_dir / "secret.apk"
    rogue.write_bytes(path.read_bytes())
    with pytest.raises(ArtifactError, match="outside"):
        stage_apk(rogue, allowed_roots=(root,), staging_dir=staging)
    assert not list(staging.iterdir())


def test_symlink_source_is_rejected(secure_dir):
    root, staging, path = _fixture(secure_dir)
    linked = root / "linked.apk"
    linked.symlink_to(path)
    with pytest.raises(ArtifactError, match="linked"):
        stage_apk(linked, allowed_roots=(root,), staging_dir=staging)


def test_bad_zip_or_size_are_refused(secure_dir):
    root, staging, path = _fixture(secure_dir)
    path.write_bytes(b"NOPE" + b"irrelevant")
    with pytest.raises(ArtifactError, match="ZIP"):
        stage_apk(path, allowed_roots=(root,), staging_dir=staging)
    assert list(staging.iterdir()) == []
    path.write_bytes(b"PK\x03\x04" + b"too big")
    with pytest.raises(ArtifactError, match="size"):
        stage_apk(path, allowed_roots=(root,), staging_dir=staging, max_bytes=5)
    assert list(staging.iterdir()) == []


def test_staging_dir_must_be_private(secure_dir):
    root, staging, path = _fixture(secure_dir)
    staging.chmod(0o755)
    with pytest.raises(ArtifactError, match="0700"):
        stage_apk(path, allowed_roots=(root,), staging_dir=staging)
    staging.chmod(0o700)
    staging.rmdir()
    with pytest.raises(ArtifactError, match="already exist"):
        stage_apk(path, allowed_roots=(root,), staging_dir=staging)


def test_validate_input_and_missing_file(secure_dir):
    root, staging, path = _fixture(secure_dir)
    for invalid in (Path("relative.apk"), secure_dir / "none.apk", root / "file.txt"):
        with pytest.raises(ArtifactError):
            stage_apk(invalid, allowed_roots=(root,), staging_dir=staging)
    for invalid in (0, 3, 2 * 1024**3 + 1):
        with pytest.raises(ValueError):
            stage_apk(path, allowed_roots=(root,), staging_dir=staging, max_bytes=invalid)


def test_symlink_staged_path_fails_verification(secure_dir):
    root, staging, path = _fixture(secure_dir)
    result = stage_apk(path, allowed_roots=(root,), staging_dir=staging)
    result.path.unlink()
    result.path.symlink_to(path)
    assert not verify_staged(result)
    remove_staged(result)
    assert result.path.is_symlink()


def test_source_swapping_is_detected_before_copy(monkeypatch, secure_dir):
    import android_mcp_host.security.artifacts as module

    root, staging, path = _fixture(secure_dir)
    original_open = module.os.open

    def swap_file(name, *args, **kwargs):
        if Path(name) == path:
            source = path.with_suffix(".old")
            path.rename(source)
            path.write_bytes(b"PK\x03\x04other")
            # Open the previous inode, while the pathname now points elsewhere.
            return original_open(source, *args, **kwargs)
        return original_open(name, *args, **kwargs)

    monkeypatch.setattr(module.os, "open", swap_file)
    with pytest.raises(ArtifactError, match="changed"):
        stage_apk(path, allowed_roots=(root,), staging_dir=staging)


def test_file_grows_beyond_cap_during_copy(secure_dir, monkeypatch):
    import android_mcp_host.security.artifacts as module

    root, staging, path = _fixture(secure_dir)
    path.write_bytes(b"PK\x03\x04" + b"small")
    real = module.tempfile.mkstemp

    def append_before_copy(*args, **kwargs):
        with path.open("ab") as handle:
            handle.write(b"X" * 1024)
        return real(*args, **kwargs)

    monkeypatch.setattr(module.tempfile, "mkstemp", append_before_copy)
    with pytest.raises(ArtifactError, match="grew"):
        stage_apk(path, allowed_roots=(root,), staging_dir=staging, max_bytes=100)
    assert list(staging.iterdir()) == []


def test_file_changes_within_cap_during_copy(secure_dir, monkeypatch):
    import android_mcp_host.security.artifacts as module

    root, staging, path = _fixture(secure_dir)
    real = module.tempfile.mkstemp

    def append_before_copy(*args, **kwargs):
        with path.open("ab") as handle:
            handle.write(b"X")
        return real(*args, **kwargs)

    monkeypatch.setattr(module.tempfile, "mkstemp", append_before_copy)
    with pytest.raises(ArtifactError, match="changed"):
        stage_apk(path, allowed_roots=(root,), staging_dir=staging)
    assert list(staging.iterdir()) == []


def test_missing_staged_file_fails_verification(secure_dir):
    root, staging, path = _fixture(secure_dir)
    result = stage_apk(path, allowed_roots=(root,), staging_dir=staging)
    result.path.unlink()
    assert not verify_staged(result)
