"""Remote view retirement with fake transports and offscreen Qt only."""
import gc
import threading
import weakref
from types import SimpleNamespace

import pytest
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QEvent  # noqa: E402  # reason: optional Qt imports follow importorskip
from PySide6.QtWidgets import QWidget  # noqa: E402  # reason: optional Qt imports follow importorskip

from headless.test_gui_panel_dispose import qapp as qapp  # noqa: E402, F401  # reason: shared fake-only fixtures
from je_auto_control.gui.remote_desktop import connection_screen  # noqa: E402  # reason: optional Qt imports follow importorskip


def test_retired_quick_connect_drops_live_backend_events(qapp, monkeypatch):
    received = []
    monkeypatch.setattr(connection_screen.QuickConnectScreen, "_on_error", lambda self, value: received.append(value))
    screen = connection_screen.QuickConnectScreen()
    callback = screen._viewer_callbacks()["on_error"]
    screen.dispose()
    callback(RuntimeError("late"))
    qapp.processEvents()
    assert received == []
    screen.deleteLater()


def test_retired_quick_connect_drops_already_queued_events(qapp, monkeypatch):
    received = []
    monkeypatch.setattr(connection_screen.QuickConnectScreen, "_on_error", lambda self, value: received.append(value))
    screen = connection_screen.QuickConnectScreen()
    callback = screen._viewer_callbacks()["on_error"]
    worker = threading.Thread(target=callback, args=(RuntimeError("queued"),))
    worker.start()
    worker.join(2)
    screen.dispose()
    qapp.processEvents()
    assert received == []
    screen.deleteLater()


@pytest.mark.parametrize("dispose", [False, True])
def test_surviving_callbacks_do_not_retain_deleted_quick_view(qapp, dispose):
    screen = connection_screen.QuickConnectScreen()
    callbacks = screen._viewer_callbacks()
    reference = weakref.ref(screen)
    if dispose:
        screen.dispose()
    screen.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    del screen
    gc.collect()
    assert reference() is None
    callbacks["on_error"](RuntimeError("after deletion"))
    callbacks["on_frame"](b"not an image")
    callbacks["on_cursor"](1, 2)
    qapp.processEvents()


def test_live_delivery_runs_on_gui_thread_and_retirement_drops_queued(qapp):
    from je_auto_control.gui.remote_desktop.view_lifetime import ViewLifetime
    seen = []

    class Page(QWidget):
        def receive(self, value):
            seen.append((value, threading.current_thread()))

    page = Page()
    lease = ViewLifetime(page)
    callback = lease.callback("receive")
    producer = threading.Thread(target=callback, args=("live",))
    producer.start()
    producer.join(2)
    qapp.processEvents()
    assert seen == [("live", threading.main_thread())]
    callback("queued")
    lease.retire()
    qapp.processEvents()
    assert len(seen) == 1
    page.deleteLater()


def test_close_denies_pending_future_and_late_approval(qapp, monkeypatch):
    screen = connection_screen.QuickConnectScreen()
    pending = SimpleNamespace(address=("fake", 1), transport="tcp")
    announced = threading.Event()
    requests = []
    original = screen._approvals._notify

    def announce(request):
        requests.append(request)
        original(request)
        announced.set()

    monkeypatch.setattr(screen._approvals, "_notify", announce)
    callback = screen._approvals.request
    result = []
    worker = threading.Thread(target=lambda: result.append(callback(pending)))
    worker.start()
    assert announced.wait(2)
    screen.dispose()
    worker.join(2)
    assert not worker.is_alive() and result == [False]
    requests[0].decision = "full"
    assert requests[0].decision == "denied"
    assert callback(pending) is False
    qapp.processEvents()  # queued request must not construct a dialog
    screen.deleteLater()


