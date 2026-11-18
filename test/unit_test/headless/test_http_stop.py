"""A stop or a cancellation ends an HTTP request that is already out, instead of waiting for its timeout.

Real sockets on 127.0.0.1: one server reads the request and never answers (and
notes when the client hangs up), one answers at once.
"""
import errno
import socket
import sys
import threading
import time
import urllib.error
from concurrent.futures import CancelledError

import pytest

from je_auto_control.utils.exception.cancellation import CancellationToken, cancellation_scope
from je_auto_control.utils.executor.run_control import ExecutionStopped, StopToken, stoppable_run
from je_auto_control.utils.http_client import http_client

_BODY = b'{"ok": true}'
_REPLY = (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n"
          b"Content-Length: " + str(len(_BODY)).encode() + b"\r\n\r\n" + _BODY)


class _Server:
    """One listening socket on 127.0.0.1 that serves each connection with ``answer``."""

    def __init__(self, answer: bool) -> None:
        self._answer = answer
        self._listener = socket.socket()
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(8)
        self._listener.settimeout(0.2)
        self.port = self._listener.getsockname()[1]
        self.connections = 0
        self.requested = threading.Event()
        self.hung_up = threading.Event()
        self._closing = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/slow"  # NOSONAR python:S5332  # reason: local test server

    def _serve(self) -> None:
        while not self._closing.is_set():
            try:
                client, _address = self._listener.accept()
            except OSError:
                continue
            self.connections += 1
            with client:
                client.settimeout(10)
                if client.recv(65536):
                    self.requested.set()
                if self._answer:
                    client.sendall(_REPLY)
                    continue
                try:
                    if client.recv(1) == b"":        # the client shut its side
                        self.hung_up.set()
                except OSError:
                    self.hung_up.set()

    def close(self) -> None:
        self._closing.set()
        self._thread.join(timeout=5)
        self._listener.close()


@pytest.fixture
def silent():
    server = _Server(answer=False)
    yield server
    server.close()


@pytest.fixture
def answering():
    server = _Server(answer=True)
    yield server
    server.close()


def _later(action, delay: float = 0.3) -> None:
    timer = threading.Timer(delay, action)
    timer.daemon = True
    timer.start()


def _call(url: str, timeout: float = 30.0):
    return http_client.perform_call(http_client.build_call(url, "GET", timeout=timeout))


def test_a_stop_ends_a_request_waiting_for_its_reply(silent):
    token = StopToken("http-stop")
    _later(lambda: token.stop("test"))
    started = time.monotonic()
    with stoppable_run(token=token), pytest.raises(ExecutionStopped):
        _call(silent.url)
    assert time.monotonic() - started < 5          # not the 30 s timeout
    assert silent.requested.is_set()
    assert silent.hung_up.wait(5), "the request's socket was left open"


def test_a_cancellation_ends_a_request_waiting_for_its_reply(silent):
    token = CancellationToken(task_id=41)
    _later(token.cancel)
    started = time.monotonic()
    with cancellation_scope(token), pytest.raises(CancelledError):
        _call(silent.url)
    assert time.monotonic() - started < 5
    assert silent.hung_up.wait(5)


def test_a_stopped_run_sends_nothing(silent):
    token = StopToken("http-stopped")
    token.stop("before")
    with stoppable_run(token=token), pytest.raises(ExecutionStopped):
        _call(silent.url)
    time.sleep(0.3)
    assert silent.connections == 0


def test_inside_a_run_a_reply_still_arrives_whole(answering):
    with stoppable_run(token=StopToken("http-answer")):
        response = _call(answering.url)
    assert response["status"] == 200
    assert response["json"] == {"ok": True}


def test_inside_a_run_the_timeout_still_applies(silent):
    with stoppable_run(token=StopToken("http-timeout")), pytest.raises(OSError):
        _call(silent.url, timeout=0.5)


