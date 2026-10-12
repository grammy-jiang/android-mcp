from contextlib import closing

import pytest

from android_mcp_host.security.audit import AuditError, AuditEvent, AuditJournal

EVENT = AuditEvent("begin", "ABC-1", "install_apk", "b" * 64, "authorized")


def test_journal_is_durable_and_chain_valid(store):
    first = AuditJournal(store, clock=lambda: 1000)
    assert first.append(EVENT) == 1
    assert first.append(AuditEvent("end", "ABC-1", "install_apk", "b" * 64, "ok")) == 2
    reopened = AuditJournal(store, clock=lambda: 1100)
    assert reopened.verify_chain()
    with closing(store._connect()) as conn, conn:
        entries = conn.execute("SELECT body FROM audit_events ORDER BY seq").fetchall()
    assert len(entries) == 2
    assert "approved-token" not in str(entries)


def test_detects_modified_entry_and_denies_new_write(store):
    journal = AuditJournal(store)
    journal.append(EVENT)
    with closing(store._connect()) as conn, conn:
        conn.execute("UPDATE audit_events SET body='tampered' WHERE seq=1")
    assert journal.verify_chain() is False
    with pytest.raises(AuditError, match="head"):
        journal.append(EVENT)


def test_detects_prior_chain_modification(store):
    journal = AuditJournal(store)
    journal.append(EVENT)
    journal.append(AuditEvent("end", "ABC-1", "install_apk", "b" * 64, "ok"))
    with closing(store._connect()) as conn, conn:
        conn.execute("UPDATE audit_events SET body='tampered' WHERE seq=1")
    assert journal.verify_chain() is False


def test_delete_detected_by_sequence_gap(store):
    journal = AuditJournal(store)
    journal.append(EVENT)
    journal.append(AuditEvent("end", "ABC-1", "install_apk", "b" * 64, "ok"))
    with closing(store._connect()) as conn, conn:
        conn.execute("DELETE FROM audit_events WHERE seq=1")
    assert journal.verify_chain() is False


def test_invalid_event_category_is_rejected(store):
    journal = AuditJournal(store)
    for event in (
        AuditEvent("root_shell", "ABC", "install_apk", "a" * 64, "ok"),
        AuditEvent("begin", "ABC", "install_apk", "a" * 64, "private_error"),
        AuditEvent("begin", "", "install_apk", "a" * 64, "ok"),
        AuditEvent("begin", "ABC", "install_apk", "short", "ok"),
    ):
        with pytest.raises(ValueError):
            journal.append(event)


def test_corrupt_sqlite_causes_audit_failure(store):
    journal = AuditJournal(store)
    with closing(store._connect()) as conn, conn:
        conn.execute("DROP TABLE audit_events")
    with pytest.raises(AuditError):
        journal.append(EVENT)
    with pytest.raises(AuditError):
        journal.verify_chain()
