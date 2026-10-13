"""H2.c six required artifact lifecycle tests. All payloads are synthetic."""

from __future__ import annotations

import asyncio
import hashlib
import json
import socket
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator

from android_mcp_host import cli
from android_mcp_host.server import create_server

OWNER = "host-fixture-owner"
OTHER = "another-host-owner"
MIME = "application/octet-stream"


def _store(tmp_path: Path, **kwargs: Any) -> Any:
    from android_mcp_host.private_artifact_store import PrivateArtifactStore

    return PrivateArtifactStore(tmp_path / "private-artifacts", **kwargs)


def _error(action: Any, code: str) -> None:
    from android_mcp_host.private_artifact_store import ArtifactStoreError

    with pytest.raises(ArtifactStoreError) as caught:
        action()
    assert caught.value.code == code
    assert "SECRET" not in str(caught.value)


def test_t_h2c_01_private_staging_returns_opaque_handle_mime_digest_and_size(
    tmp_path: Path,
) -> None:
    data = b"generated synthetic private fixture"
    store = _store(tmp_path)
    result = store.put(OWNER, data, mime_type=MIME, filename="fixture.bin")
    assert result["sha256"] == hashlib.sha256(data).hexdigest()
    assert result["mime_type"] == MIME and result["size_bytes"] == len(data)
    assert result["handle"].startswith("art_")
    assert len(result["handle"]) >= 30
    assert OWNER not in result["handle"] and result["sha256"] not in result["handle"]
    assert str(tmp_path) not in json.dumps(result)
    assert store.read(OWNER, result["handle"]) == data
    assert stat.S_IMODE((tmp_path / "private-artifacts").stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "private-artifacts" / "objects").stat().st_mode) == 0o700
    assert not list((tmp_path / "private-artifacts" / "objects").glob("tmp-*"))
    metadata = store.public_metadata(OWNER, result["handle"])
    assert metadata["status"] == "ok"
    assert metadata["artifact"] == result
    assert "path" not in metadata["artifact"]


def test_t_h2c_02_unknown_expired_cross_owner_and_revoked_handle_denied(
    tmp_path: Path,
) -> None:
    clock = [1000.0]
    store = _store(tmp_path, clock=lambda: clock[0])
    record = store.put(OWNER, b"synthetic content", mime_type=MIME, ttl_s=20)
    token = record["handle"]
    for owner, handle in ((OTHER, token), (OWNER, "art_" + "a" * 32), ("../../other", token)):
        denied = store.public_metadata(owner, handle)
        assert denied["status"] == "not_found" and denied["artifact"] is None
        assert denied["errors"][0]["code"] == "NOT_FOUND"
        assert str(tmp_path) not in json.dumps(denied)
    _error(lambda: store.read(OTHER, token), "NOT_FOUND")
    assert store.revoke(OTHER, token) is False
    assert store.revoke(OWNER, token) is True
    _error(lambda: store.read(OWNER, token), "NOT_FOUND")
    assert store.revoke(OWNER, token) is False
    fresh = store.put(OWNER, b"fresh", mime_type=MIME, ttl_s=10)
    clock[0] += 11.0
    assert store.public_metadata(OWNER, fresh["handle"])["status"] == "not_found"
    _error(lambda: store.read(OWNER, fresh["handle"]), "NOT_FOUND")


def test_t_h2c_03_untrusted_filename_symlink_mime_and_oversize_denied(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path, max_artifact_bytes=128)
    for filename in ("../secret.png", "/tmp/secret.png", "a/b.jpg", "..", ".hidden"):
        _error(
            lambda filename=filename: store.put(OWNER, b"data", mime_type=MIME, filename=filename),
            "INVALID_FILENAME",
        )
    _error(lambda: store.put(OWNER, b"x" * 129, mime_type=MIME), "ARTIFACT_TOO_LARGE")
    _error(
        lambda: store.put(OWNER, b"definitely not a PNG", mime_type="image/png"),
        "MIME_MISMATCH",
    )
    _error(
        lambda: store.put(OWNER, b"data", mime_type="application/unknown"),
        "UNSUPPORTED_MIME",
    )
    _error(
        lambda: store.put(OWNER, b"SECRET_PAYLOAD", mime_type="text/plain\n"),
        "UNSUPPORTED_MIME",
    )
    payload = store.put(OWNER, b"do not leak", mime_type=MIME)
    objects = list((tmp_path / "private-artifacts" / "objects").iterdir())
    assert len(objects) == 1
    objects[0].unlink()
    outside = tmp_path / "outside-sensitive"
    outside.write_text("SECRET_IN_OUTSIDE", encoding="utf-8")
    objects[0].symlink_to(outside)
    _error(lambda: store.read(OWNER, payload["handle"]), "INTEGRITY_FAIL")
    assert outside.read_text() == "SECRET_IN_OUTSIDE"