def test_workspace_releases_remote_page_and_preserves_registry_host(qapp, monkeypatch):
    from je_auto_control.gui import main_widget
    from je_auto_control.gui.remote_desktop import tab
    from je_auto_control.utils.remote_desktop.registry import registry, SLOT_HOST
    from headless.test_gui_panel_dispose import _Host
    monkeypatch.setattr(tab, "_load_webrtc_panels", lambda: (None, None))
    workspace = main_widget.AutoControlGUIWidget()
    entry = workspace._find_entry("remote_desktop")
    old = entry.widget
    host = _Host()
    host.start()
    registry.adopt(SLOT_HOST, host, old._quick_connect._owner)
    workspace.close_tab("remote_desktop")
    assert not entry.built
    assert registry.host is host and host.is_running
    workspace.show_tab("remote_desktop")
    assert entry.widget is not old
    assert entry.widget._webrtc_viewer_panel is None
    workspace.close_tab("remote_desktop")
    workspace.deleteLater()


def test_retired_tcp_callbacks_do_not_keep_viewer_panel(qapp, monkeypatch):
    from je_auto_control.gui.remote_desktop import viewer_panel
    from headless.test_gui_panel_dispose import _Viewer
    panel = viewer_panel._ViewerPanel()
    panel._port.setValue(1234)
    panel._token.setText("fake")
    # Keep the connect pending without entering any backend.
    class Task:
        finished = SimpleNamespace(connect=lambda callback: None)
        def cancel(self):
            return None
    monkeypatch.setattr(viewer_panel, "connect_viewer", lambda *a, **k: Task())
    panel._connect()
    backend = _Viewer.made[-1]
    reference = weakref.ref(panel)
    panel.dispose()
    panel.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    del panel
    gc.collect()
    assert reference() is None
    backend.kwargs["on_error"](RuntimeError("late"))
    backend.kwargs["on_frame"](b"invalid")
    backend.kwargs["on_audio"](b"")
    qapp.processEvents()


def test_blocked_upload_outlives_view_without_holding_it(qapp):
    from je_auto_control.gui.remote_desktop import viewer_panel
    from je_auto_control.gui.remote_desktop.view_upload import start_upload
    entered, finish, done = threading.Event(), threading.Event(), threading.Event()
    calls = []

    class Viewer:
        def send_file(self, source, dest, on_progress):
            calls.append((source, dest))
            entered.set()
            assert finish.wait(3)
            on_progress("id", 1, 1)
            done.set()
            return SimpleNamespace(transfer_id="id", success=True, error=None)

    panel = viewer_panel._ViewerPanel()
    reference = weakref.ref(panel)
    start_upload(panel, Viewer(), "source", "dest", panel._view)
    try:
        assert entered.wait(2)
        panel.dispose()
        panel.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        del panel
        gc.collect()
        assert reference() is None
    finally:
        finish.set()
    assert done.wait(2)
    qapp.processEvents()
    assert calls == [("source", "dest")]


def test_audio_stop_runs_after_page_deletion_without_blocking_qt(qapp):
    from je_auto_control.gui.remote_desktop import viewer_panel
    from PySide6.QtCore import QTimer
    entered, finish, done = threading.Event(), threading.Event(), threading.Event()
    threads = []

    def stop():
        threads.append(threading.current_thread())
        entered.set()
        finish.wait(3)
        done.set()

    panel = viewer_panel._ViewerPanel()
    panel._audio_player = SimpleNamespace(stop=stop)
    ticks = []
    timer = QTimer()
    timer.setInterval(0)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    try:
        panel.dispose()
        panel.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert entered.wait(2)
        qapp.processEvents()
        assert ticks and len(threads) == 1 and threads[0] is not threading.main_thread()
    finally:
        timer.stop()
        finish.set()
    assert done.wait(2)


def test_retirement_serializes_concurrent_producers_with_qt_deletion(qapp):
    from je_auto_control.gui.remote_desktop.view_lifetime import ViewLifetime
    calls = []

    class Page(QWidget):
        def receive(self, value):
            calls.append(value)

    page = Page()
    lease = ViewLifetime(page)
    callback = lease.callback("receive")
    ready, finish = threading.Event(), threading.Event()
    errors = []

    def producer():
        ready.set()
        try:
            for value in range(1000):
                callback(value)
            finish.wait(2)
            callback("after deletion")
        except Exception as error:
            errors.append(error)

    worker = threading.Thread(target=producer)
    worker.start()
    assert ready.wait(2)
    lease.retire()
    page.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    finish.set()
    worker.join(2)
    qapp.processEvents()
    assert not worker.is_alive() and not errors and not calls


