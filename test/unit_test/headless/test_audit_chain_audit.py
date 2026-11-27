"""Audit-chain tampering the chain used to accept (2026-09-24 audit).

Opening the log re-hashed any row whose ``row_hash`` was NULL, so a forged
row with its hash cleared verified clean; ``verify_chain`` trusted the first
row's ``prev_hash``, so deleting the oldest rows went unnoticed; and
``clear()`` left no trace. Pruning must still verify.
"""
import sqlite3

import pytest

from je_auto_control.utils.remote_desktop import audit_log as audit_module
from je_auto_control.utils.remote_desktop.audit_log import AuditLog


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "audit.db"
    log = AuditLog(path)
    for index in range(4):
        log.log("auth_ok", host_id="h", viewer_id=f"v{index}", detail=f"d{index}")
    log.close()
    return path


def _tamper(path, sql):
    connection = sqlite3.connect(path)
    try:
        connection.execute(sql)
        connection.commit()
    finally:
        connection.close()


def _verify(path):
    log = AuditLog(path)
    try:
        return log.verify_chain()
    finally:
        log.close()


def test_a_forged_row_with_its_hash_cleared_is_caught(db):
    _tamper(db, "UPDATE events SET detail='forged', row_hash=NULL WHERE id >= 2")
    result = _verify(db)
    assert not result.ok
    assert result.broken_at_id == 2


def test_deleting_the_oldest_rows_is_caught(db):
    _tamper(db, "DELETE FROM events WHERE id = 1")
    assert not _verify(db).ok


def test_clear_leaves_a_verifiable_record(db):
    log = AuditLog(db)
    try:
        assert log.clear() == 4
        rows = log.query()
        assert [row["event_type"] for row in rows] == ["audit_log_cleared"]
        assert rows[0]["detail"] == "4 rows deleted"
        assert log.verify_chain().ok
    finally:
        log.close()


def test_pruning_still_verifies(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_module, "_MAX_ROWS", 6)
    monkeypatch.setattr(audit_module, "_PRUNE_TARGET", 3)
    log = AuditLog(tmp_path / "pruned.db")
    try:
        for index in range(10):
            log.log("event", detail=str(index))
        result = log.verify_chain()
        assert result.ok
        assert result.total_rows <= 6
    finally:
        log.close()


def test_a_log_pruned_before_the_anchor_existed_still_verifies(tmp_path):
    path = tmp_path / "old.db"
    log = AuditLog(path)
    try:
        for index in range(5):
            log.log("event", detail=str(index))
    finally:
        log.close()
    _tamper(path, "DELETE FROM events WHERE id <= 2")
    _tamper(path, "DROP TABLE chain_meta")
    _tamper(path, "PRAGMA user_version = 0")
    assert _verify(path).ok


def test_text_sqlite_cannot_store_is_still_logged(tmp_path):
    """A lone surrogate raised out of log() with the write transaction left open.

    A peer chooses ``viewer_id``, so a refused login could both skip its own
    audit row and lose the next one to the stuck transaction.
    """
    log = AuditLog(tmp_path / "surrogate.db")
    try:
        log.log("auth_fail", viewer_id="evil\ud800", detail="x\udfff")
        log.log("auth_ok", viewer_id="v")
        rows = log.query()
        assert [row["event_type"] for row in rows] == ["auth_ok", "auth_fail"]
        assert rows[1]["viewer_id"].startswith("evil")
        assert log.verify_chain().ok
    finally:
        log.close()


def test_another_process_cannot_prune_inside_a_prune(tmp_path, monkeypatch):
    """The anchor read before the other process pruned was stored after it, and verified as tampering."""
    monkeypatch.setattr(audit_module, "_MAX_ROWS", 6)
    monkeypatch.setattr(audit_module, "_PRUNE_TARGET", 3)
    path = tmp_path / "shared.db"
    log = AuditLog(path)
    other = AuditLog(path)
    other._conn.execute("PRAGMA busy_timeout = 0")
    set_anchor = log._set_anchor_locked

    def interleaved(value):
        other.log("event", detail="from the other process")
        set_anchor(value)

    monkeypatch.setattr(log, "_set_anchor_locked", interleaved)
    try:
        for index in range(7):
            log.log("event", detail=str(index))
        assert log.verify_chain().ok
    finally:
        other.close()
        log.close()


def test_a_clear_that_cannot_record_itself_clears_nothing(tmp_path, monkeypatch):
    """The rows used to go even when the event saying so could not be written."""
    log = AuditLog(tmp_path / "clear.db")
    try:
        log.log("auth_ok", viewer_id="v")

        def refuse(*_args, **_kwargs):
            raise sqlite3.OperationalError("database is locked")

        with monkeypatch.context() as patch:
            patch.setattr(log, "_insert_locked", refuse, raising=False)
            patch.setattr(log, "log", refuse)
            with pytest.raises((sqlite3.Error, audit_module.AuditLogError)):
                log.clear()
        assert [row["event_type"] for row in log.query()] == ["auth_ok"]
        assert log.verify_chain().ok
    finally:
        log.close()
