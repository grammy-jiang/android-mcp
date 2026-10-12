#!/usr/bin/env python3
"""Real Kotlin/JVM HTTP N0.b guard acceptance, without ADB or Android hardware.

Every raw request uses only an ephemeral IPv4 loopback port, bounded reads,
and the executable already built by check-native.sh. No secret fixture, user
device, Android operation or externally accessible listener is involved.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "android/native-mcp-jvm/build/install/native-mcp-jvm/bin/native-mcp-jvm"


def unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def raw_response(port: int, request: bytes) -> tuple[int, str]:
    with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
        sock.settimeout(3)
        sock.sendall(request)
        # Only a small first response segment is needed to validate denials.
        data = sock.recv(8192)
    first_line = data.split(b"\r\n", 1)[0]
    tokens = first_line.split(b" ")
    if len(tokens) < 2 or not tokens[0].startswith(b"HTTP/"):
        raise AssertionError("Guard did not return a valid HTTP status")
    code = int(tokens[1])
    return code, data.decode("utf-8", errors="replace")


def request_bytes(
    method: str,
    path: str,
    host: str,
    *,
    origin: str | None = None,
    length: str | None = None,
    extra: str = "",
) -> bytes:
    # Values are fixed synthetic test input, never taken from untrusted callers.
    headers = [f"{method} {path} HTTP/1.1", f"Host: {host}", "Connection: close"]
    if origin is not None:
        headers.append(f"Origin: {origin}")
    if length is not None:
        headers.append(f"Content-Length: {length}")
    if extra:
        headers.append(extra)
    return ("\r\n".join(headers) + "\r\n\r\n").encode("ascii")


def check_denials(port: int) -> dict[str, object]:
    cases = (
        ("bad_host", request_bytes("POST", "/mcp", "evil.invalid", length="0"), 403),
        (
            "host_suffix",
            request_bytes("POST", "/mcp", "127.0.0.1.evil.invalid", length="0"),
            403,
        ),
        (
            "bad_origin",
            request_bytes(
                "POST",
                "/mcp",
                f"127.0.0.1:{port}",
                origin="https://evil.invalid",
                length="0",
            ),
            403,
        ),
        (
            "cross_origin_preflight",
            request_bytes(
                "OPTIONS",
                "/mcp",
                f"127.0.0.1:{port}",
                origin="https://evil.invalid",
                length="0",
            ),
            403,
        ),
        (
            "local_preflight",
            request_bytes(
                "OPTIONS",
                "/mcp",
                f"127.0.0.1:{port}",
                origin=f"http://127.0.0.1:{port}",
                length="0",
            ),
            403,
        ),
        (
            "unknown_path",
            request_bytes("POST", "/native_admin", f"127.0.0.1:{port}", length="0"),
            404,
        ),
        (
            "body_oversize",
            request_bytes("POST", "/mcp", f"127.0.0.1:{port}", length="131073"),
            413,
        ),
        (
            "chunked_body",
            request_bytes(
                "POST",
                "/mcp",
                f"127.0.0.1:{port}",
                extra="Transfer-Encoding: chunked",
            ),
            411,
        ),
        (
            "duplicate_host",
            request_bytes(
                "POST",
                "/mcp",
                f"127.0.0.1:{port}",
                length="0",
                extra="Host: 127.0.0.1:38765",
            ),
            400,
        ),
        (
            "duplicate_origin",
            request_bytes(
                "POST",
                "/mcp",
                f"127.0.0.1:{port}",
                origin=f"http://127.0.0.1:{port}",
                length="0",
                extra="Origin: http://127.0.0.1:38765",
            ),
            400,
        ),
        (
            "giant_header",
            request_bytes(
                "POST",
                "/mcp",
                f"127.0.0.1:{port}",
                length="0",
                extra="X-Flood: " + "z" * 8500,
            ),
            400,
        ),
    )
    names = []
    for name, raw, expected in cases:
        status, output = raw_response(port, raw)
        # Duplicate/overlarge headers can be rejected by Ktor's HTTP parser
        # before the application guard runs; a 400/431 still proves denial.
        parser_denials = {"duplicate_host", "duplicate_origin", "giant_header"}
        if status != expected or (
            name not in parser_denials and "NATIVE_" not in output
        ):
            raise AssertionError(
                f"Native HTTP {name} guard failed: actual status={status}, expected={expected}"
            )
        names.append(name)
    return {"status": "pass", "guard_denials": names, "http_cases": len(names)}


def main() -> int:
    if not BIN.is_file() or not os.access(BIN, os.X_OK):
        raise RuntimeError(
            "Build Native JVM installDist before running N0.b HTTP guard"
        )
    port = unused_port()
    proc = subprocess.Popen(
        [str(BIN), str(port)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for attempt in range(80):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                if proc.poll() is not None:
                    raise RuntimeError("Kotlin HTTP test listener exited")
                time.sleep(0.1)
        else:
            raise RuntimeError("Kotlin HTTP test listener never became ready")
        result = check_denials(port)
        result["transport"] = "real Kotlin SDK on 127.0.0.1 only"
        result["physical_device_used"] = False
        print(json.dumps(result, sort_keys=True))
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
