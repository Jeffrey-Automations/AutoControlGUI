"""Older tabs' slow calls (key derivation, file reads, chain checks) no longer hold the GUI thread.

Offscreen Qt against fakes: each backend call is replaced by one that waits on
a gate, so the test sees the slot return first, the tab report itself busy,
and the outcome arrive later on the GUI thread. ``dispose()`` while the call
is out drops its outcome.
"""
import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

from headless._qt_settle import pump_until  # noqa: E402
from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper  # noqa: E402

_WAIT = 10.0


def _t(key: str) -> str:
    return language_wrapper.translate(key, key)


class _Gate:
    """A backend call that blocks until released and remembers where it ran."""

    def __init__(self, result=None, error=None) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.threads: list = []
        self.result = result
        self.error = error

    def __call__(self, *args, **kwargs):
        self.threads.append(threading.get_ident())
        self.entered.set()
        self.release.wait(_WAIT)
        if self.error is not None:
            raise self.error
        return self.result

    def off_gui_thread(self) -> bool:
        return bool(self.threads) and all(ident != threading.get_ident() for ident in self.threads)


@pytest.fixture
def boxes(monkeypatch):
    QApplication.instance() or QApplication([])
    shown = []
    for name in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, name, lambda *args: shown.append(args[-1]))
    # No real dialog ever opens: a test that needs a path patches the one it uses.
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: ("", ""))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: ("", ""))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: "")
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    return shown


def _returns_at_once(slot) -> None:
    started = time.monotonic()
    slot()
    assert time.monotonic() - started < 5.0, "the slot held the GUI thread"


# --- secrets vault ------------------------------------------------------------------------------------------

class _Vault:
    """A locked vault whose unlock (the 600k-iteration key derivation) is a gate."""

    def __init__(self, gate) -> None:
        self.is_initialized = True
        self.is_unlocked = False
        self._gate = gate

    def unlock(self, passphrase):
        self._gate(passphrase)
        self.is_unlocked = True
        return True

    def lock(self):
        self.is_unlocked = False

    def list_names(self):
        return ["db_password"]


def test_unlocking_the_vault_runs_off_the_gui_thread(boxes, monkeypatch):
    from je_auto_control.gui import secrets_tab as module
    gate = _Gate()
    monkeypatch.setattr(module, "default_secret_manager", _Vault(gate))
    tab = module.SecretsTab()
    tab._passphrase.setText("correct horse")
    _returns_at_once(tab._on_unlock)
    assert gate.entered.wait(_WAIT)
    assert tab._status_label.text() == _t("task_running")
    tab._on_lock()                                  # one vault command at a time
    assert tab._status_label.text() == _t("task_busy")
    gate.release.set()
    assert pump_until(lambda: not tab._runs.running)
    assert gate.off_gui_thread()
    assert [tab._list.item(row).text() for row in range(tab._list.count())] == ["db_password"]
    assert tab._status_label.text() == _t("secret_status_unlocked")
    assert boxes == []
    tab.dispose()
    tab.deleteLater()


def test_disposing_the_secrets_tab_drops_an_unlock_still_out(boxes, monkeypatch):
    from je_auto_control.gui import secrets_tab as module
    gate = _Gate()
    monkeypatch.setattr(module, "default_secret_manager", _Vault(gate))
    tab = module.SecretsTab()
    tab._passphrase.setText("correct horse")
    tab._on_unlock()
    assert gate.entered.wait(_WAIT)
    shown = []
    tab._runs.result.connect(shown.append)
    tab.dispose()
    gate.release.set()
    pump_until(lambda: False, timeout=0.5)
    assert shown == [] and tab._list.count() == 0
    tab.deleteLater()


# --- REST tab: configuration bundle -------------------------------------------------------------------------

def _rest_tab(monkeypatch):
    from je_auto_control.gui import rest_api_tab as module
    registry = type("R", (), {"status": staticmethod(lambda: {"running": False}), "stop": staticmethod(
        lambda: None)})
    monkeypatch.setattr(module, "rest_api_registry", registry)
    return module, module.RestApiTab()


