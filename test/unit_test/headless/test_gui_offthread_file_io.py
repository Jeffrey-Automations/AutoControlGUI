"""The file reads and writes that follow a tab's file dialog no longer hold the GUI thread.

Offscreen Qt against fakes: every file dialog is faked, and the read or write
behind it waits on a gate, so the test sees the slot return first, the tab
report itself busy, and the outcome arrive later on the GUI thread.
``dispose()`` (or closing a dialog) while the call is out drops its outcome.
"""
import builtins
import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox  # noqa: E402

from headless._qt_settle import pump_until  # noqa: E402
from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper  # noqa: E402

_WAIT = 10.0


def _t(key: str) -> str:
    return language_wrapper.translate(key, key)


class _Gate:
    """A backend call that blocks until released, remembers where it ran, then delegates or answers."""

    def __init__(self, result=None, error=None, then=None) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.threads: list = []
        self.calls: list = []
        self.result = result
        self.error = error
        self.then = then

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        self.threads.append(threading.get_ident())
        self.entered.set()
        self.release.wait(_WAIT)
        if self.error is not None:
            raise self.error
        if self.then is not None:
            return self.then(*args, **kwargs)
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
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("", False))
    return shown


def _returns_at_once(slot, *args) -> None:
    started = time.monotonic()
    slot(*args)
    assert time.monotonic() - started < 5.0, "the slot held the GUI thread"


def _pick_open(monkeypatch, path) -> None:
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(path), ""))


def _pick_save(monkeypatch, path) -> None:
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(path), ""))


def _gated_open(monkeypatch, module) -> _Gate:
    """Gate the module's ``open``: the file is still really opened, once the gate is released."""
    gate = _Gate(then=builtins.open)
    monkeypatch.setattr(module, "open", gate, raising=False)
    return gate


# --- DAG editor ---------------------------------------------------------------------------------------------

def test_loading_a_dag_file_runs_off_the_gui_thread(boxes, monkeypatch, tmp_path):
    from je_auto_control.gui import dag_tab as module
    source = tmp_path / "dag.json"
    source.write_text('{"nodes": []}', encoding="utf-8")
    _pick_open(monkeypatch, source)
    gate = _gated_open(monkeypatch, module)
    tab = module.DagTab()
    _returns_at_once(tab._on_load)
    assert gate.entered.wait(_WAIT)
    assert tab._status_label.text() == _t("task_running")
    tab._on_load()                                  # one load at a time
    assert tab._status_label.text() == _t("task_busy")
    gate.release.set()
    assert pump_until(lambda: not tab._loading.running)
    assert gate.off_gui_thread() and len(gate.calls) == 1
    assert tab._editor.toPlainText() == '{"nodes": []}'
    tab.dispose()
    tab.deleteLater()


def test_a_dag_file_that_cannot_be_read_is_reported_in_the_tab(boxes, monkeypatch, tmp_path):
    from je_auto_control.gui import dag_tab as module
    _pick_open(monkeypatch, tmp_path / "missing.json")
    tab = module.DagTab()
    tab._editor.setPlainText("kept")
    tab._on_load()
    assert pump_until(lambda: not tab._loading.running)
    assert tab._status_label.text().startswith(_t("dag_error"))
    assert tab._editor.toPlainText() == "kept"
    tab.dispose()
    tab.deleteLater()


def test_disposing_the_dag_tab_drops_a_load_still_out(boxes, monkeypatch, tmp_path):
    from je_auto_control.gui import dag_tab as module
    source = tmp_path / "dag.json"
    source.write_text('{"nodes": []}', encoding="utf-8")
    _pick_open(monkeypatch, source)
    gate = _gated_open(monkeypatch, module)
    tab = module.DagTab()
    tab._on_load()
    assert gate.entered.wait(_WAIT)
    tab.dispose()
    gate.release.set()
    pump_until(lambda: False, timeout=0.5)
    assert tab._editor.toPlainText() == ""
    tab.deleteLater()