def test_t_h2c_04_dedup_concurrent_content_is_atomic_and_crash_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "private-artifacts"
    store = _store(tmp_path)
    payload = b"A" * 8192

    def write(_: int) -> dict[str, Any]:
        return store.put(OWNER, payload, mime_type=MIME)

    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(write, range(16)))
    assert len({record["handle"] for record in records}) == 16
    assert len({record["sha256"] for record in records}) == 1
    assert len(list((root / "objects").iterdir())) == 1
    assert all(store.read(OWNER, record["handle"]) == payload for record in records)
    assert len(store.list_metadata(OWNER)) == 16

    from android_mcp_host.private_artifact_store import PrivateArtifactStore

    original = PrivateArtifactStore._write_object

    def interrupted(self: Any, key: str, data: bytes, digest: str) -> None:
        raise OSError("synthetic process interrupted during private write")

    with monkeypatch.context() as scope:
        scope.setattr(PrivateArtifactStore, "_write_object", interrupted)
        _error(
            lambda: store.put(OWNER, b"new private payload", mime_type=MIME),
            "STORAGE_FAILURE",
        )
    restarted = _store(tmp_path)
    assert len(restarted.list_metadata(OWNER)) == 16
    assert len(list((root / "objects").iterdir())) == 1
    assert all(restarted.read(OWNER, record["handle"]) == payload for record in records)
    assert original is PrivateArtifactStore._write_object


def test_t_h2c_05_restart_ttl_revoke_and_disk_cleanup_are_bounded(
    tmp_path: Path,
) -> None:
    clock = [500.0]
    root = tmp_path / "private-artifacts"
    store = _store(
        tmp_path,
        clock=lambda: clock[0],
        max_total_bytes=75,
        max_artifact_bytes=50,
        max_records=4,
    )
    first = store.put(OWNER, b"a" * 45, mime_type=MIME, ttl_s=10)
    second = store.put(OWNER, b"b" * 25, mime_type=MIME, ttl_s=30)
    _error(
        lambda: store.put(OWNER, b"c" * 15, mime_type=MIME, ttl_s=30),
        "QUOTA_EXCEEDED",
    )
    assert len(store.list_metadata(OWNER)) == 2
    reopened = _store(
        tmp_path,
        clock=lambda: clock[0],
        max_total_bytes=75,
        max_artifact_bytes=50,
        max_records=4,
    )
    assert reopened.read(OWNER, first["handle"]) == b"a" * 45
    assert reopened.read(OWNER, second["handle"]) == b"b" * 25
    clock[0] += 15
    report = reopened.cleanup()
    assert report["removed_records"] >= 1
    assert len(reopened.list_metadata(OWNER)) == 1
    assert reopened.public_metadata(OWNER, first["handle"])["status"] == "not_found"
    third = reopened.put(OWNER, b"c" * 45, mime_type=MIME)
    assert third["size_bytes"] == 45
    assert reopened.revoke(OWNER, second["handle"]) is True
    report = reopened.cleanup()
    assert report["remaining_records"] == 1
    assert len(list((root / "objects").iterdir())) == 1
    assert reopened.read(OWNER, third["handle"]) == b"c" * 45


