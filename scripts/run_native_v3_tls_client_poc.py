#!/usr/bin/env python3
"""E02.a test-only real AndroidKeyStore TLS client → pinned Host OpenSSL server.

Only ephemeral certificates on an independently owned disposable API36 AVD.
The Android Keystore private key cannot leave Android. ADB reverse carries
bytes only and is NEVER treated as caller authentication or user consent.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import secrets
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from scripts.native_v3_owned_avd import exclusive_avd_lock
from scripts.native_v3_tls_poc import POCError
from scripts.run_native_v3_tls_poc import _adb, _preflight, _run

SERIAL = "emulator-5570"
AVD = "android_mcp_native_v3_tls_api36_20261014"
TAG = "NativeV3TlsClient"
TEST_CLASS = (
    "org.androidmcp.v3tlsfixture.MutualTlsClientAndroidTest"
    "#androidKeyStoreClientNeedsPinnedHostAndClientTrust"
)
TEST_COMPONENT = (
    "org.androidmcp.v3tlsfixture.test/androidx.test.runner.AndroidJUnitRunner"
)
TARGET_PACKAGE = "org.androidmcp.v3tlsfixture"
ANDROID_LISTEN_PORT = 39145


def create_host_certificate(folder: Path) -> tuple[bytes, Path, Path]:
    """Short-lived server identity, private key confined to temporary 0600 file."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(minutes=30))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ip_address("127.0.0.1"))]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=False,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    server_pem = cert.public_bytes(serialization.Encoding.PEM)
    server_key = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    path_cert = folder / "host-server.pem"
    path_key = folder / "host-server-key.pem"
    path_cert.write_bytes(server_pem)
    path_key.write_bytes(server_key)
    path_cert.chmod(0o600)
    path_key.chmod(0o600)
    return cert.public_bytes(serialization.Encoding.DER), path_cert, path_key


def parse_android_ready(logcat: str, nonce: str) -> bytes:
    if not re.fullmatch(r"[a-f0-9]{24}", nonce) or len(logcat) > 128_000:
        raise POCError("Invalid nonce or oversized Android readiness record")
    regex = re.compile(
        rf"{TAG}: READY nonce={nonce} port={ANDROID_LISTEN_PORT} "
        r"cert_base64=([A-Za-z0-9+/=]+)(?=\s|$)"
    )
    entries = regex.findall(logcat)
    if len(entries) != 1:
        raise POCError("No single current-epoch Android TLS client public identity")
    try:
        der = base64.b64decode(entries[0], validate=True)
        cert = x509.load_der_x509_certificate(der)
        cert.public_key()  # public identity must parse as an actual certificate
    except (ValueError, TypeError) as exc:
        raise POCError("Malformed Android public TLS certificate") from exc
    if not (128 <= len(der) <= 6000):
        raise POCError("Unexpected client public cert length")
    return der


def parse_android_complete(logcat: str, instrument: str, nonce: str) -> None:
    if (
        f"{TAG}: COMPLETE nonce={nonce} allowed=1 denied=2" not in logcat
        or "OK (1 test)" not in instrument
        or "INSTRUMENTATION_CODE: -1" not in instrument
        or "FAILURES!!!" in instrument
    ):
        raise POCError(
            "Android KeyStore client mutual TLS positive/negative tests failed"
        )


def trusted_host_server(
    host_cert: Path, host_key: Path, client_der: bytes
) -> ssl.SSLContext:
    cert = x509.load_der_x509_certificate(client_der)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_cert_chain(str(host_cert), str(host_key))
    ctx.load_verify_locations(
        cadata=cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
    )
    ctx.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    return ctx


def server_verify_connections(
    listener: socket.socket, context: ssl.SSLContext, trusted_der: bytes, nonce: str
) -> tuple[int, int]:
    allowed = 0
    denied = 0
    listener.settimeout(14)
    for trial in range(3):
        with listener.accept()[0] as raw:
            raw.settimeout(12)
            try:
                with context.wrap_socket(raw, server_side=True) as secure:
                    presented = secure.getpeercert(binary_form=True)
                    if presented is None or presented != trusted_der:
                        raise POCError("Host TLS server accepted unpinned Android cert")
                    message = bytearray()
                    while len(message) < 100:
                        c = secure.recv(1)
                        if not c:
                            raise POCError("TLS client closed without intended request")
                        if c == b"\n":
                            break
                        message.extend(c)
                    if bytes(message) != f"POC={nonce}".encode("ascii"):
                        raise POCError("Wrong signed client nonce, forbidden action")
                    secure.sendall(f"TLS_OK={nonce}\n".encode("ascii"))
                    allowed += 1
            except ssl.SSLError:
                denied += 1
    if allowed != 1 or denied != 2:
        raise POCError(f"mTLS Host validation incomplete: {allowed=} {denied=}")
    return allowed, denied


