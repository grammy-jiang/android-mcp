import pytest

from android_mcp_host.security.identity import fingerprint

BASE = {
    "device_id": "ABC-99",
    "kind": "install_apk",
    "argv_suffix": ("install", "-r", "/tmp/a.apk"),
}


def test_fingerprint_is_deterministic_and_binds_all_arguments():
    result = fingerprint(**BASE, artifact_sha256="a" * 64)
    assert len(result) == 64
    assert result == fingerprint(**BASE, artifact_sha256="a" * 64)
    for changes in (
        {"device_id": "OTHER"},
        {"kind": "instrument_test"},
        {"argv_suffix": ("install", "-t", "/tmp/a.apk")},
        {"artifact_sha256": "b" * 64},
        {"artifact_sha256": None},
    ):
        override = BASE | changes
        if "artifact_sha256" not in changes:
            override["artifact_sha256"] = "a" * 64
        assert fingerprint(**override) != result


@pytest.mark.parametrize("device", ["", "-invalid", "-s ABC", "a\nb", 22, "X" * 200])
def test_invalid_serial(device):
    with pytest.raises(ValueError):
        fingerprint(**(BASE | {"device_id": device}))


@pytest.mark.parametrize("suffix", [[], (), ("valid", ""), ("x\x00",), [42], "bad", ("x" * 8193,)])
def test_invalid_argv(suffix):
    with pytest.raises(ValueError):
        fingerprint(**(BASE | {"argv_suffix": suffix}))


@pytest.mark.parametrize("digest", ["not-a-digest", "A" * 64, "0" * 65, 8])
def test_invalid_artifact_digest(digest):
    with pytest.raises(ValueError):
        fingerprint(**BASE, artifact_sha256=digest)


def test_invalid_action_kind():
    for value in ("", "t" * 65, "点击", None):
        with pytest.raises(ValueError):
            fingerprint(**(BASE | {"kind": value}))
