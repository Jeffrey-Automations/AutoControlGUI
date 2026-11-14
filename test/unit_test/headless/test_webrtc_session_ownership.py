"""The WebRTC host panel stops the session it captured, never a later one, and never on the GUI thread.

The panel made its offers with ``create_session_offer`` and dropped or
disconnected sessions with ``stop_session(session_id)``, resolved when the
stop ran -- in the background, by then possibly a different session under the
same id. Dropping an offer nobody would show also ran that stop on the GUI
thread when the panel went away. The panel now uses the owned offers and
retirements ``MultiViewerHost`` already offers, captured before anything is
scheduled.
"""
import os
import threading
import types

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
pytest.importorskip("aiortc", exc_type=ImportError)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from je_auto_control.gui.remote_desktop import webrtc_host_connection  # noqa: E402
from je_auto_control.utils.remote_desktop import multi_viewer as mv  # noqa: E402
from headless._qt_settle import pump_until  # noqa: E402
from headless.test_remote_desktop_multi_viewer import _FakeHost, _host, fake_webrtc  # noqa: E402,F401

_APP = QApplication.instance() or QApplication([])


class _HeldRetirement:
    def __init__(self):
        self.release, self.entered, self.threads = threading.Event(), threading.Event(), []

    def stop(self):
        self.threads.append(threading.get_ident())
        self.entered.set()
        assert self.release.wait(10.0)


def test_dropping_an_offer_on_the_gui_thread_stops_it_on_a_worker():
    retirement = _HeldRetirement()
    offer = types.SimpleNamespace(session_id="s", sdp="v=0", retirement=retirement)
    gui = threading.get_ident()
    webrtc_host_connection._drop_offer(offer)                # returns without waiting for the peer
    assert retirement.entered.wait(10.0)
    assert retirement.threads[0] != gui
    retirement.release.set()
    from je_auto_control.gui.tab_task_controller import task_controller
    assert pump_until(lambda: task_controller().active_count() == 0)


def test_dropping_an_offer_on_a_worker_stops_it_there():
    retirement = _HeldRetirement()
    retirement.release.set()
    offer = types.SimpleNamespace(session_id="s", sdp="v=0", retirement=retirement)
    worker = threading.Thread(target=webrtc_host_connection._drop_offer, args=(offer,))
    worker.start()
    worker.join(10.0)
    assert retirement.threads == [worker.ident]


def test_a_dropped_offer_never_stops_the_session_that_reused_its_id(monkeypatch):
    monkeypatch.setattr(mv.secrets, "token_hex", lambda _: "reused")
    coordinator = _host()
    stale = coordinator.create_owned_session_offer()       # the panel was gone when it arrived
    stale.retirement.stop()                                # ... and the session ended some other way
    fresh = coordinator.create_owned_session_offer()       # a new session under the same id
    fresh_peer = _FakeHost.instances[-1]
    worker = threading.Thread(target=webrtc_host_connection._drop_offer, args=(stale,))
    worker.start()
    worker.join(10.0)
    assert not fresh_peer.stopped
    assert coordinator.session_count() == 1
    fresh.retirement.stop()
