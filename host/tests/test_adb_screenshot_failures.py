"""Additional adversarial H4.a contract tests; no real ADB or physical media."""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path
from typing import Any

import pytest
from test_adb_screenshot_artifacts import (
    ART_OWNER,
    builder,
    capture,
    png_fixture,
)
from test_avd_provisioning import NAME, OWNER

from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.private_artifact_support import ArtifactStoreError
from android_mcp_host.synthetic_screenshot import CaptureApproval, CaptureFrame, validate_png


def chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def fixture(chunks: list[tuple[bytes, bytes]]) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunk(kind, content) for kind, content in chunks)


def parts() -> tuple[bytes, bytes, bytes]:
    raw = png_fixture()
    return raw[16:29], raw[41:-16], b""


@pytest.mark.parametrize(
    "kind",
    [
        "empty",
        "not-bytes",
        "too-large",
        "signature",
        "truncated",
        "oversize-chunk",
        "bad-crc",
        "bad-header-len",
        "zero-width",
        "excess-width",
        "interlace",
        "color",
        "idat-before-ihdr",
        "no-idat",
        "empty-idat",
        "no-iend",
        "bad-iend",
        "trailing",
        "duplicate-ihdr",
        "extra-chunk",
        "corrupt-zlib",
        "truncated-zlib",
        "short-decoded",
        "extra-decoded",
        "bad-filter",
        "garbage-after-zlib",
    ],
)
def test_strict_png_parser_rejects_untrusted_boundaries(kind: str) -> None:
    hdr, data, _ = parts()
    ihdr = (b"IHDR", hdr)
    idat = (b"IDAT", data)
    end = (b"IEND", b"")
    if kind == "empty":
        value: Any = b""
    elif kind == "not-bytes":
        value = "not a PNG"
    elif kind == "too-large":
        value = b"x" * (4 * 1024 * 1024 + 1)
    elif kind == "signature":
        value = b"notpng!!" + png_fixture()[8:]
    elif kind == "truncated":
        value = png_fixture()[:-2]
    elif kind == "oversize-chunk":
        value = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 5_000_000) + b"IHDR" + b"stuff"
    elif kind == "bad-crc":
        value = bytearray(png_fixture())
        value[29] ^= 0x01
        value = bytes(value)
    elif kind == "bad-header-len":
        value = fixture([(b"IHDR", hdr[:-1]), idat, end])
    elif kind == "zero-width":
        value = fixture([(b"IHDR", struct.pack(">I", 0) + hdr[4:]), idat, end])
    elif kind == "excess-width":
        value = fixture([(b"IHDR", struct.pack(">I", 2049) + hdr[4:]), idat, end])
    elif kind == "interlace":
        value = fixture([(b"IHDR", hdr[:-1] + b"\x01"), idat, end])
    elif kind == "color":
        value = fixture([(b"IHDR", hdr[:9] + b"\x03" + hdr[10:]), idat, end])
    elif kind == "idat-before-ihdr":
        value = fixture([idat, ihdr, end])
    elif kind == "no-idat":
        value = fixture([ihdr, end])
    elif kind == "empty-idat":
        value = fixture([ihdr, (b"IDAT", b""), end])
    elif kind == "no-iend":
        value = fixture([ihdr, idat])
    elif kind == "bad-iend":
        value = fixture([ihdr, idat, (b"IEND", b"x")])
    elif kind == "trailing":
        value = fixture([ihdr, idat, end, (b"IEND", b"")])
    elif kind == "duplicate-ihdr":
        value = fixture([ihdr, ihdr, idat, end])
    elif kind == "extra-chunk":
        value = fixture([ihdr, (b"tEXt", b"oops"), idat, end])
    elif kind == "corrupt-zlib":
        value = fixture([ihdr, (b"IDAT", b"not-deflate"), end])
    elif kind == "truncated-zlib":
        value = fixture([ihdr, (b"IDAT", data[:-1]), end])
    elif kind == "short-decoded":
        value = fixture([ihdr, (b"IDAT", zlib.compress(b"\x00")), end])
    elif kind == "extra-decoded":
        value = fixture([ihdr, (b"IDAT", zlib.compress(b"\x00" * 500)), end])
    elif kind == "bad-filter":
        payload = b"\x05" + b"\xff" * 8 + b"\x00" + b"\xff" * 8
        value = fixture([ihdr, (b"IDAT", zlib.compress(payload)), end])
    else:
        value = fixture([ihdr, (b"IDAT", data + b"extra"), end])
    with pytest.raises(ValueError):
        validate_png(value)


