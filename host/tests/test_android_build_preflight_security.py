"""H2.b pinned project, Git authorization and malformed provider security tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from test_android_build_preflight import (
    COMMIT,
    GitRunner,
    Inventory,
    checked,
    code,
    make_project,
    service,
)

import android_mcp_host.android_build_preflight as bp


def test_corrupt_wrapper_jar_or_zip_without_main_entry_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    import io
    import zipfile

    root, checksum = make_project(tmp_path)
    original = bp.zipfile.is_zipfile
    with monkeypatch.context() as scope:
        scope.setattr(bp.zipfile, "is_zipfile", lambda stream: True)

        def bad_zip(stream: io.BytesIO) -> zipfile.ZipFile:
            raise zipfile.BadZipFile("secret corrupt entry")

        scope.setattr(bp.zipfile, "ZipFile", bad_zip)
        reply = checked(service(root, checksum).plan())
        assert code(reply) == ["WRAPPER_UNVERIFIED"]
    assert bp.zipfile.is_zipfile is original

    jar = root / "android/gradle/wrapper/gradle-wrapper.jar"
    with zipfile.ZipFile(jar, "w") as archive:
        archive.writestr("not-the-gradle-wrapper.class", b"fake")
    checksum = hashlib.sha256(jar.read_bytes()).hexdigest()
    result = checked(service(root, checksum).plan())
    assert code(result) == ["WRAPPER_UNVERIFIED"]

    with zipfile.ZipFile(jar, "w") as archive:
        for index in range(513):
            archive.writestr(f"entry-{index:04d}.class", b"")
        archive.writestr("org/gradle/wrapper/GradleWrapperMain.class", b"fake")
    checksum = hashlib.sha256(jar.read_bytes()).hexdigest()
    result = checked(service(root, checksum).plan())
    assert code(result) == ["WRAPPER_UNVERIFIED"]


def test_bad_local_inventory_payload_or_unbounded_version_denies_plan(tmp_path: Path) -> None:
    root, checksum = make_project(tmp_path)

    class BrokenInventory:
        def __init__(self, result: Any) -> None:
            self.result = result

        def inspect(self) -> Any:
            return self.result

    versions = {
        key: {"runnable": True, "version": value}
        for key, value in {
            "jdk17": "17.0.20",
            "sdk_platform": "36",
            "gradle": "9.6",
            "build_tools": "36.0.0",
        }.items()
    }
    for payload in (
        [],
        "malformed",
        {},
        {"tools": []},
        {"tools": None},
        {"tools": {**versions, "jdk17": {"runnable": True, "version": None}}},
        {"tools": {**versions, "jdk17": {"runnable": True, "version": "x" * 200}}},
        {"tools": {**versions, "jdk17": {"runnable": True, "version": "秘密"}}},
    ):
        result = checked(
            bp.AndroidBuildPreflight(
                root,
                expected_revision=COMMIT,
                expected_wrapper_sha256=checksum,
                inventory=BrokenInventory(payload),  # type: ignore[arg-type]
                runner=GitRunner(),
            ).plan()
        )
        assert result["status"] == "unavailable"
        assert code(result) == ["TOOLCHAIN_UNAVAILABLE"]
        assert result["tasks"] == [] and result["argv_preview"] == []


def test_malformed_git_sha_never_reaches_subsequent_status_or_toolchain(tmp_path: Path) -> None:
    root, checksum = make_project(tmp_path)
    reader = GitRunner(revision="not-a-sha")
    inventory = Inventory()
    reply = checked(service(root, checksum, runner=reader, inventory=inventory).plan())
    assert reply["status"] == "blocked"
    assert code(reply) == ["REVISION_UNVERIFIED"]
    assert len(reader.calls) == 1 and inventory.calls == 0


def test_chosen_build_root_path_is_capped_to_schema_size() -> None:
    with pytest.raises(ValueError, match="trusted absolute"):
        bp.AndroidBuildPreflight(Path("/" + "x" * 1100))


def test_root_filesystem_errors_are_typed_and_never_exec_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, checksum = make_project(tmp_path)
    reader = GitRunner()
    original = Path.is_dir

    def blocked(self: Path) -> bool:
        if self == root:
            raise OSError("SECRET_ACCOUNT_INFORMATION")
        return original(self)

    with monkeypatch.context() as scope:
        scope.setattr(Path, "is_dir", blocked)
        result = checked(service(root, checksum, runner=reader).plan())
        assert result["status"] == "blocked"
        assert code(result) == ["PROJECT_ROOT_UNTRUSTED"]
        assert reader.calls == []
        assert "SECRET_ACCOUNT_INFORMATION" not in str(result)
