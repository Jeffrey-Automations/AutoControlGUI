"""The Run History tab queries its SQLite store and decodes its preview off the GUI thread.

The tab queried the history every two seconds, and decoded the selected run's
screenshot on every refresh, resize and selection, all on the GUI thread.
Offscreen Qt against gated fakes; no real history store is touched.
"""
import os
import threading
import time
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from headless._qt_settle import pump_until  # noqa: E402
from je_auto_control.utils.run_history.history_store import RunRecord  # noqa: E402

_WAIT = 10.0


class _Gate:
    """A call that blocks until released and remembers where it ran."""

    def __init__(self, then) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.threads: list = []
        self.calls: list = []
        self.then = then

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        self.threads.append(threading.get_ident())
        self.entered.set()
        self.release.wait(_WAIT)
        return self.then(*args, **kwargs)

    def off_gui_thread(self) -> bool:
        return bool(self.threads) and all(ident != threading.get_ident() for ident in self.threads)


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _store(runs, **extra):
    return types.SimpleNamespace(list_runs=lambda **_kwargs: list(runs), **extra)


def _tab(monkeypatch, store):
    from je_auto_control.gui import run_history_tab as module
    monkeypatch.setattr(module, "default_history_store", store)
    started = time.monotonic()
    tab = module.RunHistoryTab()
    assert time.monotonic() - started < 5.0, "building the tab waited for the store"
    tab._timer.stop()
    return module, tab


def test_the_history_is_queried_off_the_gui_thread(app, monkeypatch):
    runs = [RunRecord(5, "manual", "x", "s.json", 1.0, 2.0, "ok", None)]
    gate = _Gate(lambda **kwargs: list(runs))
    _module, tab = _tab(monkeypatch, types.SimpleNamespace(list_runs=gate))
    assert gate.entered.wait(_WAIT)
    assert tab._table.rowCount() == 0
    tab._refresh()                                  # asked again while one is out: runs once it reports
    gate.release.set()
    assert pump_until(lambda: len(gate.calls) == 2 and not tab._queries.running)
    assert gate.off_gui_thread() and tab._table.rowCount() == 1
    tab.dispose()
    tab.deleteLater()


def test_an_answer_for_an_older_filter_is_not_shown(app, monkeypatch):
    calls = []
    gate = _Gate(lambda **kwargs: calls.append(kwargs["source_type"]) or (
        [] if kwargs["source_type"] else [RunRecord(1, "manual", "x", "s.json", 1.0, 2.0, "ok", None)]))
    _module, tab = _tab(monkeypatch, types.SimpleNamespace(list_runs=gate))
    assert gate.entered.wait(_WAIT)
    tab._filter.setCurrentIndex(1)                  # scheduler runs only
    gate.release.set()
    assert pump_until(lambda: len(calls) == 2 and not tab._queries.running)
    assert calls[1] is not None and tab._table.rowCount() == 0
    tab.dispose()
    tab.deleteLater()


def test_the_preview_is_decoded_off_the_gui_thread_once_per_screenshot(app, monkeypatch, tmp_path):
    shot = tmp_path / "shot.png"
    image = QImage(64, 48, QImage.Format.Format_RGB32)
    image.fill(0x336699)
    assert image.save(str(shot), "PNG")
    runs = [RunRecord(5, "manual", "x", "s.json", 1.0, 2.0, "ok", None, str(shot))]
    module, tab = _tab(monkeypatch, _store(runs))
    assert pump_until(lambda: tab._table.rowCount() == 1)
    decode = _Gate(module._decode_preview)
    monkeypatch.setattr(module, "_decode_preview", decode)
    started = time.monotonic()
    tab._table.selectRow(0)
    assert time.monotonic() - started < 5.0, "selecting a run waited for its screenshot"
    assert decode.entered.wait(_WAIT)
    decode.release.set()
    assert pump_until(lambda: tab._thumb_label.pixmap() is not None and not tab._thumb_label.pixmap().isNull())
    assert decode.off_gui_thread()
    tab.resize(900, 700)
    tab._refresh_preview()                          # the decoded copy is painted again, not re-read
    assert len(decode.calls) == 1
    tab.dispose()
    tab.deleteLater()


def test_clearing_the_history_runs_off_the_gui_thread(app, monkeypatch):
    runs = [RunRecord(5, "manual", "x", "s.json", 1.0, 2.0, "ok", None)]
    gate = _Gate(runs.clear)
    module, tab = _tab(monkeypatch, _store(runs, clear=gate))
    assert pump_until(lambda: tab._table.rowCount() == 1)
    monkeypatch.setattr(module.QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    started = time.monotonic()
    tab._on_clear()
    assert time.monotonic() - started < 5.0, "the slot held the GUI thread"
    assert gate.entered.wait(_WAIT)
    gate.release.set()
    assert pump_until(lambda: tab._table.rowCount() == 0)
    assert gate.off_gui_thread()
    tab.dispose()
    tab.deleteLater()


def test_disposing_the_history_tab_drops_a_query_still_out(app, monkeypatch):
    runs = [RunRecord(5, "manual", "x", "s.json", 1.0, 2.0, "ok", None)]
    gate = _Gate(lambda **kwargs: list(runs))
    _module, tab = _tab(monkeypatch, types.SimpleNamespace(list_runs=gate))
    assert gate.entered.wait(_WAIT)
    tab.dispose()
    gate.release.set()
    pump_until(lambda: False, timeout=0.5)
    assert tab._table.rowCount() == 0
    tab.deleteLater()