def test_audio_replacement_finishes_old_stop_before_new_start(qapp, monkeypatch):
    from je_auto_control.gui.remote_desktop import viewer_panel
    events = []
    active = [True]

    def stop_old():
        events.append("old stopped")
        active[0] = False

    class NewPlayer:
        def start(self):
            assert not active[0]
            events.append("new started")
            active[0] = True

        def stop(self):
            active[0] = False

    panel = viewer_panel._ViewerPanel()
    panel._audio_available = True
    panel._enable_audio.setChecked(True)
    panel._audio_player = SimpleNamespace(stop=stop_old)
    monkeypatch.setattr(viewer_panel, "AudioPlayer", NewPlayer)
    panel._start_audio_player_if_requested()
    assert events == ["old stopped", "new started"]
    assert isinstance(panel._audio_player, NewPlayer)
    panel.dispose()
    panel.deleteLater()


@pytest.mark.parametrize("kind", ["host", "viewer"])
def test_webrtc_backend_survives_deleted_view_and_cleanup_starts_after_delete(qapp, monkeypatch, kind):
    from pathlib import Path
    from je_auto_control.gui import tab_task_controller
    from je_auto_control.gui.remote_desktop import webrtc_panel, webrtc_host_connection, webrtc_viewer_connection
    from je_auto_control.gui.remote_desktop import view_frames
    workers, stopped = [], []

    def defer_start(owner, worker, **kwargs):
        workers.append(worker)
        return None

    class Backend:
        authenticated = False
        _pc = None

        def __init__(self, **kwargs):
            self.callbacks = kwargs

        def set_file_received_callback(self, callback):
            self.file = callback

        def set_inbox_listing_callback(self, callback):
            self.listing = callback

        def set_inbox_op_result_callback(self, callback):
            self.operation = callback

        def stop(self):
            stopped.append(threading.current_thread())

        stop_all = stop

    monkeypatch.setattr(tab_task_controller, "start_worker", defer_start)
    monkeypatch.setattr(webrtc_host_connection, "MultiViewerHost", Backend)
    monkeypatch.setattr(webrtc_viewer_connection, "WebRTCDesktopViewer", Backend)
    monkeypatch.setattr(view_frames, "_av_frame_to_qimage", lambda frame: None)
    if kind == "host":
        panel = webrtc_panel._WebRTCHostPanel()
        backend = panel._build_multi_host("token")
        panel._multi_host = backend
        callbacks = [(backend.callbacks["on_session_state"], ("id", "failed")),
                     (backend.callbacks["on_session_authenticated"], ("id",)),
                     (backend.callbacks["on_annotation"], ({},)),
                     (backend.callbacks["on_pending_viewer"], ("id", "viewer"))]
    else:
        panel = webrtc_panel._WebRTCViewerPanel()
        backend = panel._build_viewer("token")
        panel._viewer = backend
        callbacks = [(backend.callbacks["on_state_change"], ("failed",)),
                     (backend.callbacks["on_auth_result"], (True,)),
                     (backend.callbacks["on_frame"], (object(),)),
                     (backend.file, (Path("late"),)),
                     (backend.listing, ([],)), (backend.operation, ("late", False, {}))]
    for callback, args in callbacks:
        callback(*args)
    reference = weakref.ref(panel)
    panel.dispose()
    assert workers and not stopped
    panel.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    del panel
    gc.collect()
    assert reference() is None
    for callback, args in callbacks:
        callback(*args)
    qapp.processEvents()
    for worker in workers:
        thread = threading.Thread(target=worker.run)
        thread.start()
        thread.join(2)
        assert not thread.is_alive()
    assert len(stopped) == 1 and stopped[0] is not threading.main_thread()




def test_approval_timeout_cannot_accept_racing_late_allow():
    from je_auto_control.gui.remote_desktop.view_approvals import ViewApprovals

    def notify(request):
        def timed_out(timeout):
            request.resolve("full")
            return False
        request.event.wait = timed_out

    approvals = ViewApprovals(notify, 0)
    assert approvals.request(SimpleNamespace()) is False
