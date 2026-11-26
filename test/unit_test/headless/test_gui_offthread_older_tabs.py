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

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

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