def run_client_poc(repo: Path, output_dir: Path) -> dict[str, Any]:
    repo = repo.resolve(strict=True)
    owner, _, avd = _preflight()
    with exclusive_avd_lock(avd / "v3-tls-exclusive.lock"):
        owner, observed, _ = _preflight()
        package = (
            repo
            / "android/native-v3-tls-fixture/build/outputs/apk/debug/native-v3-tls-fixture-debug.apk"
        )
        android_test = (
            repo / "android/native-v3-tls-fixture/build/outputs/apk/androidTest/debug/"
            "native-v3-tls-fixture-debug-androidTest.apk"
        )
        if not all(
            p.is_file() and p.stat().st_size > 10_000 for p in (package, android_test)
        ):
            raise POCError("Signed Android test-only TLS fixture not built")
        for apk in (package, android_test):
            install = _adb("install", "-r", str(apk), timeout=90)
            if (
                not install.strip().splitlines()
                or install.strip().splitlines()[-1] != "Success"
            ):
                raise POCError("Android TLS test app installation not confirmed")
        package_metadata = _adb("shell", "dumpsys", "package", TARGET_PACKAGE)
        if "versionCode=1 minSdk=30 targetSdk=36" not in package_metadata:
            raise POCError("OS package manager did not confirm test fixture")

        nonce = secrets.token_hex(12)
        with tempfile.TemporaryDirectory(prefix="native-v3-tls-host-") as temp:
            private_folder = Path(temp)
            public_server_der, cert_path, private_path = create_host_certificate(
                private_folder
            )
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.bind(("127.0.0.1", 0))
                listener.listen(4)
                server_port = listener.getsockname()[1]
                # ADB reverse is a *transport* to this private Host port,
                # not any grant or authorization. No remote/public TLS socket.
                _adb(
                    "reverse",
                    "--no-rebind",
                    f"tcp:{ANDROID_LISTEN_PORT}",
                    f"tcp:{server_port}",
                )
                proc: subprocess.Popen[bytes] | None = None
                try:
                    args = [
                        "adb",
                        "-s",
                        SERIAL,
                        "shell",
                        "am",
                        "instrument",
                        "-w",
                        "-r",
                        "-e",
                        "class",
                        TEST_CLASS,
                        "-e",
                        "run_nonce",
                        nonce,
                        "-e",
                        "reverse_port",
                        str(ANDROID_LISTEN_PORT),
                        "-e",
                        "host_cert_base64",
                        base64.b64encode(public_server_der).decode("ascii"),
                        TEST_COMPONENT,
                    ]
                    proc = subprocess.Popen(
                        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                    )
                    deadline = time.monotonic() + 20
                    ready: bytes | None = None
                    while time.monotonic() < deadline:
                        logs = _adb(
                            "logcat", "-d", "-t", "120", "-s", f"{TAG}:I", "*:S"
                        )
                        try:
                            ready = parse_android_ready(logs, nonce)
                            break
                        except POCError:
                            if proc.poll() is not None:
                                raise POCError(
                                    "Android test ended before mutual TLS readiness"
                                ) from None
                            time.sleep(0.2)
                    if ready is None:
                        raise POCError("Android private identity readiness timeout")
                    ctx = trusted_host_server(cert_path, private_path, ready)
                    success, rejections = server_verify_connections(
                        listener, ctx, ready, nonce
                    )
                    try:
                        output, errors = proc.communicate(timeout=18)
                    except subprocess.TimeoutExpired as exc:
                        raise POCError(
                            "AndroidJUnitRunner timed out after TLS connections"
                        ) from exc
                    execution = (output + errors).decode("utf-8", "replace")
                    logs = _adb("logcat", "-d", "-t", "140", "-s", f"{TAG}:I", "*:S")
                    parse_android_complete(logs, execution, nonce)
                    report = {
                        "status": "PASS_REAL_ANDROID_KEYSTORE_TLS_POC_ONLY",
                        "product_status": "PRODUCT_INCOMPLETE",
                        "production_pairing_implemented": False,
                        "android_api": 36,
                        "avd": AVD,
                        "android_boot_identity": observed["boot_identity"],
                        "emulator_pid": owner["pid"],
                        "git_head": _run(
                            ["git", "-C", str(repo), "rev-parse", "HEAD"]
                        ).strip(),
                        "git_tree": _run(
                            ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"]
                        ).strip(),
                        "android_keystore_client_cert_sha256": hashlib.sha256(
                            ready
                        ).hexdigest(),
                        "host_server_cert_sha256": hashlib.sha256(
                            public_server_der
                        ).hexdigest(),
                        "test_apk_sha256": hashlib.sha256(
                            android_test.read_bytes()
                        ).hexdigest(),
                        "fixture_apk_sha256": hashlib.sha256(
                            package.read_bytes()
                        ).hexdigest(),
                        "actual_host_verified_client": success == 1,
                        "actual_host_rejected_clients": rejections,
                        "actual_android_verified_host": True,
                        "transport": "ADB reverse over private loopback to Python OpenSSL mTLS",
                        "test_private_key_retention": "MODE_0600_TEMPORARY_FILE_REMOVED_AFTER_TEST",
                        "independent_security_review": "NOT_PERFORMED",
                        "physical_device_used": False,
                        "public_listener": False,
                        "feature_done": False,
                        "timestamp_unix": int(time.time()),
                    }
                    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                    receipt = output_dir / f"tls-client-{report['timestamp_unix']}.json"
                    with receipt.open("x") as destination:
                        json.dump(report, destination, sort_keys=True, indent=2)
                        destination.write("\n")
                    receipt.chmod(0o600)
                    return report
                finally:
                    if proc is not None:
                        if proc.poll() is None:
                            proc.kill()
                        proc.communicate(timeout=10)
                    _adb(
                        "reverse", "--remove", f"tcp:{ANDROID_LISTEN_PORT}", timeout=10
                    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(run_client_poc(args.repo, args.evidence_dir), sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        POCError,
        ValueError,
        OSError,
        ssl.SSLError,
        subprocess.TimeoutExpired,
    ) as exc:
        print(f"E02A_MTLS_CLIENT_FAIL_CLOSED: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
