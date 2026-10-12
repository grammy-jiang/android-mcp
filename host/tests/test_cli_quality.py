"""CLI compatibility and binding safety tests."""

from android_mcp_host import cli


def test_serving_only_starts_with_supported_host_and_valid_port(monkeypatch):
    calls = []

    class StubServer:
        def run(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(cli, "create_server", lambda: StubServer())
    monkeypatch.setattr(cli.platform, "system", lambda: "Linux")
    assert cli.main(["serve", "--port", "9625"]) == 0
    assert calls == [{"transport": "http", "host": "127.0.0.1", "port": 9625}]


def test_default_port_and_macos(monkeypatch):
    calls = []

    class StubServer:
        def run(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(cli, "create_server", lambda: StubServer())
    monkeypatch.setattr(cli.platform, "system", lambda: "Darwin")
    assert cli.main(["serve"]) == 0
    assert calls[0]["port"] == 8765


def test_unsupported_host_fails_before_constructing_service(monkeypatch):
    def never_start():
        raise AssertionError("must not start unsupported platform")

    monkeypatch.setattr(cli, "create_server", never_start)
    monkeypatch.setattr(cli.platform, "system", lambda: "Windows")
    import pytest

    with pytest.raises(SystemExit) as error:
        cli.main(["serve"])
    assert error.value.code == 2