def test_png_split_data_and_all_filter_values_supported() -> None:
    hdr, _, _ = parts()
    rows = b"\x03" + b"\xff" * 8 + b"\x04" + b"\xaa" * 8
    packed = zlib.compress(rows)
    sample = fixture([(b"IHDR", hdr), (b"IDAT", packed[:4]), (b"IDAT", packed[4:]), (b"IEND", b"")])
    assert validate_png(sample) == (2, 2)


def test_capture_duplicate_is_durable_and_expired_private_image_not_retried(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    worker, live, jobs, artifacts, handle, lid = builder(
        tmp_path,
        backend=lambda name, handle, lid, timeout: (
            calls.append("capture")
            or CaptureFrame(png_fixture(), name, handle, lid, False, False, True)
        ),
    )
    now = [500.0]
    artifacts._clock = lambda: now[0]
    try:
        first = capture(worker, handle, lid)
        assert first["status"] == "ok"
        assert len(artifacts.list_metadata(ART_OWNER)) == 2
        again = capture(worker, handle, lid)
        assert again == first
        assert calls == ["capture"]
        different = capture(worker, handle, lid, request="another-request")
        assert different["status"] == "blocked"
        assert different["errors"][0]["code"] == "RECOVERY_REQUIRED"
        now[0] += 121.0
        assert (
            artifacts.public_metadata(ART_OWNER, first["artifact_handle"])["status"] == "not_found"
        )
        expired = capture(worker, handle, lid)
        assert expired["status"] == "uncertain"
        assert expired["errors"][0]["code"] == "ARTIFACT_EXPIRED"
        assert calls == ["capture"]
        artifacts.cleanup()
        assert artifacts.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, first["job_id"])["job"]["state"] == "succeeded"
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "mutate",
    [
        {"owner": "foreign"},
        {"avd_handle": "mcpavd_" + "x" * 32},
        {"lifecycle_job_id": "job_" + "z" * 32},
        {"purpose": "wrong-purpose"},
        {"ttl_s": 0},
        {"ttl_s": float("inf")},
        {"ttl_s": 301},
        {"ttl_s": "bad-value"},
    ],
)
def test_grant_mismatch_denied_before_any_backend_call(
    tmp_path: Path, mutate: dict[str, Any]
) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    fields = {
        "owner": OWNER,
        "avd_handle": handle,
        "lifecycle_job_id": lid,
        "purpose": "synthetic-debug-screenshot",
        "ttl_s": 120,
    }
    fields.update(mutate)
    worker._approval = CaptureApproval(**fields)
    worker._fixture = lambda *args: pytest.fail("Unauthorized media backend invoked")
    try:
        response = capture(worker, handle, lid)
        assert response["status"] == "blocked"
        assert response["errors"][0]["code"] == "CONSENT_REQUIRED"
        assert artifacts.list_metadata(ART_OWNER) == []
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