def test_outside_any_run_the_request_stays_on_the_calling_thread(answering, monkeypatch):
    seen = []
    real = http_client.urllib_transport

    def transport(call):
        seen.append(threading.current_thread())
        return real(call)

    monkeypatch.setattr(http_client, "urllib_transport", transport)
    assert _call(answering.url)["status"] == 200
    assert seen == [threading.current_thread()]


def test_a_stopped_ac_http_request_ends_the_script_promptly(silent):
    from je_auto_control.utils.executor.action_executor import Executor
    executor = Executor()
    token = StopToken("http-script")
    _later(lambda: token.stop("test"))
    started = time.monotonic()
    with stoppable_run(token=token), pytest.raises(ExecutionStopped):
        executor.execute_action([["AC_http_request", {"url": silent.url, "timeout": 30}],
                                 ["AC_set_var", {"name": "after", "value": 1}]])
    assert time.monotonic() - started < 10
    assert executor.variables.get("after") is None


class _PendingSocket:
    """A socket whose non-blocking connect never completes."""

    closed = False

    def __init__(self, *args) -> None:
        self.timeout = "unset"

    def setblocking(self, flag) -> None:
        return None

    def connect_ex(self, target) -> int:
        return 10035 if sys.platform == "win32" else errno.EINPROGRESS

    def settimeout(self, value) -> None:
        self.timeout = value

    def close(self) -> None:
        _PendingSocket.closed = True


def _never_ready(read, write, error, timeout):
    time.sleep(timeout)
    return [], [], []


def test_a_stop_ends_a_connect_that_has_not_finished(monkeypatch):
    monkeypatch.setattr(http_client, "_wait_writable", _never_ready)
    stop = threading.Event()
    _later(stop.set)
    started = time.monotonic()
    with pytest.raises(urllib.error.URLError, match="request stopped"):
        http_client._connect_in_slices(("127.0.0.1", 9), 30, aborted=stop.is_set, make_socket=_PendingSocket)
    assert time.monotonic() - started < 2
    assert _PendingSocket.closed


def test_a_connect_that_never_finishes_still_times_out(monkeypatch):
    monkeypatch.setattr(http_client, "_wait_writable", _never_ready)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        http_client._connect_in_slices(("127.0.0.1", 9), 0.4, aborted=lambda: False, make_socket=_PendingSocket)
    assert 0.3 < time.monotonic() - started < 2


def test_a_stop_ends_a_request_still_connecting_and_sends_nothing(silent, monkeypatch):
    waits = []

    def held(read, write, error, timeout):
        waits.append(timeout)
        return _never_ready(read, write, error, timeout)

    monkeypatch.setattr(http_client, "_wait_writable", held)
    token = StopToken("http-connecting")
    _later(lambda: token.stop("test"))
    started = time.monotonic()
    with stoppable_run(token=token), pytest.raises(ExecutionStopped):
        _call(silent.url)
    if not waits:
        pytest.skip("this loopback connect completed at once, so there was no handshake to wait on")
    assert time.monotonic() - started < 3
    assert not silent.requested.is_set(), "the request was sent after the stop"


def test_a_stop_does_not_wait_for_a_name_lookup_and_nothing_is_sent_after_it(silent, monkeypatch):
    """A lookup cannot be interrupted, but the call does not wait for it and sends nothing once it ends."""
    looked_up, release = threading.Event(), threading.Event()
    real = socket.getaddrinfo

    def slow_lookup(*args, **kwargs):
        looked_up.set()
        release.wait(10)
        return real(*args, **kwargs)

    monkeypatch.setattr(http_client.socket, "getaddrinfo", slow_lookup)
    token = StopToken("http-lookup")
    _later(lambda: token.stop("test"))
    started = time.monotonic()
    with stoppable_run(token=token), pytest.raises(ExecutionStopped):
        _call(silent.url)
    assert time.monotonic() - started < 3, "the stop waited for the lookup"
    assert looked_up.is_set()
    release.set()                     # the lookup finishes after the stop ...
    time.sleep(0.5)
    assert not silent.requested.is_set(), "... and nothing is sent once it has"
