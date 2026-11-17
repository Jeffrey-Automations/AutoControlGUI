"""The GUI collects cyclic garbage on its own thread, from a timer, while automatic collection is off (offscreen Qt)."""
import gc
import os
import sys
import threading
import weakref

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtWidgets import QApplication  # noqa: E402

from headless._qt_settle import pump_until  # noqa: E402
from je_auto_control.gui import _gui_thread_gc  # noqa: E402
from je_auto_control.gui._gui_thread_gc import GuiThreadCollector  # noqa: E402


class _Node:
    """A cycle member the collector has to free, observable through a weak reference."""

    def __init__(self) -> None:
        self.me = self


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def collector_state():
    """Each test sets the collector state it needs; the one found is restored afterwards."""
    enabled, threshold = gc.isenabled(), gc.get_threshold()
    made = []
    yield made
    for collector in made:
        collector.stop()
        collector.deleteLater()
    gc.set_threshold(*threshold)
    (gc.enable if enabled else gc.disable)()


def _make(made, *args, **kwargs):
    collector = GuiThreadCollector(*args, **kwargs)
    made.append(collector)
    return collector


@pytest.mark.parametrize("was_enabled", [True, False])
def test_automatic_collection_is_off_while_it_runs_and_given_back_as_found(qapp, collector_state, was_enabled):
    (gc.enable if was_enabled else gc.disable)()
    collector = _make(collector_state, qapp)
    assert not gc.isenabled()
    collector.stop()
    assert gc.isenabled() is was_enabled
    collector.stop()                    # idempotent: a second stop changes nothing
    assert gc.isenabled() is was_enabled


def test_nothing_is_collected_below_the_first_threshold(qapp, collector_state, monkeypatch):
    collector = _make(collector_state, qapp)
    calls = []
    monkeypatch.setattr(gc, "collect", lambda generation=2: calls.append(generation) or 0)
    monkeypatch.setattr(gc, "get_count", lambda: (5, 0, 0))
    assert collector.check() is None
    assert calls == []


def test_generations_follow_the_interpreters_thresholds(qapp, collector_state, monkeypatch):
    gc.set_threshold(700, 10, 10)
    collector = _make(collector_state, qapp)
    calls = []
    monkeypatch.setattr(gc, "collect", lambda generation=2: calls.append(generation) or 0)
    monkeypatch.setattr(gc, "get_count", lambda: (701, 0, 0))
    for _ in range(100):
        collector.check()
    assert calls.count(2) == 1
    assert calls[99] == 2          # every 10 * 10 young collections
    assert calls.count(1) == 9                             # every 10th, the 100th being full
    assert calls.count(0) == 90
    assert collector.collections == [90, 9, 1]


def test_a_first_threshold_of_zero_stays_switched_off(qapp, collector_state, monkeypatch):
    gc.set_threshold(0)
    collector = _make(collector_state, qapp)
    monkeypatch.setattr(gc, "get_count", lambda: (10 ** 6, 0, 0))
    assert collector.check() is None


def test_cyclic_garbage_is_freed_by_the_timer_on_the_gui_thread(qapp, collector_state, monkeypatch):
    gc.set_threshold(100, 10, 10)
    threads = []
    real_collect = gc.collect

    def collect(generation=2):
        threads.append(threading.get_ident())
        return real_collect(generation)

    monkeypatch.setattr(gc, "collect", collect)
    collector = _make(collector_state, qapp, interval_ms=5)
    node = _Node()
    freed = weakref.ref(node)
    del node
    junk = [[index] for index in range(500)]           # past the first threshold
    del junk
    assert pump_until(lambda: freed() is None, timeout=5.0)
    assert collector.collections[0] >= 1
    assert set(threads) == {threading.get_ident()}


def test_start_autocontrol_gui_installs_it_and_stops_it_on_quit(qapp, collector_state, monkeypatch):
    from PySide6 import QtWidgets

    from je_auto_control.gui import main_window, theme
    import je_auto_control.gui as gui_package

    installed = []

    class _Recorded(GuiThreadCollector):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            installed.append(self)
            collector_state.append(self)

    class _Window:
        def show(self):
            return None

    monkeypatch.setattr(_gui_thread_gc, "GuiThreadCollector", _Recorded)
    class _ExistingApp:
        """``QApplication(argv)`` hands back the test's application; ``instance()`` still works."""

        def __new__(cls, _argv):
            return qapp

        instance = staticmethod(lambda: qapp)

    monkeypatch.setattr(QtWidgets, "QApplication", _ExistingApp)
    monkeypatch.setattr(main_window, "AutoControlGUIUI", _Window)
    monkeypatch.setattr(theme, "prepare_application", lambda app: None)
    monkeypatch.setattr(qapp, "exec", lambda: 0)
    gc.enable()
    with pytest.raises(SystemExit) as exited:
        gui_package.start_autocontrol_gui()
    assert exited.value.code == 0
    assert len(installed) == 1
    assert installed[0].parent() is qapp
    assert not gc.isenabled()
    qapp.aboutToQuit.emit()
    assert gc.isenabled()
    qapp.aboutToQuit.disconnect(installed[0].stop)


def test_the_top_level_package_still_imports_no_qt():
    import subprocess
    code = "import sys, je_auto_control; print(any('PySide6' in m for m in sys.modules))"
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,  # nosec B603  # reason: fixed argv
                          timeout=120, check=False)
    assert done.stdout.strip() == "False", done.stdout + done.stderr