def test_tool_input_target_and_absent_execution_all_fail_closed(tmp_path: Path) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    try:
        checks = (
            worker.submit("delete", NAME, handle, lid),
            worker.submit("plan", NAME, handle, "bad"),
            worker.submit("capture", NAME, handle, lid, request_id="\nrm -rf"),
            worker.submit("capture", NAME, handle, lid, request_id=None),
            worker.submit("plan", "-avd", handle, lid),
            worker.submit("plan", NAME, "physical-serial", lid),
        )
        assert all(item["status"] == "blocked" for item in checks)
        assert checks[0]["errors"][0]["code"] == "INVALID_ACTION"
        assert checks[1]["errors"][0]["code"] == "INVALID_INPUT"
        assert checks[-1]["errors"][0]["code"] == "NOT_OWNED"
        worker._fixture = None
        disabled = capture(worker, handle, lid)
        assert disabled["errors"][0]["code"] == "EXECUTION_DISABLED"
        assert jobs.list_status(OWNER)[0]["job_id"] == lid
        assert artifacts.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "spoof",
    ["name", "handle", "lifecycle", "synthetic", "securetype", "locktype", "type"],
)
def test_returned_capture_identity_or_security_type_spoof_cannot_commit(
    tmp_path: Path, spoof: str
) -> None:
    def fake(name: str, handle: str, lid: str, timeout: float) -> Any:
        if spoof == "type":
            return {"payload": png_fixture(), "secure_window": False}
        return CaptureFrame(
            png_fixture(),
            "foreign" if spoof == "name" else name,
            "mcpavd_" + "x" * 32 if spoof == "handle" else handle,
            "job_" + "y" * 32 if spoof == "lifecycle" else lid,
            "false" if spoof == "securetype" else False,  # type: ignore[arg-type]
            "false" if spoof == "locktype" else False,  # type: ignore[arg-type]
            spoof != "synthetic",
        )

    worker, live, jobs, artifacts, handle, lid = builder(tmp_path, backend=fake)
    try:
        first = capture(worker, handle, lid)
        assert first["status"] == "failed"
        assert first["artifact_handle"] is None
        assert jobs.status(OWNER, first["job_id"])["job"]["state"] == "failed"
        assert capture(worker, handle, lid)["status"] == "failed"
        assert artifacts.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


def test_controller_and_owner_mismatch_constructor_denied(tmp_path: Path) -> None:
    from android_mcp_host.synthetic_screenshot import ScreenshotArtifacts

    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    try:
        with pytest.raises(ValueError):
            ScreenshotArtifacts(
                live.provisioner, live, jobs, artifacts, owner="foreign", artifact_owner=ART_OWNER
            )
        with pytest.raises(ValueError):
            ScreenshotArtifacts(
                live.provisioner, live, jobs, artifacts, owner=OWNER, artifact_owner="bad/owner"
            )
    finally:
        live.shutdown()


def test_capture_storage_failure_cleans_private_objects_and_marks_uncertain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    put = artifacts.put
    calls = [0]

    def partial(owner: str, data: bytes, **kwargs: Any) -> dict[str, Any]:
        calls[0] += 1
        if calls[0] == 2:
            raise ArtifactStoreError("QUOTA_EXCEEDED")
        return put(owner, data, **kwargs)

    monkeypatch.setattr(artifacts, "put", partial)
    try:
        result = capture(worker, handle, lid)
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "CAPTURE_FAILED"
        assert calls == [2]
        assert artifacts.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"
        assert capture(worker, handle, lid)["status"] == "uncertain"
    finally:
        live.shutdown()


def test_lifecycle_disappearing_mid_capture_is_uncertain_not_success(tmp_path: Path) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)

    def cut(name: str, handle: str, lid: str, timeout: float) -> CaptureFrame:
        live.shutdown()
        return CaptureFrame(png_fixture(), name, handle, lid, False, False, True)

    worker._fixture = cut
    result = capture(worker, handle, lid)
    assert result["status"] == "uncertain"
    assert result["errors"][0]["code"] == "UNVERIFIED_TARGET"
    assert artifacts.list_metadata(ART_OWNER) == []
    assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"


