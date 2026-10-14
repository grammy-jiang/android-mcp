"""Fail-closed local AVD ownership/HMAC; not Host or Android authorization.

The sole source of trust is an externally established test-only local 0600
HMAC seal, not ADB port identity or a model-created permission grant.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import stat
import tempfile
from pathlib import Path
from typing import Any


class IdentityError(ValueError):
    """An AVD or process cannot prove disposable exclusive ownership."""


def _require(assertion: bool, message: str) -> None:
    if not assertion:
        raise IdentityError(message)


def validate_identity(owner: dict[str, Any], observed: dict[str, Any]) -> None:
    """Pure functional admission; test first, inspect right before any install."""
    _require(owner.get("disposable") is True, "Not a declared disposable AVD")
    name = owner.get("avd")
    serial = owner.get("expected_serial")
    api = owner.get("expected_api")
    _require(
        isinstance(name, str)
        and bool(
            re.fullmatch(r"android_mcp_native_v3_api(30|33|34|36)_20[0-9]{6}", name)
        ),
        "Unknown or non-owned AVD",
    )
    _require(
        owner.get("worktree", "").startswith("android-mcp-native-v3-"),
        "Wrong owner worktree",
    )
    _require(owner.get("host") == socket.gethostname(), "Wrong owner workstation")
    _require(
        isinstance(serial, str) and bool(re.fullmatch(r"emulator-55[0-9]{2}", serial)),
        "Physical/malformed serial",
    )
    _require(isinstance(api, int) and api in (30, 33, 34, 36), "Unapproved Android API")
    _require(name == f"android_mcp_native_v3_api{api}_20261014", "Wrong AVD marker/API")
    _require(
        owner.get("pid", 0) > 0 and isinstance(owner.get("pid"), int),
        "No owned emulator PID",
    )
    _require(observed.get("serial") == serial, "Serial changed")
    _require(observed.get("avd") == name, "AVD identity mismatch")
    _require(observed.get("api") == api, "SDK mismatch")
    _require(observed.get("qemu") == "1", "Physical device or unverifiable emulator")
    _require(observed.get("abi") == "arm64-v8a", "Unknown ABI")
    _require(observed.get("boot_completed") == "1", "Device not fully booted")
    boot = observed.get("boot_identity")
    _require(
        isinstance(boot, str)
        and bool(
            re.fullmatch(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", boot
            )
        ),
        "Missing device kernel boot epoch",
    )
    process = observed.get("process")
    _require(isinstance(process, str) and "qemu-system-" in process, "Not QEMU process")
    _require(
        f"-avd {name}" in process and f"-port {serial.split('-')[1]}" in process,
        "Emulator process does not own expected AVD/port",
    )


def validate_test_run_nonce(value: str) -> str:
    """A per-test-run nonce is unpredictable, exact and never an OS grant."""
    _require(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value) is not None,
        "Test run must use a fresh 128-bit lowercase hex nonce",
    )
    return value


def _owner_canonical_bytes(data: dict[str, Any]) -> bytes:
    try:
        output = json.dumps(
            data,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (ValueError, TypeError) as error:
        raise IdentityError("Invalid JSON owner/proof record") from error
    _require(len(output) < 8192, "AVD owner/proof record too large")
    return output


def _signature_payload(record: dict[str, Any]) -> bytes:
    return _owner_canonical_bytes(
        {key: value for key, value in record.items() if key != "hmac_sha256"}
    )


def create_owner_attestation(
    owner: dict[str, Any],
    observed: dict[str, Any],
    process_start: str,
    secret: bytes,
    nonce: str,
    issued: int,
) -> dict[str, Any]:
    """Seal a *pre-verified exclusively owned* disposable process/boot.

    The local HMAC key is never in Git. This only establishes a test-lab
    ownership continuity check against accidentally adopting another AVD;
    it is not an Android/Host user authentication credential.
    """
    validate_identity(owner, observed)
    validate_test_run_nonce(nonce)
    _require(
        isinstance(secret, bytes) and len(secret) == 32,
        "Missing 256-bit local disposable AVD seal",
    )
    _require(
        isinstance(process_start, str)
        and len(process_start) in range(12, 100)
        and "2026" in process_start,
        "Expected exact owner QEMU process creation epoch",
    )
    _require(type(issued) is int and issued > 1700000000, "Invalid proof issue clock")
    started = owner.get("started_utc")
    _require(
        type(started) is int and started <= issued,
        "Proof issue precedes declared owned process creation",
    )
    receipt: dict[str, Any] = {
        "schema": "native-v3-avd-owner-attestation.v1",
        "issued_at_unix": issued,
        "expiry_unix": issued + 86400,
        "owner_sha256": hashlib.sha256(_owner_canonical_bytes(owner)).hexdigest(),
        "pid_start_sha256": hashlib.sha256(process_start.encode("utf-8")).hexdigest(),
        "boot_id": observed["boot_identity"],
        "pid": owner["pid"],
        "avd": owner["avd"],
        "serial": owner["expected_serial"],
        "api": owner["expected_api"],
        "nonce": nonce,
    }
    receipt["hmac_sha256"] = hmac.new(
        secret, _signature_payload(receipt), hashlib.sha256
    ).hexdigest()
    return receipt


def verify_owner_attestation(
    proof: dict[str, Any],
    owner: dict[str, Any],
    observed: dict[str, Any],
    process_start: str,
    secret: bytes,
    now_unix: int,
) -> bool:
    """An unsigned owner JSON, stale boot or recycled PID can never pass."""
    validate_identity(owner, observed)
    _require(
        isinstance(proof, dict) and isinstance(secret, bytes) and len(secret) == 32,
        "No secure AVD owner proof",
    )
    _require(
        proof.get("schema") == "native-v3-avd-owner-attestation.v1"
        and validate_test_run_nonce(proof.get("nonce")) is not None,
        "Missing/invalid attested random owner nonce",
    )
    issued = proof.get("issued_at_unix")
    expires = proof.get("expiry_unix")
    _require(
        type(now_unix) is int
        and type(issued) is int
        and type(expires) is int
        and issued <= now_unix <= expires
        and 0 < expires - issued <= 86400,
        "AVD proof expired, stale, forged or issued in future",
    )
    _require(
        proof.get("owner_sha256")
        == hashlib.sha256(_owner_canonical_bytes(owner)).hexdigest()
        and isinstance(process_start, str)
        and proof.get("pid_start_sha256")
        == hashlib.sha256(process_start.encode("utf-8")).hexdigest(),
        "Owner JSON changed or QEMU PID was reused by another process",
    )
    _require(
        proof.get("pid") == owner["pid"]
        and proof.get("boot_id") == observed["boot_identity"]
        and proof.get("avd") == owner["avd"]
        and proof.get("serial") == owner["expected_serial"]
        and proof.get("api") == owner["expected_api"],
        "Owner proof not bound to exact AVD/boot/API/PID identity",
    )
    candidate = proof.get("hmac_sha256")
    _require(
        isinstance(candidate, str)
        and re.fullmatch(r"[a-f0-9]{64}", candidate) is not None,
        "Owner HMAC missing or malformed",
    )
    expected = hmac.new(secret, _signature_payload(proof), hashlib.sha256).hexdigest()
    _require(hmac.compare_digest(candidate, expected), "Owner proof HMAC mismatch")
    return True


def _open_private_regular(path: Path) -> int:
    """Read a single mode-0600 owned file without following a symlink."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except (OSError, ValueError) as exc:
        raise IdentityError("Private test owner credential/proof unavailable") from exc
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_size > 8192
    ):
        os.close(fd)
        raise IdentityError("Owner credential/proof must be a regular 0600 file")
    return fd


