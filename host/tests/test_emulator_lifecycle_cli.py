"""Production H3.c composition exposes only plan/status; fake backend never configured."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from test_avd_provisioning import ABI, LICENSE, OWNER, SOURCE, SYSTEM, provider

from android_mcp_host import cli
from android_mcp_host.durable_jobs import DurableJobStore
from android_mcp_host.emulator_lifecycle import EmulatorLifecycle


def make_flags(tmp_path: Path) -> list[str]:
    return [
        "serve",
        "--emulator-lifecycle-plan",
        "--avd-provision",
        "--avd-provision-root",
        str(tmp_path / "owned-avds"),
        "--avd-sdk-root",
        str(tmp_path / "synthetic-sdk"),
        "--avd-owner",
        OWNER,
        "--avd-api",
        "36",
        "--avd-abi",
        ABI,
        "--avd-image-sha256",
        hashlib.sha256(SOURCE).hexdigest(),
        "--avd-system-image-sha256",
        hashlib.sha256(SYSTEM).hexdigest(),
        "--avd-license-sha256",
        hashlib.sha256(LICENSE).hexdigest(),
        "--durable-job-status",
        "--job-root",
        str(tmp_path / "jobs"),
        "--job-owner",
        OWNER,
    ]


def test_opt_in_cli_has_no_real_backend_even_with_all_pins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class DummyServer:
        def run(self, **kwargs: Any) -> None:
            assert kwargs == {"transport": "http", "host": "127.0.0.1", "port": 8765}

    with monkeypatch.context() as patch:
        patch.setattr(cli.platform, "system", lambda: "Linux")
        patch.setattr(cli, "create_server", lambda **kwargs: calls.append(kwargs) or DummyServer())
        assert cli.main(make_flags(tmp_path)) == 0
    assert len(calls) == 1
    controller = calls[0]["emulator_lifecycle"]
    assert isinstance(controller, EmulatorLifecycle)
    assert controller._backend is None
    assert controller._owner == OWNER
    assert not (tmp_path / "owned-avds").exists()
    assert (tmp_path / "jobs").exists()


def test_owner_mismatch_rejected_before_any_process_spawn(
    tmp_path: Path,
) -> None:
    target = provider(tmp_path)
    ledger = DurableJobStore(tmp_path / "jobs")
    with pytest.raises(ValueError, match="lifecycle owner"):
        EmulatorLifecycle(target, ledger, owner="a-different-owner")
    assert ledger.list_status(OWNER) == []


def test_cli_rejects_cross_owner_even_when_all_root_pins_are_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = make_flags(tmp_path)
    args[args.index("--job-owner") + 1] = "foreign-owner"
    with monkeypatch.context() as patch:
        patch.setattr(cli.platform, "system", lambda: "Linux")
        with pytest.raises(SystemExit) as denied:
            cli.main(args)
    assert denied.value.code == 2
    assert not (tmp_path / "jobs").exists()
    assert not (tmp_path / "owned-avds").exists()
