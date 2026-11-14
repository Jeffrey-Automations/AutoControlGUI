"""Closing admission is separate from a full stop: immediate, lock-light, and safe when authority is gone.

A full ``stop()`` waits on native work -- PortAudio's close, zeroconf's thread,
a peer connection -- under the owner's lock, and a caller whose authority was
revoked may not get to run it at all. ``close_admission()`` only stops the
owner taking anything new (audio blocks and writes, discovery reports, viewer
sessions, answers and input), takes no lock a native cleanup holds, and leaves
the full stop to run later. A ``StopQueue`` calls it on the GUI thread before
it queues the stop.
"""
import threading

import pytest

from je_auto_control.utils.remote_desktop.audio import AudioPlayer
from je_auto_control.utils.remote_desktop.audio_retirement import AudioLease
from je_auto_control.utils.remote_desktop.webrtc_retirement import PeerStopPending
from headless.test_remote_desktop_audio import fake_sd  # noqa: F401  # reason: shared fake sounddevice fixture
from headless.test_browser_retirement import backend  # noqa: F401  # reason: shared fake zeroconf fixture
from headless.test_remote_desktop_multi_viewer import _FakeHost, _host, fake_webrtc  # noqa: F401


def test_an_audio_lease_admits_nothing_once_closed_and_still_retires():
    lease = AudioLease()
    lease.activate()
    assert lease.enter()
    lease.leave()
    lease.close_admission()
    assert lease.enter() is False
    assert lease.status.admission_closed
    lease.retire()                               # no stream: the full retire still completes
    assert lease.status.complete


def test_an_audio_player_closes_admission_while_its_lock_is_held(fake_sd):  # noqa: F811
    player = AudioPlayer()
    player.start()
    stream = fake_sd.last_output
    with player._lock:                           # a stop or start busy in a native call
        done = threading.Event()
        worker = threading.Thread(target=lambda: (player.close_admission(), done.set()))
        worker.start()
        assert done.wait(2.0), "close_admission waited for the owner's lock"
    worker.join(2.0)
    with pytest.raises(RuntimeError, match="not running"):
        player.play(b"\x00\x00")
    assert not stream.closed                     # the stream is the full stop's job
    player.stop()
    assert stream.closed


def test_a_lan_browser_stops_reporting_at_once_and_still_stops(backend):  # noqa: F811
    from je_auto_control.utils.remote_desktop import lan_discovery as discovery
    published = []
    browser = discovery.HostBrowser(published.append)
    browser.close_admission()
    browser._listener.add_service(None, "kind", "late-host")
    assert published == []
    assert browser.retirement_status.admission_closed
    browser.stop()
    assert "cancel" in backend.calls and "close" in backend.calls


def test_a_multi_viewer_host_takes_no_new_session_answer_or_input_once_closed():
    delivered = []
    host = _host(input_dispatcher=delivered.append)
    existing = host.create_owned_session_offer()
    host._dispatch({"type": "click"})
    host.close_admission()
    host._dispatch({"type": "click"})
    assert delivered == [{"type": "click"}]      # only the input before the close
    with pytest.raises(PeerStopPending):
        host.create_owned_session_offer()
    with pytest.raises(PeerStopPending):
        host.accept_session_answer(existing.session_id, "answer")
    host.stop_all()                              # the full stop still closes what was admitted
    assert _FakeHost.instances[0].stopped


def test_a_stop_queue_closes_admission_before_the_stop_runs():
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    import functools
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QWidget
    QApplication.instance() or QApplication([])
    from je_auto_control.gui import _slow_op
    from headless._qt_settle import pump_until
    events, release = [], threading.Event()

    class _Owner:
        def close_admission(self):
            events.append(("close_admission", threading.get_ident()))

        def stop(self):
            assert release.wait(10.0)
            events.append(("stop", threading.get_ident()))

    owner, nested = _Owner(), _Owner()
    widget = QWidget()
    try:
        queue = _slow_op.StopQueue(widget)
        queue.retire(functools.partial(_slow_op.stop_each, owner.stop, nested.stop))
        gui = threading.get_ident()
        assert events == [("close_admission", gui), ("close_admission", gui)]   # both, before anything ran
        release.set()
        assert pump_until(lambda: queue.pending == 0)
        assert [name for name, _thread in events[2:]] == ["stop", "stop"]
        assert all(thread != gui for _name, thread in events[2:])
    finally:
        release.set()
        widget.deleteLater()
