#!/usr/bin/env python3
"""E02.a real AndroidKeyStore/JSSE ↔ Python OpenSSL mutual TLS proof.

Test-only loopback server exists solely inside an AndroidJUnitRunner fixture.
No production listener, no stored Host credentials, no public network, no
privilege grants and no claim that ADB forwarding is authentication.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import select
import socket
import socketserver
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from scripts.native_v3_owned_avd import exclusive_avd_lock
from scripts.native_v3_tls_poc import (
    POCError,
    assert_ciphertext,
    assert_expected_server_cert,
    parse_ready,
    validate_exclusive_tls_avd,
    verify_android_completion,
)

SERIAL = "emulator-5570"
AVD = "android_mcp_native_v3_tls_api36_20261014"
TEST_PACKAGE = "org.androidmcp.v3tlsfixture.test"
APK_PACKAGE = "org.androidmcp.v3tlsfixture"
TEST_COMPONENT = f"{TEST_PACKAGE}/androidx.test.runner.AndroidJUnitRunner"
TEST_NAME = "org.androidmcp.v3tlsfixture.MutualTlsAndroidTest#realKeystoreMutualTlsRequiresPinnedClient"
TAG = "NativeV3TlsPoc"


class _TlsWireProxy(socketserver.ThreadingTCPServer):
    """Loopback ciphertext recorder; no TLS termination or private keys."""

    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, upstream_port: int):
        self.upstream_port = upstream_port
        self.captured_to_android = bytearray()
        self.captured_from_android = bytearray()
        self.capture_lock = threading.Lock()

        class Handler(socketserver.BaseRequestHandler):
            def handle(handler_self) -> None:
                with socket.create_connection(
                    ("127.0.0.1", handler_self.server.upstream_port), timeout=8
                ) as upstream:
                    sources = (handler_self.request, upstream)
                    deadline = time.monotonic() + 20
                    while time.monotonic() < deadline:
                        ready, _, _ = select.select(sources, [], [], 0.5)
                        for source in ready:
                            data = source.recv(16384)
                            if not data:
                                return
                            other = (
                                upstream
                                if source is handler_self.request
                                else handler_self.request
                            )
                            with handler_self.server.capture_lock:
                                output = (
                                    handler_self.server.captured_to_android
                                    if source is handler_self.request
                                    else handler_self.server.captured_from_android
                                )
                                if len(output) + len(data) > 128 * 1024:
                                    raise POCError("TLS capture exceeded safe bound")
                                output.extend(data)
                            other.sendall(data)
                    raise POCError("TLS proxy connection timed out")

        super().__init__(("127.0.0.1", 0), Handler)


def _run(argv: list[str], timeout: int = 30, limit: int = 100 * 1024) -> str:
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise POCError(f"Bounded tool failed: {argv[0]}") from exc
    if p.returncode != 0 or len(p.stdout) + len(p.stderr) > limit:
        raise POCError(
            f"Test tool failed ({Path(argv[0]).name}, {p.returncode}): "
            + p.stderr[:200].decode("utf-8", "replace")
        )
    return p.stdout.decode("utf-8", "replace")


def _adb(*args: str, timeout: int = 30) -> str:
    return _run(["adb", "-s", SERIAL, *args], timeout=timeout)


def _preflight() -> tuple[dict, dict, Path]:
    avd = Path.home() / ".android/avd" / f"{AVD}.avd"
    marker = avd / "v3-tls-owner.json"
    if not marker.is_file():
        raise POCError("Test-only owned TLS AVD marker missing")
    owner = json.loads(marker.read_text())
    process = _run(["ps", "-p", str(owner["pid"]), "-o", "command="], timeout=8)
    observed = {
        "serial": SERIAL,
        "avd": _adb("emu", "avd", "name").splitlines()[0].strip(),
        "api": int(_adb("shell", "getprop", "ro.build.version.sdk").strip()),
        "abi": _adb("shell", "getprop", "ro.product.cpu.abi").strip(),
        "qemu": _adb("shell", "getprop", "ro.kernel.qemu").strip(),
        "boot_completed": _adb("shell", "getprop", "sys.boot_completed").strip(),
        "boot_identity": _adb(
            "shell", "cat", "/proc/sys/kernel/random/boot_id"
        ).strip(),
        "process": process.strip(),
    }
    validate_exclusive_tls_avd(owner, observed)
    return owner, observed, avd


def _create_client_certificate(root: Path, name: str) -> tuple[bytes, Path, Path]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    ident = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(ident)
        .issuer_name(ident)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(minutes=30))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False
        )
        .sign(private_key, hashes.SHA256())
    )
    client_der = certificate.public_bytes(serialization.Encoding.DER)
    certfile, keyfile = root / f"{name}.cert.pem", root / f"{name}.key.pem"
    certfile.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    keyfile.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    certfile.chmod(0o600)
    keyfile.chmod(0o600)
    return client_der, certfile, keyfile


def _read_logcat() -> str:
    return _adb("logcat", "-d", "-t", "100", "-s", f"{TAG}:I", "*:S", timeout=15)


def _await_ready(proc: subprocess.Popen[bytes], nonce: str) -> tuple[int, bytes]:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            stdout, stderr = proc.communicate(timeout=5)
            raise POCError(
                "TLS AndroidJUnitRunner terminated before readiness: "
                + (stdout + stderr)[-1600:].decode("utf-8", "replace")
            )
        try:
            return parse_ready(_read_logcat(), nonce)
        except POCError:
            time.sleep(0.35)
    raise POCError("AndroidKeystore TLS fixture readiness deadline exceeded")


def _available_forward_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _client_ssl_context(
    server_der: bytes, cert: Path | None, key: Path | None
) -> ssl.SSLContext:
    server = x509.load_der_x509_certificate(server_der)
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ctx.check_hostname = False  # Exact pinned leaf on private ADB port only.
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    ctx.set_ciphers("ECDHE-ECDSA-AES128-GCM-SHA256")
    ctx.load_verify_locations(
        cadata=server.public_bytes(serialization.Encoding.PEM).decode("ascii")
    )
    if cert is not None and key is not None:
        ctx.load_cert_chain(str(cert), str(key))
    return ctx


def _attempt(
    context: ssl.SSLContext, port: int, nonce: str, *, expect_success: bool
) -> str:
    response = ""
    stage = "connecting"
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=8) as raw:
            raw.settimeout(8)
            stage = "TLS_handshake"
            with context.wrap_socket(raw, server_hostname=None) as tls:
                stage = "send_request"
                tls.sendall(f"POC={nonce}\n".encode())
                stage = "receive_response"
                response = tls.recv(80).decode("ascii", "strict")
        if expect_success and response == f"TLS_OK={nonce}\n":
            return "accepted"
    except (ssl.SSLError, OSError, ConnectionError, UnicodeError) as exc:
        if not expect_success:
            return "rejected"
        raise POCError(
            "Expected pinned mutual TLS handshake failed: "
            + stage
            + ": "
            + type(exc).__name__
            + ": "
            + str(exc)[:160]
        ) from None
    if expect_success:
        raise POCError("Valid mutual TLS response did not match nonce")
    # A connection closed without reply is also genuine denial: the Android
    # test must independently attest its own failed TLS/identity verification.
    if response == "":
        return "rejected"
    raise POCError("Untrusted TLS Host received application data")


def run_poc(repo: Path, evidence_dir: Path) -> dict:
    repo = repo.resolve(strict=True)
    owner, _, avd = _preflight()
    with exclusive_avd_lock(avd / "v3-tls-exclusive.lock"):
        owner, os_state, _ = _preflight()
        apk = (
            repo / "android/native-v3-tls-fixture/build/outputs/apk/debug/"
            "native-v3-tls-fixture-debug.apk"
        )
        test_apk = (
            repo / "android/native-v3-tls-fixture/build/outputs/apk/androidTest/"
            "debug/native-v3-tls-fixture-debug-androidTest.apk"
        )
        if not all(
            path.is_file() and path.stat().st_size > 10_000 for path in (apk, test_apk)
        ):
            raise POCError("Signed TLS instrumentation APKs not built")
        for file in (apk, test_apk):
            response = _adb("install", "-r", str(file), timeout=90).strip()
            if not response.splitlines() or response.splitlines()[-1] != "Success":
                raise POCError("Failed to install TLS test fixture")
        package = _adb("shell", "dumpsys", "package", APK_PACKAGE)
        if "versionCode=1 minSdk=30 targetSdk=36" not in package:
            raise POCError("Installed Android package manager oracle mismatch")

        nonce = secrets.token_hex(12)
        with tempfile.TemporaryDirectory(prefix="native-v3-mtls-") as workspace:
            tmp = Path(workspace)
            trusted_der, trusted_cert, trusted_key = _create_client_certificate(
                tmp, "android-mcp-v3-trusted-host"
            )
            _, attacker_cert, attacker_key = _create_client_certificate(
                tmp, "android-mcp-v3-attacker"
            )
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
                TEST_NAME,
                "-e",
                "run_nonce",
                nonce,
                "-e",
                "client_cert_base64",
                base64.b64encode(trusted_der).decode("ascii"),
                TEST_COMPONENT,
            ]
            proc = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            port = None
            try:
                device_port, server_cert = _await_ready(proc, nonce)
                # The certificate comes from the current pinned emulator
                # instrumentation record, not arbitrary network discovery.
                pinned = hashlib.sha256(server_cert).hexdigest()
                assert_expected_server_cert(server_cert, pinned)
                port = _available_forward_port()
                _adb("forward", "--no-rebind", f"tcp:{port}", f"tcp:{device_port}")
                no_cert = _client_ssl_context(server_cert, None, None)
                wrong = _client_ssl_context(server_cert, attacker_cert, attacker_key)
                trusted = _client_ssl_context(server_cert, trusted_cert, trusted_key)
                with _TlsWireProxy(port) as proxy:
                    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
                    thread.start()
                    try:
                        endpoint = proxy.server_address[1]
                        statuses = [
                            _attempt(no_cert, endpoint, nonce, expect_success=False),
                            _attempt(wrong, endpoint, nonce, expect_success=False),
                            _attempt(trusted, endpoint, nonce, expect_success=True),
                        ]
                    except POCError:
                        print(
                            "E02A_WIRE_DIAGNOSTIC"
                            f" to_android={len(proxy.captured_to_android)}"
                            f" first={bytes(proxy.captured_to_android[:5]).hex()}"
                            f" from_android={len(proxy.captured_from_android)}"
                            f" first={bytes(proxy.captured_from_android[:5]).hex()}",
                            file=sys.stderr,
                        )
                        raise
                    finally:
                        proxy.shutdown()
                        thread.join(timeout=8)
                if statuses != ["rejected", "rejected", "accepted"]:
                    raise POCError("Actual Host identity/denial sequence incomplete")
                client_tls_wire = bytes(proxy.captured_to_android)
                android_tls_wire = bytes(proxy.captured_from_android)
                assert_ciphertext(client_tls_wire, nonce)
                assert_ciphertext(android_tls_wire, nonce)
                try:
                    stdout, stderr = proc.communicate(timeout=35)
                except subprocess.TimeoutExpired as exc:
                    raise POCError("AndroidJUnitRunner TLS callback timed out") from exc
                instrumented = (stdout + stderr).decode("utf-8", "replace")
                verify_android_completion(_read_logcat(), instrumented, nonce)
                # Status response is received from authenticated Android
                # TLS socket, not ADB shell or Kotlin JVM fake.
                report = {
                    "status": "PASS_REAL_TEST_FIXTURE_MTLS_ONLY",
                    "product": "PRODUCT_INCOMPLETE",
                    "native_release_capabilities_done": 0,
                    "source_head": _run(
                        ["git", "-C", str(repo), "rev-parse", "HEAD"]
                    ).strip(),
                    "source_tree": _run(
                        ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"]
                    ).strip(),
                    "android_api": 36,
                    "avd": AVD,
                    "serial": SERIAL,
                    "boot_identity": os_state["boot_identity"],
                    "emulator_pid": owner["pid"],
                    "actual_android_keystore_private_key_nonexportable": True,
                    "actual_android_tls_protocol": "JSSE TLSv1.2 ECDHE_ECDSA_AES128_GCM_SHA256 test-only",
                    "host_tls_protocol": "Python stdlib OpenSSL TLSv1.2 pinned self-signed leaf",
                    "pinned_host_certificate_sha256": hashlib.sha256(
                        trusted_der
                    ).hexdigest(),
                    "pinned_android_certificate_sha256": pinned,
                    "test_apk_sha256": hashlib.sha256(
                        test_apk.read_bytes()
                    ).hexdigest(),
                    "apk_sha256": hashlib.sha256(apk.read_bytes()).hexdigest(),
                    "client_result": statuses,
                    "client_tls_wire_bytes": len(client_tls_wire),
                    "android_tls_wire_bytes": len(android_tls_wire),
                    "client_tls_wire_sha256": hashlib.sha256(
                        client_tls_wire
                    ).hexdigest(),
                    "android_tls_wire_sha256": hashlib.sha256(
                        android_tls_wire
                    ).hexdigest(),
                    "plaintext_marker_visible_on_tls_wire": False,
                    "android_reported_denials": 2,
                    "android_reported_successes": 1,
                    "public_listener": False,
                    "physical_android_used": False,
                    "production_pairing_implemented": False,
                    "timestamp_unix": int(time.time()),
                }
                evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                receipt = (
                    evidence_dir / f"e02a-tls-api36-{report['timestamp_unix']}.json"
                )
                receipt.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
                receipt.chmod(0o600)
                return report
            finally:
                if port is not None:
                    try:
                        _adb("forward", "--remove", f"tcp:{port}", timeout=10)
                    except POCError:
                        pass
                if proc.poll() is None:
                    proc.kill()
                proc.communicate(timeout=10)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(run_poc(args.repo, args.evidence_dir), sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (POCError, ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"E02A_FAIL_CLOSED: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
