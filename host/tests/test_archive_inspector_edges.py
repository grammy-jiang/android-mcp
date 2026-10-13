"""Adversarial H2.e archive and private verifier regressions."""

from __future__ import annotations

import asyncio
import io
import json
import socket
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from test_apk_aab_inspection import AAB, APK, MANIFEST, OWNER, fixture, owner_store, put, verifier

import android_mcp_host.archive_inspector as inspector
import android_mcp_host.archive_validation as validation
from android_mcp_host.command_runner import RunResult
from android_mcp_host.private_artifact_support import ArtifactStoreError


@pytest.mark.parametrize(
    "name",
    ["", "bad\x00name", "bad\nname", "x" * 257, "C:/fake", "trailing//slash", "./wrong"],
)
def test_zip_path_rejection_direct_helper(name: str) -> None:
    assert not validation._safe_filename(name)


@pytest.mark.parametrize(
    "value",
    [
        b"",
        b"broken xml",
        b"<notmanifest/>",
        b"<!DOCTYPE manifest [ <!ENTITY x 'bad'> ]><manifest/>",
        b'<manifest package="org.example.demo">\x00</manifest>',
        MANIFEST.replace(b"org.example.demo", b"invalid/name"),
        MANIFEST.replace(b"org.example.demo", b"org.example." + b"z" * 130),
        MANIFEST.replace(b'android:versionCode="12"', b'android:versionCode="0"'),
        MANIFEST.replace(b'android:versionCode="12"', b'android:versionCode="2147483648"'),
        MANIFEST.replace(b'android:versionCode="12"', b'android:versionCode="not-a-number"'),
        MANIFEST.replace(b'android:versionName="1.2.3"', b'android:versionName="!bad"'),
        MANIFEST.replace(b"android.permission.INTERNET", b"bad permission with spaces"),
        MANIFEST.replace(b"<uses-permission", b"<not-permission"),
    ],
)
def test_literal_manifest_parser_fail_closed_or_exact(value: bytes) -> None:
    decoded = validation._manifest(value)
    if value.endswith(b'<not-permission android:name="android.permission.INTERNET" /></manifest>'):
        assert decoded is not None and decoded["permissions"] == []
    else:
        assert decoded is None


def test_parser_permission_quota_is_bounded() -> None:
    many = MANIFEST.replace(
        b'<uses-permission android:name="android.permission.INTERNET" />',
        b"".join(
            b'<uses-permission android:name="org.permission.TEST%02d" />' % index
            for index in range(65)
        ),
    )
    assert validation._manifest(many) is None


def test_zip_rejects_unsupported_mime_empty_bytes_and_too_many_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for content, kind, reason in (
        (fixture("apk"), "text/plain", "UNSUPPORTED_ARCHIVE"),
        (b"", APK, "RESOURCE_LIMIT"),
        (b"not-zip", APK, "INVALID_ARCHIVE"),
    ):
        with pytest.raises(validation.ArchiveValidationError) as error:
            validation.inspect_zip(content, kind)
        assert error.value.code == reason
    with monkeypatch.context() as scoped:
        scoped.setattr(validation, "MAX_ARCHIVE_MEMBERS", 1)
        with pytest.raises(validation.ArchiveValidationError, match="RESOURCE_LIMIT"):
            validation.inspect_zip(fixture("apk", **{"assets/extra": b"x"}), APK)


def test_zip_decompression_total_and_manifest_abi_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with monkeypatch.context() as scoped:
        scoped.setattr(validation, "MAX_UNCOMPRESSED_BYTES", 50)
        with pytest.raises(validation.ArchiveValidationError, match="RESOURCE_LIMIT"):
            validation.inspect_zip(fixture("apk"), APK)
    with monkeypatch.context() as scoped:
        scoped.setattr(validation, "MAX_MANIFEST_BYTES", 50)
        with pytest.raises(validation.ArchiveValidationError, match="RESOURCE_LIMIT"):
            validation.inspect_zip(fixture("apk"), APK)
    with monkeypatch.context() as scoped:
        scoped.setattr(validation, "MAX_ABIS", 1)
        with pytest.raises(validation.ArchiveValidationError, match="RESOURCE_LIMIT"):
            validation.inspect_zip(
                fixture(
                    "apk",
                    **{
                        "lib/arm64-v8a/libone.so": b"elf",
                        "lib/x86_64/libtwo.so": b"elf",
                    },
                ),
                APK,
            )


