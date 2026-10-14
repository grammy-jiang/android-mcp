"""E02.a strict test-only TLS POC evidence preflight and metadata helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import socket
from typing import Any


class POCError(ValueError):
    """Test-only Host/Native TLS evidence is missing or untrustworthy."""


def _require(ok: bool, error: str) -> None:
    if not ok:
        raise POCError(error)


def parse_ready(logs: str, nonce: str) -> tuple[int, bytes]:
    _require(bool(re.fullmatch(r"[0-9a-f]{24}", nonce)), "Missing random run nonce")
    _require(len(logs) < 96_000, "TLS readiness output exceeded budget")
    candidates = []
    regex = re.compile(
        rf"NativeV3TlsPoc:\s+READY nonce={re.escape(nonce)} "
        r"port=([0-9]{1,5}) cert_base64=([A-Za-z0-9+/=]+)(?=\s|$)"
    )
    for line in logs.splitlines():
        matched = regex.search(line)
        if matched:
            candidates.append(matched.groups())
    _require(len(candidates) == 1, "TLS readiness missing or replay/duplicate")
    port = int(candidates[0][0])
    _require(1024 <= port <= 65535, "TLS listener port out of safe range")
    try:
        cert = base64.b64decode(candidates[0][1], validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise POCError("Invalid public certificate encoding") from exc
    _require(128 <= len(cert) <= 6000, "Invalid certificate size")
    return port, cert


def verify_android_completion(logs: str, instrumentation: str, nonce: str) -> None:
    _require(bool(re.fullmatch(r"[0-9a-f]{24}", nonce)), "Invalid completion nonce")
    _require(
        f"COMPLETE nonce={nonce} allowed=1 denied=2" in logs,
        "Android JSSE did not verify exactly two denials and one paired success",
    )
    _require(
        "OK (1 test)" in instrumentation
        and "INSTRUMENTATION_CODE: -1" in instrumentation
        and "FAILURES!!!" not in instrumentation,
        "AndroidJUnitRunner did not finish real TLS assertions",
    )


def assert_expected_server_cert(der: bytes, sha256: str) -> None:
    _require(
        isinstance(sha256, str) and bool(re.fullmatch(r"[a-f0-9]{64}", sha256)),
        "TLS pin is not a SHA256 digest",
    )
    _require(len(der) in range(128, 6001), "TLS DER certificate length invalid")
    _require(
        hmac.compare_digest(hashlib.sha256(der).hexdigest(), sha256),
        "TLS server leaf certificate pin mismatch",
    )


def assert_ciphertext(wire: bytes, nonce: str) -> None:
    """A capture of TLS records, not a guarantee of a complete threat model."""
    _require(
        len(wire) >= 12 and wire.startswith(b"\x16\x03"), "No recorded TLS ClientHello"
    )
    _require(b"\x17\x03" in wire, "No encrypted TLS application record observed")
    _require(b"POC=" + nonce.encode("ascii") not in wire, "Raw request leaked in wire")
    _require(
        b"TLS_OK=" + nonce.encode("ascii") not in wire, "Raw response leaked in wire"
    )
    _require(b"GET /" not in wire and b"HTTP/" not in wire, "Plain HTTP in TLS capture")


def validate_exclusive_tls_avd(owner: dict[str, Any], observed: dict[str, Any]) -> None:
    avd = "android_mcp_native_v3_tls_api36_20261014"
    _require(owner.get("disposable") is True, "Not an owned disposable AVD")
    _require(
        owner.get("avd") == avd
        and owner.get("serial") == "emulator-5570"
        and owner.get("api") == 36
        and owner.get("abi") == "arm64-v8a"
        and owner.get("worktree") == "android-mcp-native-v3-e02a-mtls-poc-20261014"
        and owner.get("host") == socket.gethostname(),
        "TLS AVD marker is not owned by this test",
    )
    pid = owner.get("pid")
    _require(type(pid) is int and pid > 0, "Missing emulator PID")
    _require(
        observed.get("serial") == "emulator-5570"
        and observed.get("avd") == avd
        and observed.get("api") == 36
        and observed.get("abi") == "arm64-v8a"
        and observed.get("qemu") == "1"
        and observed.get("boot_completed") == "1",
        "Wrong device/ABI/boot or physical Android",
    )
    boot = observed.get("boot_identity")
    _require(
        isinstance(boot, str)
        and bool(re.fullmatch(r"[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}", boot)),
        "Invalid kernel boot epoch",
    )
    process = observed.get("process", "")
    _require(
        isinstance(process, str)
        and "qemu-system-" in process
        and f"-avd {avd}" in process
        and "-port 5570" in process,
        "AVD emulator OS process not owned",
    )
