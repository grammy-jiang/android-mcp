"""H2.e: fixed-scope offline APK/AAB inspection. Never sign, install or run Gradle."""

from __future__ import annotations

import asyncio
import io
import json
import stat
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator

from android_mcp_host.archive_validation import ArchiveValidationError, inspect_zip
from android_mcp_host.command_runner import RunResult
from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.server import create_server

OWNER = "host-owner"
APK = "application/vnd.android.package-archive"
AAB = "application/vnd.android.aab"
MANIFEST = (
    b'<manifest xmlns:android="http://schemas.android.com/apk/res/android" '
    b'package="org.example.demo" android:versionName="1.2.3" '
    b'android:versionCode="12">'
    b'<uses-permission android:name="android.permission.INTERNET" /></manifest>'
)


def fixture(fmt: str, **entries: bytes) -> bytes:
    path = "AndroidManifest.xml" if fmt == "apk" else "base/manifest/AndroidManifest.xml"
    source = {path: MANIFEST, **entries}
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, value in source.items():
            zf.writestr(name, value)
    return stream.getvalue()


def owner_store(tmp_path: Path) -> PrivateArtifactStore:
    return PrivateArtifactStore(tmp_path / "private", max_artifact_bytes=16 * 1024 * 1024)


def put(store: PrivateArtifactStore, content: bytes, kind: str = APK) -> str:
    return str(store.put(OWNER, content, mime_type=kind)["handle"])


def verifier(tmp_path: Path, name: str = "apksigner") -> Path:
    executable = tmp_path / name
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o700)
    return executable


def test_t_h2e_01_synthetic_apk_aab_fields_hash_resource_and_verified_tool(
    tmp_path: Path,
) -> None:
    from android_mcp_host.archive_inspector import ArchiveInspector

    store = owner_store(tmp_path)
    apk_data = fixture("apk", **{"lib/arm64-v8a/libdemo.so": b"elf", "resources.arsc": b"res"})
    aab_data = fixture("aab", **{"base/lib/x86_64/libdemo.so": b"elf", "base/resources.pb": b"res"})
    apk = put(store, apk_data)
    aab = put(store, aab_data, AAB)
    calls: list[list[str]] = []

    def run(argv: Any, seconds: float, limit: int) -> RunResult:
        assert seconds <= 5 and limit <= 8192
        calls.append(list(argv))
        output = (
            "Verifies\nVerified using v2 scheme (APK Signature Scheme v2): true\n"
            if "apksigner" in argv[0]
            else "jar verified.\n"
        )
        return RunResult(0, output, "", False)

    engine = ArchiveInspector(
        store=store,
        owner=OWNER,
        apk_verifier=verifier(tmp_path),
        aab_verifier=verifier(tmp_path, "jarsigner"),
        runner=run,
    )
    for handle, expected, abi in ((apk, APK, "arm64-v8a"), (aab, AAB, "x86_64")):
        result = engine.inspect(handle)
        assert result["status"] == "ok"
        archive = result["archive"]
        assert archive["handle"] == handle
        assert archive["mime_type"] == expected
        assert archive["package_id"] == "org.example.demo"
        assert archive["version_name"] == "1.2.3" and archive["version_code"] == 12
        assert archive["permissions"] == ["android.permission.INTERNET"]
        assert archive["abis"] == [abi]
        assert archive["resources_present"] is True
        assert archive["signature"]["state"] == "verified"
        assert archive["sha256"] == store.public_metadata(OWNER, handle)["artifact"]["sha256"]
        assert result["errors"] == []
        assert OWNER not in json.dumps(result) and str(tmp_path) not in json.dumps(result)
    assert len(calls) == 2
    assert all(len(argv) <= 5 for argv in calls)
    assert all(str(tmp_path / "private") not in json.dumps(argv) for argv in calls)


def test_t_h2e_02_unsigned_malformed_and_fake_signature_never_become_verified(
    tmp_path: Path,
) -> None:
    from android_mcp_host.archive_inspector import ArchiveInspector

    store = owner_store(tmp_path)
    unsigned = fixture("apk", **{"META-INF/FAKE.RSA": b"fake signature"})
    handle = put(store, unsigned)
    unavailable = ArchiveInspector(store, OWNER).inspect(handle)
    assert unavailable["status"] == "partial"
    assert unavailable["archive"]["signature"]["state"] == "unavailable"

    fake = ArchiveInspector(
        store,
        OWNER,
        apk_verifier=verifier(tmp_path),
        runner=lambda *args: RunResult(0, "Verified using v2 scheme: false\n", "", False),
    ).inspect(handle)
    assert fake["status"] == "partial"
    assert fake["archive"]["signature"]["state"] == "rejected"

    failed = ArchiveInspector(
        store,
        OWNER,
        apk_verifier=verifier(tmp_path),
        runner=lambda *args: RunResult(1, "Verifies\nVerified using v2 scheme: true", "", False),
    ).inspect(handle)
    assert failed["archive"]["signature"]["state"] == "rejected"
    assert ArchiveInspector(store, "wrong-owner").inspect(handle)["status"] == "not_found"
    assert ArchiveInspector(store, OWNER).inspect("art_" + "z" * 32)["status"] == "not_found"
    assert ArchiveInspector(store, OWNER).inspect("../secret")["status"] == "not_found"