def test_no_manifest_returns_partial_without_synthetic_identifiers() -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as zf:
        zf.writestr("base/lib/arm64-v8a/one.so", b"elf")
    result, notes = validation.inspect_zip(stream.getvalue(), AAB)
    assert result["package_id"] is None
    assert result["abis"] == ["arm64-v8a"]
    assert notes == ["MANIFEST_UNAVAILABLE"]


def test_invalid_compression_header_and_crc_are_never_accepted() -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_BZIP2) as zf:
        zf.writestr("AndroidManifest.xml", MANIFEST)
    with pytest.raises(validation.ArchiveValidationError, match="INVALID_ARCHIVE"):
        validation.inspect_zip(stream.getvalue(), APK)

    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("AndroidManifest.xml", MANIFEST)
        zf.writestr("resources.arsc", b"CRC_FIXTURE_12345")
    corrupted = stream.getvalue().replace(b"CRC_FIXTURE_12345", b"CRC_FAILURE_1234")
    with pytest.raises(validation.ArchiveValidationError, match="INVALID_ARCHIVE"):
        validation.inspect_zip(corrupted, APK)

    # Central directory's general-purpose encryption flag must be rejected.
    encrypted = bytearray(stream.getvalue())
    central = encrypted.index(b"PK\x01\x02")
    encrypted[central + 8] |= 1
    with pytest.raises(validation.ArchiveValidationError, match="INVALID_ARCHIVE"):
        validation.inspect_zip(bytes(encrypted), APK)


def test_archive_inspector_bad_owner_quota_tool_exception_and_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = owner_store(tmp_path)
    with pytest.raises(ValueError, match="Invalid trusted"):
        inspector.ArchiveInspector(store, "invalid/owner")
    for value in (-1, 6, float("nan"), True):
        with pytest.raises(ValueError, match="budget"):
            inspector.ArchiveInspector(store, OWNER, timeout_s=value)
    other = put(store, b"plain fixture", "text/plain")
    assert inspector.ArchiveInspector(store, OWNER).inspect(other)["status"] == "invalid"
    handle = put(store, fixture("apk"))
    engine = inspector.ArchiveInspector(
        store,
        OWNER,
        apk_verifier=verifier(tmp_path),
        runner=lambda *args: (_ for _ in ()).throw(OSError("SECRET USER DATA")),
    )
    assert engine.inspect(handle)["archive"]["signature"]["state"] == "unavailable"
    with monkeypatch.context() as scoped:
        scoped.setattr(
            store, "read", lambda *args: (_ for _ in ()).throw(ArtifactStoreError("INTEGRITY_FAIL"))
        )
        assert inspector.ArchiveInspector(store, OWNER).inspect(handle)["status"] == "not_found"


def test_verifier_non_executable_and_schema_contract_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "nonexec"
    path.write_text("unknown tool", encoding="utf-8")
    assert not inspector._safe_verifier(path)
    assert not inspector._safe_verifier("str-path")  # type: ignore[arg-type]

    class Resource:
        def joinpath(self, name: str) -> Resource:
            assert name == "host-archive-inspection.v1.schema.json"
            return self

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return "[]"

    with monkeypatch.context() as scoped:
        scoped.setattr(inspector, "files", lambda _: Resource())
        with pytest.raises(ValueError, match="Invalid packaged"):
            inspector.get_archive_output_schema()


def test_apk_verifier_output_limited_and_no_false_positive(
    tmp_path: Path,
) -> None:
    store = owner_store(tmp_path)
    handle = put(store, fixture("apk"))
    tool = verifier(tmp_path)
    for result, expected in (
        (RunResult(0, "Verifies\n", "", False), "rejected"),
        (RunResult(0, "Verified using v2 scheme: true\n", "", False), "rejected"),
        (RunResult(0, "Verifies\nVerified using v2 scheme: true", "", True), "unavailable"),
    ):
        response = inspector.ArchiveInspector(
            store,
            OWNER,
            apk_verifier=tool,
            runner=lambda *args, value=result: value,
        ).inspect(handle)
        assert response["archive"]["signature"]["state"] == expected


