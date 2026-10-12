from pathlib import Path

import pytest

from android_mcp_host.security.store import StateStore


@pytest.fixture
def secure_dir(tmp_path: Path) -> Path:
    path = tmp_path / "secure"
    path.mkdir(mode=0o700)
    return path


@pytest.fixture
def store(secure_dir: Path) -> StateStore:
    return StateStore(secure_dir / "state.sqlite3")
