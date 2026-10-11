import json

import pytest

from android_mcp_host.cli import main


def test_doctor_is_successful_without_device_or_adb(capsys, monkeypatch):
    monkeypatch.setenv("PATH", "")
    result = main(["doctor"])
    status = json.loads(capsys.readouterr().out)
    assert result == 0
    assert status["schema_version"] == 1
    assert status["runtime"] == "host"


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "::1"])
def test_remote_bind_rejected(host):
    with pytest.raises(SystemExit) as error:
        main(["serve", "--host", host])
    assert error.value.code == 2


@pytest.mark.parametrize("port", ["0", "65536"])
def test_invalid_port_rejected(port):
    with pytest.raises(SystemExit) as error:
        main(["serve", "--port", port])
    assert error.value.code == 2
