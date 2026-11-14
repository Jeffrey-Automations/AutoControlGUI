"""Network calls the GUI runs stop when their task is stopped or runs out of time.

``perform_call`` -- the one path the REST, signaling, USB and admin clients use
-- now sends nothing inside a cancelled scope and does not hand on a reply that
arrived after the cancellation. The signaling long-polls (the host waits up to
ten minutes for an answer) look at their stop between polls instead of only
after the whole wait: stopping the WebRTC host used to leave the publish loop
waiting it out.
"""
import threading
import time
from concurrent.futures import CancelledError

import pytest

from je_auto_control.utils.exception.cancellation import CancellationToken, cancellation_scope
from je_auto_control.utils.http_client import http_client
from je_auto_control.utils.remote_desktop import signaling_client


def _reply():
    return {"status": 200, "text": "{}", "json": {}, "headers": {}}


def test_a_cancelled_scope_sends_nothing(monkeypatch):
    sent = []
    monkeypatch.setattr(http_client, "urllib_transport", lambda call: sent.append(call) or _reply())
    token = CancellationToken(task_id=1)
    token.cancel()
    with cancellation_scope(token), pytest.raises(CancelledError):
        http_client.perform_call(http_client.build_call("http://127.0.0.1:9/x", "GET"))  # NOSONAR python:S5332
    assert sent == []


def test_a_reply_after_the_cancellation_is_not_handed_on(monkeypatch):
    token = CancellationToken(task_id=2)

    def slow_transport(call):
        token.cancel()                           # Stop pressed while the request was out
        return _reply()

    monkeypatch.setattr(http_client, "urllib_transport", slow_transport)
    with cancellation_scope(token), pytest.raises(CancelledError):
        http_client.perform_call(http_client.build_call("http://127.0.0.1:9/x", "GET"))  # NOSONAR python:S5332


def test_an_unscoped_call_is_unchanged(monkeypatch):
    monkeypatch.setattr(http_client, "urllib_transport", lambda call: _reply())
    assert http_client.perform_call(http_client.build_call("http://127.0.0.1:9/x", "GET"))["status"] == 200  # NOSONAR


def test_a_signaling_wait_ends_soon_after_it_is_cancelled(monkeypatch):
    monkeypatch.setattr(signaling_client, "fetch_answer", lambda *a, **k: None)
    stop = threading.Event()
    threading.Timer(0.2, stop.set).start()
    started = time.monotonic()
    with pytest.raises(CancelledError):
        signaling_client.wait_for_answer("http://127.0.0.1:9", "h", timeout_s=600.0,  # NOSONAR python:S5332
                                         poll_interval_s=5.0, cancelled=stop.is_set)
    assert time.monotonic() - started < 1.5


def test_a_signaling_wait_follows_the_callers_scope(monkeypatch):
    monkeypatch.setattr(signaling_client, "fetch_offer", lambda *a, **k: None)
    token = CancellationToken(task_id=3)
    threading.Timer(0.2, token.cancel).start()
    started = time.monotonic()
    with cancellation_scope(token), pytest.raises(CancelledError):
        signaling_client.wait_for_offer("http://127.0.0.1:9", "h", timeout_s=600.0,  # NOSONAR python:S5332
                                        poll_interval_s=5.0)
    assert time.monotonic() - started < 1.5


def test_an_uncancelled_wait_still_times_out(monkeypatch):
    monkeypatch.setattr(signaling_client, "fetch_answer", lambda *a, **k: None)
    with pytest.raises(signaling_client.SignalingError):
        signaling_client.wait_for_answer("http://127.0.0.1:9", "h", timeout_s=0.3,  # NOSONAR python:S5332
                                         poll_interval_s=0.1)


def test_stopping_the_publish_loop_ends_its_long_wait_and_drops_the_session(monkeypatch):
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    try:
        from je_auto_control.gui.remote_desktop.webrtc_workers import HostPublishLoopWorker
    except ImportError:
        pytest.skip("the WebRTC GUI needs the webrtc extra")
    from headless._qt_settle import pump_until
    monkeypatch.setattr(signaling_client, "push_offer", lambda *a, **k: None)
    monkeypatch.setattr(signaling_client, "fetch_answer", lambda *a, **k: None)
    stopped, waiting = [], threading.Event()

    class _Host:
        def create_session_offer(self):
            waiting.set()
            return "session-1", "v=0"

        def stop_session(self, session_id):
            stopped.append(session_id)

    worker = HostPublishLoopWorker(multi_host=_Host(), server_url="http://127.0.0.1:9",  # NOSONAR python:S5332
                                   host_id="h", secret=None, wait_timeout_s=600.0)
    worker.start()
    try:
        assert waiting.wait(5.0)
        time.sleep(0.2)                           # now inside the ten-minute wait
        worker.requestInterruption()
        assert pump_until(lambda: not worker.isRunning(), timeout=3.0)
        assert stopped == ["session-1"]
    finally:
        worker.requestInterruption()