def read_lab_owner_secret(path: Path, *, create: bool = False) -> bytes:
    """Strict local test-only HMAC key; never auto provision during a test.

    create=True may be invoked only after independently verifying a newly
    owned exclusively disposable emulator during provisioning. No private
    key bytes are ever emitted to logs, source control or MCP.
    """
    if create and not path.exists() and not path.is_symlink():
        try:
            fd = os.open(
                path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
        except FileExistsError:
            pass  # Race: another trusted provisioning call created the key.
        else:
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "wb") as output:
                    output.write(secrets.token_bytes(32))
                    output.flush()
                    os.fsync(output.fileno())
            except Exception:
                path.unlink(missing_ok=True)
                raise
    fd = _open_private_regular(path)
    with os.fdopen(fd, "rb") as inp:
        key = inp.read(33)
    _require(len(key) == 32, "Local AVD owner HMAC key must be exactly 256 bits")
    return key


def atomic_create_owner_proof(path: Path, proof: dict[str, Any]) -> None:
    """Create a private immutable-at-issue proof file without overwrite."""
    _require(
        isinstance(proof, dict) and len(_owner_canonical_bytes(proof)) < 8192,
        "Malformed/bloated AVD owner proof",
    )
    _require(
        path.parent.is_dir() and not path.is_symlink(),
        "Owner attestation target is not a valid owned AVD directory",
    )
    with tempfile.NamedTemporaryFile(
        mode="wb", prefix=".native-v3-proof-", dir=path.parent, delete=False
    ) as provisional:
        temporary = Path(provisional.name)
        os.fchmod(provisional.fileno(), 0o600)
        provisional.write(_owner_canonical_bytes(proof))
        provisional.flush()
        os.fsync(provisional.fileno())
    try:
        try:
            os.link(temporary, path, follow_symlinks=False)
        except (FileExistsError, OSError) as error:
            raise IdentityError("Existing owner proof cannot be overwritten") from error
    finally:
        temporary.unlink(missing_ok=True)
    _require(
        stat.S_IMODE(path.stat().st_mode) == 0o600,
        "Owner proof not mode 0600 after atomic create",
    )


