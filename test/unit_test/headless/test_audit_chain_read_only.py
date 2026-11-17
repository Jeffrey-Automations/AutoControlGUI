"""The diagnosis verifies the audit chain without creating, migrating or writing the log.

``ac_diagnose`` is annotated read-only, but its audit check opened the default
log through ``AuditLog``, which made ``~/.je_auto_control``, created the
SQLite schema and ran the one-off chain backfill on a machine that had none.
"""
import hashlib
import os
import sqlite3
import subprocess
import sys

import pytest

from je_auto_control.utils.diagnostics import diagnostics
from je_auto_control.utils.remote_desktop import audit_log as audit_module
from je_auto_control.utils.remote_desktop.audit_log import (
    AuditLog, AuditLogError, verify_audit_chain_read_only,
)


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def chained(tmp_path):
    path = tmp_path / "audit.db"
    log = AuditLog(path)
    for index in range(3):
        log.log("auth_ok", host_id="h", viewer_id=f"v{index}")
    log.close()
    return path


def test_a_missing_log_is_nothing_to_verify_and_is_not_created(tmp_path):
    path = tmp_path / "nested" / "audit.db"
    assert verify_audit_chain_read_only(path) is None
    assert not path.parent.exists()


def test_an_intact_chain_verifies_and_the_file_is_untouched(chained):
    before = _digest(chained)
    result = verify_audit_chain_read_only(chained)
    assert (result.ok, result.total_rows) == (True, 3)
    assert _digest(chained) == before


def test_a_tampered_row_is_reported_as_the_writable_open_reports_it(chained):
    connection = sqlite3.connect(chained)
    connection.execute("UPDATE events SET detail = 'forged' WHERE id = 2")
    connection.commit()
    connection.close()
    result = verify_audit_chain_read_only(chained)
    assert (result.ok, result.broken_at_id, result.total_rows) == (False, 2, 3)
    log = AuditLog(chained)
    try:
        assert log.verify_chain() == result
    finally:
        log.close()


def test_a_log_from_before_the_chain_is_not_backfilled(tmp_path):
    path = tmp_path / "audit.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, ts TEXT, event_type TEXT,"
                       " host_id TEXT, viewer_id TEXT, detail TEXT)")
    connection.execute("INSERT INTO events (ts, event_type) VALUES ('t', 'auth_ok')")
    connection.commit()
    connection.close()
    before = _digest(path)
    assert verify_audit_chain_read_only(path) is None
    assert _digest(path) == before


def test_a_file_sqlite_cannot_read_is_an_audit_log_error(tmp_path):
    path = tmp_path / "audit.db"
    path.write_bytes(b"not a database" * 100)
    with pytest.raises(AuditLogError):
        verify_audit_chain_read_only(path)


def test_the_open_default_log_is_asked_directly(monkeypatch, chained):
    log = AuditLog(chained)
    monkeypatch.setattr(audit_module, "_default_audit_log", log)
    monkeypatch.setattr(audit_module, "default_audit_log_path", lambda: chained)
    try:
        assert verify_audit_chain_read_only().total_rows == 3
    finally:
        log.close()


def test_the_diagnostic_check_reports_no_log_without_making_one(monkeypatch, tmp_path):
    path = tmp_path / "home" / ".je_auto_control" / "audit.db"
    monkeypatch.setattr(audit_module, "_default_audit_log", None)
    monkeypatch.setattr(audit_module, "default_audit_log_path", lambda: path)
    check = diagnostics._check_audit_chain()
    assert (check.ok, check.severity) == (True, "info") and "does not create" in check.detail
    assert not (tmp_path / "home").exists()


def test_ac_diagnose_leaves_no_audit_database_in_a_fresh_home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home),
           "JE_AUTOCONTROL_LOG_FILE": str(tmp_path / "log" / "run.log")}
    code = ("from je_auto_control.utils.mcp_server.tools._diagnostics import _diagnose\n"
            "report = _diagnose()\n"
            "print([c['detail'] for c in report['checks'] if c['name'] == 'audit_chain'][0])\n")
    done = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                          timeout=240, check=False)
    assert done.returncode == 0, done.stderr[-2000:]
    assert "does not create" in done.stdout
    assert not (home / ".je_auto_control").exists()