def test_fixture_io_error_and_idempotency_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    worker._fixture = lambda *args: (_ for _ in ()).throw(OSError("secret-private-path"))
    try:
        first = capture(worker, handle, lid)
        assert first["status"] == "uncertain"
        assert "secret-private-path" not in json.dumps(first)
        monkeypatch.setattr(
            worker, "_digest", lambda info, lid: hashlib.sha256(b"changed").hexdigest()
        )
        conflict = capture(worker, handle, lid)
        assert conflict["status"] == "blocked"
        assert conflict["errors"][0]["code"] == "IDEMPOTENCY_CONFLICT"
    finally:
        live.shutdown()


def test_job_error_and_busy_fixture_lock_are_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import android_mcp_host.synthetic_screenshot as module

    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(module, "claim_fixture_lock", lambda root, target: None)
            blocked = capture(worker, handle, lid)
            assert blocked["errors"][0]["code"] == "RECOVERY_REQUIRED"
        with monkeypatch.context() as patch:

            def unavailable(root: Any, target: Any) -> Any:
                raise OSError("private folder name")

            patch.setattr(module, "claim_fixture_lock", unavailable)
            blocked = capture(worker, handle, lid)
            assert blocked["errors"][0]["code"] == "JOB_UNAVAILABLE"
        with monkeypatch.context() as patch:

            def invalid(*args: Any, **kwargs: Any) -> Any:
                raise JobStoreError("STORAGE_FAILURE")

            patch.setattr(jobs, "lookup_request", invalid)
            blocked = capture(worker, handle, lid)
            assert blocked["errors"][0]["code"] == "JOB_UNAVAILABLE"
        assert artifacts.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


def test_prior_completed_unrelated_debug_job_does_not_block_capture(tmp_path: Path) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    try:
        other = jobs.prepare(
            OWNER,
            "previous-debug-job",
            hashlib.sha256(b"unrelated synthetic debug").hexdigest(),
            identity=handle,
            authorized=True,
        )
        jobs.queue(OWNER, other["job_id"], identity=handle, authorized=True)
        running = jobs.claim(
            OWNER, other["job_id"], "unrelated-debug-worker", handle, authorized=True
        )
        jobs.complete(
            OWNER,
            other["job_id"],
            "unrelated-debug-worker",
            running["generation"],
            handle,
            result_digest=hashlib.sha256(b"synthetic receipt").hexdigest(),
            authorized=True,
        )
        result = capture(worker, handle, lid)
        assert result["status"] == "ok"
        assert len(artifacts.list_metadata(ART_OWNER)) == 2
    finally:
        live.shutdown()


def test_failed_terminal_job_write_cancels_instead_of_leaving_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(
        tmp_path,
        backend=lambda name, handle, lid, timeout: CaptureFrame(
            b"wrong-image", name, handle, lid, False, False, True
        ),
    )

    def fail_complete(*args: Any, **kwargs: Any) -> Any:
        raise JobStoreError("STORAGE_FAILURE")

    monkeypatch.setattr(jobs, "complete", fail_complete)
    try:
        result = capture(worker, handle, lid)
        assert result["status"] == "uncertain"
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"
        assert artifacts.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


def test_failed_private_revocation_does_not_skip_job_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    put = artifacts.put
    count = [0]

    def bad_receipt(owner: str, payload: bytes, **kwargs: Any) -> dict[str, Any]:
        count[0] += 1
        if count[0] == 2:
            raise ArtifactStoreError("STORAGE_FAILURE")
        return put(owner, payload, **kwargs)

    monkeypatch.setattr(artifacts, "put", bad_receipt)

    def failed_revoke(*args: Any) -> None:
        raise ArtifactStoreError("STORAGE_FAILURE")

    monkeypatch.setattr(artifacts, "revoke", failed_revoke)
    try:
        result = capture(worker, handle, lid)
        assert result["status"] == "uncertain"
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"
        assert count == [2]
    finally:
        live.shutdown()
