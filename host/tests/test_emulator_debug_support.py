"""H3.f synthetic signature, finite runner parsing and provenance denial cases."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from test_avd_provisioning import NAME
from test_emulator_debug_deployment import (
    ARTIFACT_OWNER,
    PACKAGE,
    fixture_apk,
    setup_deploy,
)

from android_mcp_host.avd_provision_support import root_key
from android_mcp_host.emulator_debug_support import (
    MAX_OUTPUT,
    SIGNATURE_MEMBER,
    check_install_receipt,
    fixture_mac,
    inspect_signed_fixture,
    parse_deploy_result,
    valid_digest,
    valid_package,
    verified_fake_target,
)
from android_mcp_host.private_artifact_store import PrivateArtifactStore


@pytest.mark.parametrize(
    "package",
    [
        "",
        "../path",
        "/etc/passwd",
        "-evil",
        "org.example",
        "org..example.debug",
        "org.example.123",
        "org.example.some package",
        "org.example.foo;pwd",
        "org.example.foo/bar",
        "org.example.foo\\path",
        "a" * 140,
        None,
        123,
    ],
)
def test_package_name_requires_exact_fully_qualified_ascii(package: Any) -> None:
    assert not valid_package(package)
    assert valid_package(PACKAGE)


@pytest.mark.parametrize("digest", ["", "a" * 63, "a" * 65, "Z" * 64, "g" * 64, None, 0])
def test_debug_archive_digest_strict_lowercase_hex(digest: Any) -> None:
    assert not valid_digest(digest)
    assert valid_digest("a" * 64)


@pytest.mark.parametrize(
    "response",
    [
        "",
        "not-json",
        "[]",
        "{}",
        "null",
        "X" * (MAX_OUTPUT + 1),
        '{"synthetic":false,"action":"install","avd":"x","package":"y","success":true}',
        '{"synthetic":true,"action":"install","avd":"x","package":"y","success":1}',
        '{"synthetic":true,"action":"launch","avd":"x","package":"y","success":true}',
        '{"synthetic":true,"action":"install","avd":"other","package":"y","success":true}',
        '{"synthetic":true,"action":"install","avd":"x","package":"other","success":true}',
        '{"synthetic":true,"action":"install","avd":"x","package":"y","success":true,"raw":"PRIVATE"}',
        123,
        None,
    ],
)
def test_runner_output_is_strict_synthetic_envelope(response: Any) -> None:
    assert parse_deploy_result(response, "install", "x", "y") is None


def test_synthetic_runner_result_true_false_and_unknown_action() -> None:
    good = json.dumps(
        {"synthetic": True, "action": "install", "avd": NAME, "package": PACKAGE, "success": True}
    )
    denied = json.dumps(
        {"synthetic": True, "action": "install", "avd": NAME, "package": PACKAGE, "success": False}
    )
    assert parse_deploy_result(good, "install", NAME, PACKAGE) is True
    assert parse_deploy_result(denied, "install", NAME, PACKAGE) is False
    assert parse_deploy_result(good, "connect-usb", NAME, PACKAGE) is None


def test_signed_fixture_has_no_claim_of_android_apk_verification(tmp_path: Path) -> None:
    deploy, live, jobs, artifacts, handle, lid, apk_handle, sha = setup_deploy(
        tmp_path,
        running=False,
    )
    try:
        secret = root_key(tmp_path / "owned-avds", create=False)
        assert isinstance(secret, bytes)
        fixture = artifacts.read(ARTIFACT_OWNER, apk_handle)
        result = inspect_signed_fixture(fixture, secret, PACKAGE, "arm64-v8a")
        assert result is not None
        assert result["signature_provenance"] == "synthetic_hmac_fixture_only"
        assert result["package_id"] == PACKAGE
        assert result["abi"] == "arm64-v8a"
        assert inspect_signed_fixture(fixture, b"incorrect owner", PACKAGE, "arm64-v8a") is None
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "invalid",
    [
        {"signed": False},
        {"package": "org.example.foreign.debug"},
        {"abi": "x86_64"},
    ],
)
def test_wrong_fixture_signature_package_or_abi_denied(
    tmp_path: Path,
    invalid: dict[str, Any],
) -> None:
    deploy, live, jobs, artifacts, handle, lid, apk_handle, sha = setup_deploy(
        tmp_path,
        running=False,
    )
    try:
        signed = fixture_apk(tmp_path, **invalid)
        secret = root_key(tmp_path / "owned-avds", create=False)
        assert secret is not None
        assert inspect_signed_fixture(signed, secret, PACKAGE, "arm64-v8a") is None
    finally:
        live.shutdown()


def test_altered_apk_members_fail_even_if_test_signature_is_reused(tmp_path: Path) -> None:
    deploy, live, jobs, artifacts, handle, lid, apk_handle, sha = setup_deploy(
        tmp_path,
        running=False,
    )
    try:
        original = artifacts.read(ARTIFACT_OWNER, apk_handle)
        with zipfile.ZipFile(io.BytesIO(original)) as read:
            members = {name: read.read(name) for name in read.namelist()}
        members["lib/arm64-v8a/libfixture.so"] = b"modified-unsafely"
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as write:
            for name, data in members.items():
                write.writestr(name, data)
        secret = root_key(tmp_path / "owned-avds", create=False)
        assert secret is not None
        assert inspect_signed_fixture(stream.getvalue(), secret, PACKAGE, "arm64-v8a") is None
    finally:
        live.shutdown()


def test_unknown_extra_apk_member_cannot_use_valid_synthetic_signature(tmp_path: Path) -> None:
    deploy, live, jobs, artifacts, handle, lid, apk_handle, sha = setup_deploy(
        tmp_path,
        running=False,
    )
    try:
        original = artifacts.read(ARTIFACT_OWNER, apk_handle)
        with zipfile.ZipFile(io.BytesIO(original)) as read:
            members = {name: read.read(name) for name in read.namelist()}
        members["unknown.sh"] = b"#!/bin/sh\n"
        extra = io.BytesIO()
        with zipfile.ZipFile(extra, "w") as write:
            for name, data in members.items():
                write.writestr(name, data)
        secret = root_key(tmp_path / "owned-avds", create=False)
        assert secret is not None
        assert inspect_signed_fixture(extra.getvalue(), secret, PACKAGE, "arm64-v8a") is None
    finally:
        live.shutdown()


def test_malformed_signature_member_is_rejected(tmp_path: Path) -> None:
    deploy, live, jobs, artifacts, handle, lid, apk_handle, sha = setup_deploy(
        tmp_path,
        running=False,
    )
    try:
        unsigned = fixture_apk(tmp_path, signed=False)
        with zipfile.ZipFile(io.BytesIO(unsigned)) as read:
            members = {name: read.read(name) for name in read.namelist()}
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as write:
            for name, content in members.items():
                write.writestr(name, content)
            write.writestr(SIGNATURE_MEMBER, b"not-hex-synthetic-signature")
        key = root_key(tmp_path / "owned-avds", create=False)
        assert key is not None
        assert inspect_signed_fixture(data.getvalue(), key, PACKAGE, "arm64-v8a") is None
    finally:
        live.shutdown()


def test_fixture_mac_is_order_independent_and_secret_bound() -> None:
    first = {"AndroidManifest.xml": b"a", "resources.arsc": b"b"}
    reverse = {"resources.arsc": b"b", "AndroidManifest.xml": b"a"}
    assert fixture_mac(first, b"owner-key") == fixture_mac(reverse, b"owner-key")
    assert fixture_mac(first, b"owner-key") != fixture_mac(first, b"different-key")
    assert fixture_mac(first, b"owner-key") != fixture_mac(
        {"AndroidManifest.xml": b"c"}, b"owner-key"
    )


def test_private_install_receipt_requires_ephemeral_owner_state(tmp_path: Path) -> None:
    artifacts = PrivateArtifactStore(tmp_path / "artifacts")
    owned = {
        "action": "install",
        "state": "synthetic_installed",
        "avd_handle": "mcpavd_" + "a" * 32,
        "apk_sha256": "b" * 64,
        "package_id": PACKAGE,
        "lifecycle_job_id": "job_" + "c" * 32,
        "synthetic_fixture_only": True,
    }
    raw = json.dumps(owned).encode()
    receipt = artifacts.put(ARTIFACT_OWNER, raw, mime_type="application/json")
    handle = receipt["handle"]
    state = (handle, "b" * 64, "job_" + "c" * 32)
    args = (
        artifacts,
        ARTIFACT_OWNER,
        state,
        handle,
        owned["avd_handle"],
        PACKAGE,
        owned["lifecycle_job_id"],
        owned["apk_sha256"],
    )
    assert check_install_receipt(*args) is True
    assert check_install_receipt(artifacts, ARTIFACT_OWNER, None, *args[3:]) is False
    assert check_install_receipt(artifacts, ARTIFACT_OWNER, state, "invalid", *args[4:]) is False
    assert (
        check_install_receipt(artifacts, ARTIFACT_OWNER, state, handle, "wrong", *args[5:]) is False
    )
    assert (
        check_install_receipt(
            artifacts,
            ARTIFACT_OWNER,
            state,
            handle,
            owned["avd_handle"],
            "org.example.foreign.app",
            *args[6:],
        )
        is False
    )
    assert artifacts.revoke(ARTIFACT_OWNER, handle) is True
    assert check_install_receipt(*args) is False


def test_synthetic_lifecycle_must_match_all_returned_identity(tmp_path: Path) -> None:
    deploy, live, jobs, artifacts, handle, lid, apk_handle, sha = setup_deploy(tmp_path)
    try:
        info = live.provisioner.verify_owned(NAME, handle)
        assert info is not None
        assert verified_fake_target(live, info, lid) is True
        assert verified_fake_target(live, info, "job_" + "z" * 32) is False

        class Forged:
            def run(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
                output = live.run(*args, **kwargs)
                output["handle"] = "mcpavd_" + "z" * 32
                return output

        assert verified_fake_target(Forged(), info, lid) is False  # type: ignore[arg-type]
    finally:
        live.shutdown()
