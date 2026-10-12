import sqlite3
import stat

import pytest

from android_mcp_host.security.store import StateError, StateStore


def test_replay_protection_persists_across_instances(store):
    assert store.consume_grant("aa" * 16, "bb" * 32)
    separate = StateStore(store.path)
    assert not separate.consume_grant("aa" * 16, "bb" * 32)
    assert separate.consume_grant("cc" * 16, "bb" * 32)
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


def test_fencing_tokens_reject_stale_release_and_allow_acquire_after_expiry(secure_dir):
    now = [100.0]
    db = secure_dir / "state.db"
    first = StateStore(db, clock=lambda: now[0])
    second = StateStore(db, clock=lambda: now[0])
    lease = first.acquire("ABC", ttl_s=4)
    assert lease and lease.fence == 1
    assert first.is_current(lease)
    assert second.acquire("ABC") is None
    now[0] += 5
    assert not first.is_current(lease)
    next_lease = second.acquire("ABC", ttl_s=10)
    assert next_lease and next_lease.fence == 2
    assert next_lease.owner != lease.owner
    assert not first.release(lease)
    assert second.is_current(next_lease)
    assert second.release(next_lease)
    assert not second.release(next_lease)
    future = first.acquire("ABC")
    assert future and future.fence == 3


def test_different_device_leases_do_not_block_each_other(store):
    one = store.acquire("SERIAL-1")
    two = store.acquire("SERIAL-2")
    assert one and two
    assert one.owner != two.owner
    assert store.release(one)
    assert store.release(two)


def test_invalid_lease_input_is_rejected(store):
    with pytest.raises(ValueError):
        store.acquire("-s", ttl_s=100)
    for ttl in (0, -1, 301):
        with pytest.raises(ValueError):
            store.acquire("ABC", ttl_s=ttl)


def test_wall_clock_rollback_is_fail_closed(secure_dir):
    now = [300.0]
    s = StateStore(secure_dir / "state.db", clock=lambda: now[0])
    s.acquire("ABC")
    now[0] = 200.0
    with pytest.raises(StateError, match="clock"):
        s.acquire("XYZ")


def test_state_directory_must_be_private(tmp_path):
    public = tmp_path / "public"
    public.mkdir(mode=0o777)
    public.chmod(0o777)
    with pytest.raises(StateError, match="0700"):
        StateStore(public / "state.db")
    missing = tmp_path / "missing"
    with pytest.raises(StateError, match="already exist"):
        StateStore(missing / "state.db")


def test_state_symlinks_are_rejected(secure_dir, tmp_path):
    actual = secure_dir / "state.db"
    StateStore(actual)
    symlink = secure_dir / "linked.db"
    symlink.symlink_to(actual)
    with pytest.raises(StateError, match="symlink"):
        StateStore(symlink)
    linked_dir = tmp_path / "alias"
    linked_dir.symlink_to(secure_dir, target_is_directory=True)
    with pytest.raises(StateError, match="symlink"):
        StateStore(linked_dir / "state.db")


def test_wrong_permissions_on_existing_db_fail(secure_dir):
    database = secure_dir / "unsafe.db"
    database.write_bytes(b"not-a-database")
    database.chmod(0o644)
    with pytest.raises(StateError, match="0600"):
        StateStore(database)


def test_lease_fence_overflow_is_denied_without_mutating_epoch(store):
    from contextlib import closing

    with closing(store._connect()) as conn, conn:
        conn.execute(
            "INSERT INTO lease_epochs(device_id,last_fence) VALUES(?,?)", ("OVERFLOW", 2**62 - 1)
        )
    with pytest.raises(StateError, match="exhausted"):
        store.acquire("OVERFLOW")


def test_consumed_grant_database_error_does_not_authorize(store):
    from contextlib import closing

    with closing(store._connect()) as conn, conn:
        conn.execute("DROP TABLE consumed_grants")
    with pytest.raises(sqlite3.OperationalError):
        store.consume_grant("a" * 32, "b" * 64)


def test_state_directory_wrong_owner_is_rejected(secure_dir, monkeypatch):
    import android_mcp_host.security.store as module

    original_uid = module.os.getuid()
    monkeypatch.setattr(module.os, "getuid", lambda: original_uid + 1)
    with pytest.raises(StateError, match="owned"):
        module.StateStore(secure_dir / "state.db")
