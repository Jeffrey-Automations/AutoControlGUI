"""Quick Connect starts, stops and disconnects without holding the GUI thread.

Stopping the host joins its threads and closing a viewer joins its receive
thread, up to 2 s each; Quick Connect did both in the button slot, and taking
a slot for a new connect closed the old session there too. The registry can
now free a slot at once and hand back the blocking shutdown
(:meth:`registry.detach`), which Quick Connect runs on a worker.
"""
import os
import threading
import time

import pytest

from je_auto_control.utils.remote_desktop.registry import SLOT_HOST, SLOT_VIEWER, registry


class _Blocking:
    """A host / viewer whose shutdown waits for ``release`` and records the thread it ran on."""

    is_running = True
    port = 5555
    connected_clients = 0
    host_id = "123456789"
    connected = True

    def __init__(self):
        self.release, self.entered = threading.Event(), threading.Event()
        self.shut_on = []

    def _shut(self, timeout=2.0):
        self.shut_on.append(threading.get_ident())
        self.entered.set()
        assert self.release.wait(10.0)

    stop = disconnect = _shut


@pytest.fixture(autouse=True)
def empty_slots():
    for slot in (SLOT_HOST, SLOT_VIEWER):
        close = registry.detach(slot, "test")
        if close is not None:
            close()
    yield
    for slot in (SLOT_HOST, SLOT_VIEWER):
        close = registry.detach(slot, "test")
        if close is not None:
            close()


def test_detach_frees_the_slot_at_once_and_returns_the_shutdown():
    told, resource = [], _Blocking()
    resource.release.set()
    registry.adopt(SLOT_VIEWER, resource, "panel", lambda slot, by: told.append((slot, by)))
    close = registry.detach(SLOT_VIEWER, "other")
    assert registry.owned(SLOT_VIEWER, "panel") is None          # free before anything was closed
    assert resource.shut_on == [] and told == []
    close()
    assert len(resource.shut_on) == 1
    assert told == [(SLOT_VIEWER, "other")]                      # the displaced owner is told when it runs


def test_detach_only_own_leaves_someone_elses_session_and_an_empty_slot_gives_nothing():
    resource = _Blocking()
    registry.adopt(SLOT_VIEWER, resource, "panel")
    assert registry.detach(SLOT_VIEWER, "other", only_own=True) is None
    assert registry.owned(SLOT_VIEWER, "panel") is resource
    resource.release.set()
    registry.detach(SLOT_VIEWER, "panel", only_own=True)()
    assert registry.detach(SLOT_VIEWER, "panel") is None


@pytest.fixture
def screen(monkeypatch, tmp_path):
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    try:
        from je_auto_control.gui.remote_desktop import connection_screen
    except ImportError:
        pytest.skip("the remote desktop GUI needs the webrtc extra")
    from je_auto_control.utils.remote_desktop.address_book import AddressBook
    monkeypatch.setattr(connection_screen, "default_address_book", lambda: AddressBook(tmp_path / "book.json"))
    view = connection_screen.QuickConnectScreen()
    view._refresh_timer.stop()
    yield view
    view.deleteLater()


def test_stopping_the_host_returns_at_once_and_says_stopping(screen):
    from headless._qt_settle import settle_op
    from je_auto_control.gui.remote_desktop._helpers import _t
    host = _Blocking()
    registry.adopt(SLOT_HOST, host, "script")
    gui = threading.get_ident()
    started = time.monotonic()
    screen._stop_hosting()
    assert time.monotonic() - started < 0.5                       # the 2 s join is not on this thread
    assert host.entered.wait(10.0)
    assert screen._host_badge.text() == _t("gui_op_stopping")
    host.release.set()
    assert settle_op(screen._host_op)
    assert registry.host is None
    assert host.shut_on and host.shut_on[0] != gui
    assert screen._host_badge.text() == _t("rd_quick_not_hosting")


def test_disconnect_frees_the_session_at_once_and_closes_it_on_a_worker(screen):
    from headless._qt_settle import pump_until
    viewer = _Blocking()
    registry.adopt(SLOT_VIEWER, viewer, screen._owner)
    gui = threading.get_ident()
    started = time.monotonic()
    screen._disconnect()
    assert time.monotonic() - started < 0.5
    assert registry.owned(SLOT_VIEWER, screen._owner) is None   # free for the next connect already
    assert viewer.entered.wait(10.0)
    assert viewer.shut_on[0] != gui
    viewer.release.set()
    assert pump_until(lambda: screen._stops.pending == 0)


def test_a_new_connect_closes_the_old_session_on_its_worker_first(monkeypatch):
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QWidget
    QApplication.instance() or QApplication([])
    from je_auto_control.gui.remote_desktop._connect_task import connect_viewer
    from headless._qt_settle import pump_until
    order, done = [], threading.Event()

    class _Viewer:
        def connect(self, timeout):
            order.append(("connect", threading.get_ident()))

        def disconnect(self, timeout=2.0):
            pass

    owner = QWidget()
    try:
        def connected(viewer):
            done.set()

        handle = connect_viewer(owner, _Viewer(), on_connected=connected, on_failed=lambda error: None,
                                before=lambda: order.append(("close old", threading.get_ident())))
        assert handle is not None
        assert pump_until(done.is_set)
        assert [step for step, _thread in order] == ["close old", "connect"]
        assert order[0][1] == order[1][1] != threading.get_ident()
    finally:
        owner.deleteLater()


def test_the_viewer_panels_disconnect_closes_on_a_worker_too(monkeypatch):
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    try:
        from je_auto_control.gui.remote_desktop import viewer_panel
    except ImportError:
        pytest.skip("the remote desktop GUI needs the webrtc extra")
    from headless._qt_settle import pump_until
    monkeypatch.setattr(viewer_panel, "is_audio_backend_available", lambda: False)
    panel = viewer_panel._ViewerPanel()
    viewer = _Blocking()
    try:
        registry.adopt(SLOT_VIEWER, viewer, panel._owner)
        gui = threading.get_ident()
        started = time.monotonic()
        panel._disconnect()
        assert time.monotonic() - started < 0.5
        assert registry.owned(SLOT_VIEWER, panel._owner) is None
        assert viewer.entered.wait(10.0)
        assert viewer.shut_on[0] != gui
        viewer.release.set()
        assert pump_until(lambda: panel._stops.pending == 0)
    finally:
        viewer.release.set()
        panel.deleteLater()