def test_exporting_the_configuration_runs_off_the_gui_thread(boxes, monkeypatch, tmp_path):
    module, tab = _rest_tab(monkeypatch)
    gate = _Gate(result={"files": {"a.json": "{}"}})
    target = tmp_path / "bundle.json"
    monkeypatch.setattr(module, "export_config_bundle", gate)
    monkeypatch.setattr(module.QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    monkeypatch.setattr(module.QFileDialog, "getOpenFileName", lambda *args: (str(target), ""))
    _returns_at_once(tab._on_config_export)
    assert gate.entered.wait(_WAIT)
    tab._on_config_import()                         # one bundle operation at a time
    assert tab._status_label.text() == _t("task_busy")
    gate.release.set()
    assert pump_until(lambda: not tab._config_task.running)
    assert gate.off_gui_thread() and target.is_file()
    assert boxes == [_t("rest_config_export_done").format(count=1, path=str(target))]
    tab.dispose()
    tab.deleteLater()


def test_importing_the_configuration_reads_and_writes_off_the_gui_thread(boxes, monkeypatch, tmp_path):
    import json
    module, tab = _rest_tab(monkeypatch)
    source = tmp_path / "bundle.json"
    source.write_text(json.dumps({"files": {}}), encoding="utf-8")
    report = type("Report", (), {"written": ["a"], "skipped": []})()
    gate = _Gate(result=report)
    asked = []
    monkeypatch.setattr(module, "import_config_bundle", gate)
    monkeypatch.setattr(module.QFileDialog, "getOpenFileName", lambda *args: (str(source), ""))
    monkeypatch.setattr(module.QMessageBox, "question", lambda *args: asked.append(args[-1]) or
                        QMessageBox.StandardButton.Yes)
    _returns_at_once(tab._on_config_import)
    assert pump_until(gate.entered.is_set)          # read, confirmed, then written on a worker
    assert asked == [_t("rest_config_import_confirm")]
    gate.release.set()
    assert pump_until(lambda: not tab._config_task.running)
    assert gate.off_gui_thread()
    assert boxes == [_t("rest_config_import_done").format(written=1, skipped=0)]
    tab.dispose()
    tab.deleteLater()


def test_a_configuration_file_that_cannot_be_read_is_reported(boxes, monkeypatch, tmp_path):
    module, tab = _rest_tab(monkeypatch)
    source = tmp_path / "broken.json"
    source.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(module.QFileDialog, "getOpenFileName", lambda *args: (str(source), ""))
    monkeypatch.setattr(module.QMessageBox, "question", lambda *args: pytest.fail("nothing to confirm"))
    tab._on_config_import()
    assert pump_until(lambda: not tab._config_task.running)
    assert len(boxes) == 1 and "Expecting" in boxes[0]
    tab.dispose()
    tab.deleteLater()


# --- audit log ----------------------------------------------------------------------------------------------

class _Log:
    """An audit log whose chain check is a gate."""

    def __init__(self, gate) -> None:
        self.verify_chain = gate
        self.queried = []

    def query(self, **kwargs):
        self.queried.append((kwargs, threading.get_ident()))
        return [{"ts": "", "event_type": "usb_close", "host_id": "h", "viewer_id": "", "detail": "d"}]

    def clear(self):
        return 3


def test_the_audit_log_is_read_and_verified_off_the_gui_thread(boxes, monkeypatch):
    from types import SimpleNamespace
    from je_auto_control.gui import audit_log_tab as module
    gate = _Gate(result=SimpleNamespace(ok=True, total_rows=1, broken_at_id=None))
    log = _Log(gate)
    monkeypatch.setattr(module, "default_audit_log", lambda: log)
    tab = module.AuditLogTab()
    assert pump_until(lambda: not tab._runs.running)
    assert tab._table.rowCount() == 1
    assert all(ident != threading.get_ident() for _kwargs, ident in log.queried)
    _returns_at_once(tab._verify)
    assert gate.entered.wait(_WAIT)
    assert tab._verify_status.text() == _t("task_running")
    tab._refresh()                                  # one log operation at a time
    assert tab._verify_status.text() == _t("task_busy")
    gate.release.set()
    assert pump_until(lambda: not tab._runs.running)
    assert gate.off_gui_thread()
    assert tab._verify_status.text() == _t("audit_verify_ok").format(total=1)
    tab.dispose()
    tab.deleteLater()


def test_clearing_the_audit_log_runs_off_the_gui_thread_then_rereads_it(boxes, monkeypatch):
    from je_auto_control.gui import audit_log_tab as module
    log = _Log(_Gate())
    monkeypatch.setattr(module, "default_audit_log", lambda: log)
    monkeypatch.setattr(module.QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    tab = module.AuditLogTab()
    assert pump_until(lambda: not tab._runs.running)
    reads = len(log.queried)
    tab._clear()
    assert pump_until(lambda: len(log.queried) > reads and not tab._runs.running)
    assert tab._verify_status.text() == _t("audit_clear_done").format(count=3)
    tab.dispose()
    tab.deleteLater()