def test_t_h2c_06_public_fastmcp_metadata_has_no_raw_bytes_or_paths(
    tmp_path: Path,
) -> None:
    from android_mcp_host.private_artifact_store import get_artifact_metadata_schema

    store = _store(tmp_path)
    private = b"SECRET_SYNTHETIC_CONTENT" * 50
    record = store.put(OWNER, private, mime_type=MIME)

    async def check() -> None:
        async with Client(create_server()) as baseline:
            old = {tool.name: tool for tool in await baseline.list_tools()}
        assert set(old) == {"device_status", "adb_observe", "adb_develop"}
        async with Client(create_server(artifact_store=store, artifact_owner=OWNER)) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert set(tools) == {*old, "host_artifact_metadata"}
            for name, original in old.items():
                current = tools[name]
                assert (
                    original.title,
                    original.description,
                    original.input_schema,
                    original.output_schema,
                    original.annotations,
                ) == (
                    current.title,
                    current.description,
                    current.input_schema,
                    current.output_schema,
                    current.annotations,
                )
            tool = tools["host_artifact_metadata"]
            assert tool.output_schema == get_artifact_metadata_schema()
            Draft202012Validator.check_schema(tool.input_schema)
            Draft202012Validator.check_schema(tool.output_schema)
            assert set(tool.input_schema["required"]) == {"handle"}
            assert tool.annotations is not None
            hints = tool.annotations.model_dump(mode="json", by_alias=True)
            assert hints["readOnlyHint"] is True
            assert hints["destructiveHint"] is False
            assert hints["openWorldHint"] is False
            response = await client.call_tool(
                "host_artifact_metadata", {"handle": record["handle"]}
            )
            assert not response.is_error and isinstance(response.structured_content, dict)
            Draft202012Validator(tool.output_schema).validate(response.structured_content)
            wire = json.dumps(response.structured_content)
            assert "SECRET_SYNTHETIC_CONTENT" not in wire
            assert str(tmp_path) not in wire
            assert OWNER not in wire
            assert response.structured_content["artifact"]["sha256"] == record["sha256"]
            unknown = await client.call_tool(
                "host_artifact_metadata", {"handle": "art_" + "a" * 32}
            )
            assert unknown.structured_content["status"] == "not_found"

    asyncio.run(check())


def test_artifact_cli_is_disabled_until_owner_and_root_are_operator_supplied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        for argv in (
            ["serve", "--artifact-metadata"],
            ["serve", "--artifact-owner", OWNER],
            ["serve", "--artifact-root", str(tmp_path / "private-storage")],
            ["serve", "--artifact-metadata", "--artifact-root", str(tmp_path / "private-storage")],
            [
                "serve",
                "--artifact-metadata",
                "--artifact-root",
                "relative/path",
                "--artifact-owner",
                OWNER,
            ],
            [
                "serve",
                "--artifact-metadata",
                "--artifact-root",
                str(tmp_path / "private-storage"),
                "--artifact-owner",
                "../other",
            ],
        ):
            with pytest.raises(SystemExit) as denied:
                cli.main(argv)
            assert denied.value.code == 2
        assert calls == []
        assert not (tmp_path / "private-storage").exists()
        accepted = [
            "serve",
            "--artifact-metadata",
            "--artifact-root",
            str(tmp_path / "private-storage"),
            "--artifact-owner",
            OWNER,
        ]
        assert cli.main(accepted) == 0
    assert len(calls) == 1
    assert calls[0]["artifact_owner"] == OWNER
    assert calls[0]["artifact_store"].list_metadata(OWNER) == []
    assert (tmp_path / "private-storage").stat().st_mode & 0o777 == 0o700


def test_artifact_metadata_through_actual_localhost_fastmcp(
    tmp_path: Path,
) -> None:
    service = _store(tmp_path)
    data = b"SECRET_FAKE_IMAGE_PRIVATE_BYTES"
    record = service.put(OWNER, data, mime_type=MIME)
    root = tmp_path / "private-artifacts"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from android_mcp_host.private_artifact_store import PrivateArtifactStore\n"
        "from android_mcp_host.server import create_server\n"
        "create_server(artifact_store=PrivateArtifactStore(Path(sys.argv[1])),"
        "artifact_owner=sys.argv[2]).run("
        "transport='http',host='127.0.0.1',port=int(sys.argv[3]))\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(root), OWNER, str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def verify() -> None:
        last: Exception | None = None
        for _ in range(45):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    tools = {tool.name: tool for tool in await client.list_tools()}
                    assert "host_artifact_metadata" in tools
                    tool = tools["host_artifact_metadata"]
                    response = await client.call_tool(
                        "host_artifact_metadata", {"handle": record["handle"]}
                    )
                    assert not response.is_error
                    assert isinstance(response.structured_content, dict)
                    Draft202012Validator(tool.output_schema).validate(response.structured_content)
                    assert response.structured_content["status"] == "ok"
                    assert response.structured_content["artifact"]["sha256"] == record["sha256"]
                    wire = json.dumps(response.structured_content)
                    assert data.decode() not in wire
                    assert str(root) not in wire
                    assert OWNER not in wire
                    return
            except Exception as error:
                last = error
                await asyncio.sleep(0.1)
        raise AssertionError(f"Private artifact localhost MCP failed: {last!r}")

    try:
        asyncio.run(verify())
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    assert process.poll() is not None