def _unique_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IdentityError("Duplicate key in owner proof JSON")
        result[key] = value
    return result


def read_owner_proof(path: Path) -> dict[str, Any]:
    """Read private proof, rejecting symlinks, duplicates and huge content."""
    fd = _open_private_regular(path)
    with os.fdopen(fd, "rb") as inp:
        payload = inp.read(8193)
    _require(len(payload) <= 8192, "Owner proof exceeded bounded read")
    try:
        record = json.loads(
            payload.decode("utf-8"), object_pairs_hook=_unique_json_pairs
        )
    except (UnicodeError, ValueError, TypeError) as error:
        raise IdentityError("Malformed or non-UTF-8 owner proof") from error
    _require(isinstance(record, dict), "Owner proof must be a JSON object")
    return record


def parse_owned_forward_routes(output: str, serial: str) -> tuple[str, ...]:
    """Record only owned emulator TCP forwards; never touch another device."""
    _require(
        isinstance(serial, str)
        and re.fullmatch(r"emulator-55[0-9]{2}", serial) is not None,
        "Refusing to inspect forwarded connections on physical serial",
    )
    _require(
        isinstance(output, str) and len(output) <= 8192, "Forward inventory not bounded"
    )
    entries = []
    for line in output.splitlines():
        if not line.startswith(serial + " "):
            continue
        parsed = re.fullmatch(
            rf"{re.escape(serial)} tcp:(\d{{4,5}}) tcp:(\d{{4,5}})", line
        )
        _require(
            parsed is not None
            and all(1024 <= int(port) <= 65535 for port in parsed.groups()),
            "Unapproved or malformed ADB forward on owned disposable AVD",
        )
        entries.append(line)
    _require(len(set(entries)) == len(entries), "Duplicate ADB forward alias")
    return tuple(sorted(entries))