def test_real_local_http_archive_tool_and_no_private_paths(tmp_path: Path) -> None:
    store = owner_store(tmp_path)
    handle = put(store, fixture("apk"))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    program = (
        "from pathlib import Path\n"
        "import sys\n"
        "from android_mcp_host.archive_inspector import ArchiveInspector\n"
        "from android_mcp_host.private_artifact_store import PrivateArtifactStore\n"
        "from android_mcp_host.server import create_server\n"
        "store=PrivateArtifactStore(Path(sys.argv[1]))\n"
        "create_server(archive_inspector=ArchiveInspector(store,sys.argv[2])).run("
        "transport='http',host='127.0.0.1',port=int(sys.argv[3]))\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", program, str(tmp_path / "private"), OWNER, str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:

        async def read() -> None:
            last: Exception | None = None
            for _ in range(50):
                try:
                    async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                        response = await client.call_tool(
                            "host_archive_inspect", {"handle": handle}
                        )
                        assert response.structured_content["archive"]["handle"] == handle
                        assert str(tmp_path) not in json.dumps(response.structured_content)
                        return
                except Exception as error:
                    last = error
                    await asyncio.sleep(0.1)
            raise AssertionError(f"Local HTTP fixture unavailable: {type(last).__name__}")

        asyncio.run(read())
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    assert process.poll() is not None


def test_binary_apk_manifest_requires_trusted_aapt2_metadata_tool(tmp_path: Path) -> None:
    store = owner_store(tmp_path)
    data = fixture("apk", **{"AndroidManifest.xml": b"\x03\x00binary-axml"})
    handle = put(store, data)
    assert inspector.ArchiveInspector(store, OWNER).inspect(handle)["archive"]["package_id"] is None
    tool = verifier(tmp_path, "aapt2")
    argv_seen: list[list[str]] = []

    def run(argv: Any, seconds: float, limit: int) -> RunResult:
        argv_seen.append(list(argv))
        assert seconds <= 5 and limit <= 65536
        return RunResult(
            0,
            "package: name='com.example.real' versionCode='82' versionName='4.0.5'\n"
            "uses-permission: name='android.permission.CAMERA'\n",
            "",
            False,
        )

    result = inspector.ArchiveInspector(
        store,
        OWNER,
        apk_metadata_tool=tool,
        runner=run,
    ).inspect(handle)
    assert result["archive"]["package_id"] == "com.example.real"
    assert result["archive"]["version_name"] == "4.0.5"
    assert result["archive"]["version_code"] == 82
    assert result["archive"]["permissions"] == ["android.permission.CAMERA"]
    assert "MANIFEST_UNAVAILABLE" not in [e["code"] for e in result["errors"]]
    assert argv_seen[0][1:3] == ["dump", "badging"]
    assert argv_seen[0][0] == str(tool)


def test_binary_aab_manifest_requires_trusted_bundletool_dump(tmp_path: Path) -> None:
    store = owner_store(tmp_path)
    handle = put(store, fixture("aab", **{"base/manifest/AndroidManifest.xml": b"proto\x00"}), AAB)
    tool = verifier(tmp_path, "bundletool")
    argv_seen: list[list[str]] = []

    def run(argv: Any, seconds: float, limit: int) -> RunResult:
        argv_seen.append(list(argv))
        return RunResult(0, MANIFEST.decode("utf-8"), "", False)

    result = inspector.ArchiveInspector(
        store,
        OWNER,
        aab_metadata_tool=tool,
        runner=run,
    ).inspect(handle)
    assert result["archive"]["package_id"] == "org.example.demo"
    assert result["archive"]["permissions"] == ["android.permission.INTERNET"]
    assert argv_seen[0][1:3] == ["dump", "manifest"]
    assert argv_seen[0][3].startswith("--bundle=")
    assert argv_seen[0][4] == "--module=base"


def test_invalid_vendor_metadata_never_fabricates_package(tmp_path: Path) -> None:
    store = owner_store(tmp_path)
    handle = put(store, fixture("apk", **{"AndroidManifest.xml": b"not-real-xml"}))
    tool = verifier(tmp_path, "aapt2")
    for result in (
        RunResult(1, "package: name='com.evil' versionCode='1' versionName='1'", "", False),
        RunResult(0, "package: name='com/evil' versionCode='1' versionName='1'", "", False),
        RunResult(0, "package: name='com.evil' versionCode='0' versionName='1'", "", False),
        RunResult(0, "package: name='com.evil' versionCode='1' versionName='bad value'", "", False),
        RunResult(0, "package: name='com.evil' versionCode='1' versionName='1'", "", True),
    ):
        inspected = inspector.ArchiveInspector(
            store,
            OWNER,
            apk_metadata_tool=tool,
            runner=lambda *args, value=result: value,
        ).inspect(handle)
        assert inspected["archive"]["package_id"] is None
        assert "MANIFEST_UNAVAILABLE" in [e["code"] for e in inspected["errors"]]


def test_vendor_text_parser_bounded_permissions_and_invalid_values() -> None:
    from android_mcp_host.archive_vendor_metadata import parse_aapt2_badging

    good = "package: name='org.example.demo' versionCode='41' versionName='2.0'\n"
    assert parse_aapt2_badging(good)["package_id"] == "org.example.demo"
    for text in (
        "",
        "x" * 70000,
        "not an aapt2 response",
        good + "uses-permission: name='a b'\n",
        good + "uses-permission: bad=unexpected\n",
        good + "".join(f"uses-permission: name='org.example.permission.P{i}'\n" for i in range(65)),
    ):
        assert parse_aapt2_badging(text) is None


def test_bundletool_text_parser_size_and_rejection() -> None:
    from android_mcp_host.archive_vendor_metadata import parse_bundletool_manifest

    assert parse_bundletool_manifest(MANIFEST.decode("utf-8"))["version_code"] == 12
    assert parse_bundletool_manifest("") is None
    assert parse_bundletool_manifest("Z" * 66000) is None
    assert parse_bundletool_manifest('<!DOCTYPE manifest SYSTEM "https://invalid/">') is None


def test_bad_metadata_tool_and_crashing_process_cannot_expose_private_data(
    tmp_path: Path,
) -> None:
    store = owner_store(tmp_path)
    handle = put(store, fixture("apk", **{"AndroidManifest.xml": b"\x00"}))
    target = verifier(tmp_path, "aapt2")
    for tool, runner in (
        (Path("aapt2"), lambda *args: RunResult(0, "", "", False)),
        (target, lambda *args: (_ for _ in ()).throw(OSError("PRIVATE USER SECRET"))),
        (
            target,
            lambda *args: (_ for _ in ()).throw(subprocess.TimeoutExpired(["aapt2"], 0.1)),
        ),
    ):
        response = inspector.ArchiveInspector(
            store, OWNER, apk_metadata_tool=tool, runner=runner
        ).inspect(handle)
        assert response["archive"]["package_id"] is None
        assert "MANIFEST_UNAVAILABLE" in [e["code"] for e in response["errors"]]
        assert "PRIVATE" not in json.dumps(response)
        assert str(tmp_path) not in json.dumps(response)


def test_host_cli_archive_opt_in_requires_operator_scoped_artifact_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from android_mcp_host import cli

    calls: list[dict[str, Any]] = []

    class Stub:
        def run(self, **kwargs: Any) -> None:
            assert kwargs == {"transport": "http", "host": "127.0.0.1", "port": 8765}

    def make(**kwargs: Any) -> Stub:
        calls.append(kwargs)
        return Stub()

    with monkeypatch.context() as scoped:
        scoped.setattr(cli, "create_server", make)
        scoped.setattr(cli.platform, "system", lambda: "Linux")
        for args in (
            ["serve", "--archive-inspect"],
            ["serve", "--apk-metadata-tool", "/trusted/aapt2"],
            ["serve", "--aab-verifier", "/trusted/jarsigner"],
            ["serve", "--artifact-metadata", "--archive-inspect"],
            ["serve", "--artifact-metadata", "--archive-inspect", "--artifact-root", "relative"],
        ):
            with pytest.raises(SystemExit) as error:
                cli.main(args)
            assert error.value.code == 2
            assert calls == []
        assert cli.main(["serve"]) == 0
        assert calls == [{}]
        calls.clear()
        assert (
            cli.main(
                [
                    "serve",
                    "--artifact-metadata",
                    "--archive-inspect",
                    "--artifact-root",
                    str(tmp_path / "private"),
                    "--artifact-owner",
                    OWNER,
                    "--apk-metadata-tool",
                    str(tmp_path / "pinned-aapt2"),
                ]
            )
            == 0
        )
    assert len(calls) == 1
    assert isinstance(calls[0]["archive_inspector"], inspector.ArchiveInspector)
    assert calls[0]["artifact_owner"] == OWNER
    assert calls[0]["archive_inspector"].inspect("art_" + "x" * 32)["status"] == "not_found"