def test_t_h2e_03_archive_member_path_link_duplicate_and_zip_bomb_are_refused() -> None:
    def bad(entries: list[tuple[str, bytes, int]]) -> bytes:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as output:
            for name, content, mode in entries:
                entry = zipfile.ZipInfo(name)
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = mode << 16
                output.writestr(entry, content)
        return stream.getvalue()

    for name in (
        "../secret",
        "/private/root",
        "dir//wrong",
        "dir/./wrong",
        "dir/../wrong",
        "C:/private",
        "foo\\bar",
    ):
        with pytest.raises(ArchiveValidationError) as err:
            inspect_zip(bad([(name, b"x", 0)]), APK)
        assert err.value.code == "UNTRUSTED_ARCHIVE_PATH"
    symlink = bad([("base/manifest/AndroidManifest.xml", MANIFEST, stat.S_IFLNK | 0o777)])
    with pytest.raises(ArchiveValidationError, match="UNTRUSTED_ARCHIVE_PATH"):
        inspect_zip(symlink, AAB)
    with pytest.raises(ArchiveValidationError, match="DUPLICATE_ARCHIVE_PATH"):
        inspect_zip(bad([("Abc", b"x", 0), ("abc", b"x", 0)]), APK)
    with pytest.raises(ArchiveValidationError, match="RESOURCE_LIMIT"):
        inspect_zip(fixture("apk", **{"assets/bomb": b"A" * (17 * 1024 * 1024)}), APK)


def test_t_h2e_04_missing_wrong_or_symlinked_verifier_is_unavailable(
    tmp_path: Path,
) -> None:
    from android_mcp_host.archive_inspector import ArchiveInspector

    store = owner_store(tmp_path)
    handle = put(store, fixture("apk"))
    for path in (None, tmp_path / "absent", Path("relative-apksigner")):
        result = ArchiveInspector(store, OWNER, apk_verifier=path).inspect(handle)
        assert result["status"] == "partial"
        assert result["archive"]["signature"]["state"] == "unavailable"
    target = verifier(tmp_path)
    link = tmp_path / "link-verifier"
    link.symlink_to(target)
    assert (
        ArchiveInspector(store, OWNER, apk_verifier=link).inspect(handle)["archive"]["signature"][
            "state"
        ]
        == "unavailable"
    )
    assert not (tmp_path / "absent").exists()


def test_t_h2e_05_timeout_bad_manifest_and_truncated_subprocess_are_safe(
    tmp_path: Path,
) -> None:
    from android_mcp_host.archive_inspector import ArchiveInspector

    store = owner_store(tmp_path)
    huge = put(store, fixture("apk", **{"assets/big.xml": b"V" * 100_000}))
    assert ArchiveInspector(store, OWNER).inspect(huge)["status"] == "invalid"
    bad = fixture(
        "apk", **{"AndroidManifest.xml": MANIFEST.replace(b"org.example.demo", b"org/evil/sample")}
    )
    handle = put(store, bad)
    result = ArchiveInspector(store, OWNER).inspect(handle)
    assert result["archive"]["package_id"] is None
    assert "MANIFEST_UNAVAILABLE" in [item["code"] for item in result["errors"]]

    truncated = ArchiveInspector(
        store,
        OWNER,
        apk_verifier=verifier(tmp_path),
        runner=lambda *args: RunResult(0, "Verifies\nVerified using v2 scheme: true", "", True),
    ).inspect(handle)
    assert truncated["archive"]["signature"]["state"] != "verified"

    sleeper = tmp_path / "slow-verifier"
    sleeper.write_text("#!/bin/sh\nsleep 2\n", encoding="utf-8")
    sleeper.chmod(0o700)
    timed = ArchiveInspector(store, OWNER, apk_verifier=sleeper, timeout_s=0.1).inspect(handle)
    assert timed["archive"]["signature"]["state"] == "unavailable"
    assert "VERIFY_TIMEOUT" in [e["code"] for e in timed["errors"]]
    assert list(tmp_path.glob("android-mcp-*")) == []


def test_t_h2e_06_real_fastmcp_wire_schema_and_default_tools_private(
    tmp_path: Path,
) -> None:
    from android_mcp_host.archive_inspector import ArchiveInspector, get_archive_output_schema

    store = owner_store(tmp_path)
    handle = put(store, fixture("aab"), AAB)
    engine = ArchiveInspector(store, OWNER)

    async def verify() -> None:
        async with Client(create_server()) as plain:
            baseline = {tool.name: tool for tool in await plain.list_tools()}
        assert set(baseline) == {"device_status", "adb_observe", "adb_develop"}
        async with Client(create_server(archive_inspector=engine)) as client:
            catalog = {tool.name: tool for tool in await client.list_tools()}
            assert set(catalog) == {*baseline, "host_archive_inspect"}
            for name in baseline:
                assert catalog[name] == baseline[name]
            tool = catalog["host_archive_inspect"]
            assert tool.output_schema == get_archive_output_schema()
            Draft202012Validator.check_schema(tool.output_schema)
            assert tool.annotations is not None and tool.annotations.read_only_hint is True
            assert set(tool.input_schema["required"]) == {"handle"}
            reply = await client.call_tool("host_archive_inspect", {"handle": handle})
            assert not reply.is_error
            payload = reply.structured_content
            assert isinstance(payload, dict)
            Draft202012Validator(tool.output_schema).validate(payload)
            assert payload["status"] == "partial" and payload["archive"]["package_id"]
            assert payload["archive"]["signature"]["state"] == "unavailable"
            assert OWNER not in json.dumps(payload) and str(tmp_path) not in json.dumps(payload)
            missing = await client.call_tool("host_archive_inspect", {"handle": "art_" + "x" * 32})
            assert missing.structured_content["status"] == "not_found"

    asyncio.run(verify())
