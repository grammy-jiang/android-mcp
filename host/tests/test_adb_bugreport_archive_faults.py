"""H5.a hostile synthetic bugreport ZIP and strict text redaction tests."""

from __future__ import annotations

import io
import stat
import struct
import zipfile
from pathlib import Path
from typing import Any

import pytest
from test_adb_bugreport_artifacts import (
    ART_OWNER,
    NAME,
    OWNER,
    RAW,
    archive,
    builder,
    collect,
)

from android_mcp_host.bugreport_support import (
    MAX_ZIP_BYTES,
    InvalidBugreport,
    _sanitize_lines,
    sanitize_bugreport,
    verified_redacted_zip,
)
from android_mcp_host.synthetic_bugreport import BugreportFrame


def zip_members(
    fields: list[tuple[str, bytes]],
    *,
    compression: int = zipfile.ZIP_DEFLATED,
    symlink: bool = False,
) -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", compression=compression) as z:
        for name, payload in fields:
            info = zipfile.ZipInfo(name)
            info.compress_type = compression
            if symlink and name == "bugreport.txt":
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, payload)
    return data.getvalue()


@pytest.mark.parametrize(
    "members",
    [
        [("bugreport.txt", RAW)],
        [("version.txt", b"BUGREPORTV1\n")],
        [("bugreport.txt", RAW), ("version.txt", b"BUGREPORTV1\n")],
        [("version.txt", b"BUGREPORTV1\n"), ("bugreport.txt", RAW), ("extra.txt", b"secret")],
        [("version.txt", b"BUGREPORTV1\n"), ("../private.txt", RAW)],
        [("version.txt", b"BUGREPORTV1\n"), ("nested/bugreport.txt", RAW)],
        [("version.txt", b"BUGREPORTV1\n"), ("bugreport.txt", RAW), ("BUGREPORT.txt", b"xx")],
        [
            ("version.txt", b"BUGREPORTV1\n"),
            ("bugreport.txt", RAW),
            ("bugreport.txt", b"duplicate"),
        ],
        [("VERSION.txt", b"BUGREPORTV1\n"), ("bugreport.txt", RAW)],
    ],
)
def test_t_h5a_03_unexpected_missing_duplicate_traversal_or_nested_members_denied(
    members: list[tuple[str, bytes]],
) -> None:
    with pytest.raises(InvalidBugreport):
        sanitize_bugreport(zip_members(members))


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"\xff\n",
        b"UPTIME_SECONDS=40",
        b"UPTIME_SECONDS=30\r\n",
        b"SECRET=\x00data\n",
        b"line\x07control\n",
        b"secret" * 100 + b"\n",
        b"unknown\n" * 129,
        b"STATE=ready\n" * 129,
    ],
)
def test_t_h5a_03_malformed_encoding_controls_and_line_budgets_denied(
    payload: bytes,
) -> None:
    with pytest.raises(InvalidBugreport):
        sanitize_bugreport(archive(text=payload))


def test_t_h5a_03_large_member_and_compression_bomb_denied() -> None:
    with pytest.raises(InvalidBugreport):
        sanitize_bugreport(archive(text=b"UPTIME_SECONDS=1\n" * 6000))
    with pytest.raises(InvalidBugreport):
        sanitize_bugreport(b"x" * (MAX_ZIP_BYTES + 1))
    with pytest.raises(InvalidBugreport):
        sanitize_bugreport(b"small")


def test_t_h5a_03_zip_symlink_and_non_standard_codec_denied() -> None:
    members = [("version.txt", b"BUGREPORTV1\n"), ("bugreport.txt", RAW)]
    with pytest.raises(InvalidBugreport):
        sanitize_bugreport(zip_members(members, symlink=True))
    with pytest.raises(InvalidBugreport):
        sanitize_bugreport(zip_members(members, compression=zipfile.ZIP_BZIP2))


def test_t_h5a_03_truncated_or_corrupted_local_zip_rejected() -> None:
    source = archive()
    with zipfile.ZipFile(io.BytesIO(source)) as zipped:
        info = zipped.getinfo("bugreport.txt")
    filename_length, extra_length = struct.unpack_from("<HH", source, info.header_offset + 26)
    corrupted = bytearray(source)
    corrupted[info.header_offset + 30 + filename_length + extra_length + 2] ^= 0x3F
    for data in (source[:-8], source[:-30], source[:-80], bytes(corrupted)):
        with pytest.raises(InvalidBugreport):
            sanitize_bugreport(data)


@pytest.mark.parametrize(
    "line",
    [
        b"ACCOUNT=user@example.com",
        b"PASSWORD=password123",
        b"TOKEN=auth-private",
        b"LOG_ID=person-identifier",
        b"HOSTNAME=my-computer",
        b"AUTHORIZATION=Bearer secret",
        b"BATTERY_PERCENT=101",
        b"STATE=awake",
        b"UPTIME_SECONDS=-1",
        b"UPTIME_SECONDS=999999999999999",
        b"MAC=aa:bb:cc:dd:ee:ff",
        b"SESSION=0xabcdef",
        b"IP=192.168.1.1",
    ],
)
def test_t_h5a_04_only_allowlisted_structured_diagnostics_are_preserved(
    line: bytes,
) -> None:
    sanitized, number = _sanitize_lines(line + b"\n")
    assert sanitized == b"[REDACTED]\n"
    assert number == 1
    assert line not in sanitized


def test_t_h5a_04_sanitized_archive_is_idempotent_and_has_no_raw_secret_bytes() -> None:
    first, count = sanitize_bugreport(archive())
    assert count == 3
    assert verified_redacted_zip(first) is True
    second, replacements = sanitize_bugreport(first)
    assert second == first
    assert replacements == 0
    for private in (b"user@example.com", b"private-bearer", b"real-person-id"):
        assert private not in first
    assert verified_redacted_zip(archive()) is False
    assert verified_redacted_zip("text") is False


@pytest.mark.parametrize(
    "marker",
    [
        "",
        "FAIL:/bugreports/bugreport-mcp-fixture.zip",
        "OK:/data/data/private.zip",
        "OK:/bugreports/../private.zip",
        "OK:/bugreports/bugreport-mcp-fixture.zip\nSECRET",
        "OK:bugreport-mcp-fixture.zip",
        1,
    ],
)
def test_t_h5a_03_untrusted_bugreportz_status_never_produces_an_artifact(
    tmp_path: Path,
    marker: Any,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    worker._fixture = lambda *args: BugreportFrame(
        archive(),
        marker,
        NAME,
        handle,
        lid,
        True,
        True,
    )
    try:
        denied = collect(worker, handle, lid)
        assert denied["status"] == "failed"
        assert denied["errors"][0]["code"] == "BAD_FRAME"
        assert store.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, denied["job_id"])["job"]["state"] == "failed"
    finally:
        live.shutdown()
