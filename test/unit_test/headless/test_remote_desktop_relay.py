"""Phase 3.3: tests for the in-process TCP relay."""
import socket
import threading
import time

import pytest

from je_auto_control.utils.remote_desktop.relay import (
    RelayError, RelayServer, encode_handshake,
)


def _connect(port: int) -> socket.socket:
    sock = socket.create_connection(("127.0.0.1", port), timeout=5.0)
    return sock


@pytest.fixture
def relay():
    server = RelayServer(bind="127.0.0.1", port=0)
    server.start()
    yield server
    server.stop(timeout=1.0)


def test_relay_pairs_two_peers_by_session_id(relay):
    session_id = b"S" * 32
    host = _connect(relay.port)
    viewer = _connect(relay.port)
    host.sendall(encode_handshake("host", session_id))
    viewer.sendall(encode_handshake("viewer", session_id))
    try:
        host.sendall(b"hello viewer")
        deadline = time.monotonic() + 2.0
        received = bytearray()
        viewer.settimeout(2.0)
        while time.monotonic() < deadline and len(received) < 12:
            chunk = viewer.recv(64)
            if not chunk:
                break
            received.extend(chunk)
        assert bytes(received) == b"hello viewer"
        # Now reverse direction.
        viewer.sendall(b"reply from viewer")
        host.settimeout(2.0)
        recv2 = bytearray()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and len(recv2) < 17:
            chunk = host.recv(64)
            if not chunk:
                break
            recv2.extend(chunk)
        assert bytes(recv2) == b"reply from viewer"
    finally:
        for s in (host, viewer):
            try:
                s.close()
            except OSError:
                pass


def test_relay_only_pairs_matching_session_ids(relay):
    host = _connect(relay.port)
    viewer = _connect(relay.port)
    host.sendall(encode_handshake("host", b"A" * 32))
    viewer.sendall(encode_handshake("viewer", b"B" * 32))
    # The peers should NOT exchange data because the IDs differ.
    try:
        host.sendall(b"this should not reach the viewer")
        viewer.settimeout(0.5)
        got = b""
        try:
            got = viewer.recv(64)
        except (socket.timeout, TimeoutError, BlockingIOError):
            pass
        assert got == b""
    finally:
        for s in (host, viewer):
            try:
                s.close()
            except OSError:
                pass


def test_relay_rejects_role_collision(relay):
    """Two hosts (or two viewers) on the same session must not pair."""
    session_id = b"X" * 32
    first = _connect(relay.port)
    second = _connect(relay.port)
    first.sendall(encode_handshake("host", session_id))
    second.sendall(encode_handshake("host", session_id))
    time.sleep(0.3)
    # The second arrival is dropped by the relay; sending should fail
    # OR the socket should be at EOF.
    second.settimeout(0.5)
    got = b""
    try:
        got = second.recv(16)
    except (socket.timeout, TimeoutError, BlockingIOError, ConnectionResetError):
        pass
    assert got == b""
    for s in (first, second):
        try:
            s.close()
        except OSError:
            pass


def test_encode_handshake_validation():
    with pytest.raises(RelayError):
        encode_handshake("unknown", b"S" * 32)
    with pytest.raises(RelayError):
        encode_handshake("host", b"too-short")


def test_relay_stops_cleanly():
    server = RelayServer(bind="127.0.0.1", port=0)
    server.start()
    assert server.is_running
    server.stop(timeout=1.0)
    assert not server.is_running


def test_rapid_start_stop_never_leaks_a_thread_exception(monkeypatch):
    """Stopping must not blow up the accept thread.

    Regression: start() published the listening socket and left the *new*
    thread to call settimeout() on it. A stop() landing in that window closed
    the socket first, so settimeout raised WSAENOTSOCK (WinError 10038) outside
    any handler and the accept thread died with an unhandled exception —
    reproducibly, on ~45% of tight start/stop cycles.

    test_relay_stops_cleanly above cannot catch this: it only asserts the
    is_running flags, which are correct whether or not the thread survived.
    """
    caught: list = []
    monkeypatch.setattr(threading, "excepthook",
                        lambda args: caught.append(args.exc_value))

    for _ in range(50):
        server = RelayServer(bind="127.0.0.1", port=0)
        server.start()
        server.stop(timeout=1.0)   # no sleep: keep the race window wide

    assert caught == [], f"accept thread raised: {caught[:3]}"


def test_stopping_the_relay_frees_a_session_blocked_on_a_peer_that_stopped_reading():
    """The pipe blocked in sendall() saw neither the stop flag nor the other pipe's shutdown."""
    from je_auto_control.utils.remote_desktop import relay as relay_module
    host_far, host_near = socket.socketpair()
    viewer_far, viewer_near = socket.socketpair()
    viewer_near.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8192)
    stop = threading.Event()
    session = threading.Thread(target=relay_module._pair_and_pump, args=(host_near, viewer_near, stop),
                               daemon=True)
    session.start()
    feeder = threading.Thread(target=_feed_until_refused, args=(host_far,), daemon=True)
    feeder.start()
    try:
        time.sleep(0.5)                 # the viewer never reads: the pipe is blocked by now
        stop.set()
        session.join(timeout=5.0)
        assert not session.is_alive()
    finally:
        for sock in (host_far, viewer_far, host_near, viewer_near):
            sock.close()
        feeder.join(timeout=2.0)


def _feed_until_refused(sock: socket.socket) -> None:
    sock.settimeout(3.0)
    try:
        for _ in range(256):
            sock.sendall(b"x" * 65536)
    except OSError:
        pass


def test_a_peer_that_finishes_its_handshake_after_stop_is_not_parked():
    server = RelayServer(bind="127.0.0.1", port=0)
    server.start()
    server.stop(timeout=1.0)
    near, far = socket.socketpair()
    try:
        server._register_or_pair(0x01, b"S" * 32, near)
        assert not server._pending
        assert near.fileno() == -1
    finally:
        near.close()
        far.close()


def test_an_aborted_connection_does_not_end_the_relays_accept_loop(monkeypatch):
    server = RelayServer(bind="127.0.0.1", port=0)
    server.start()
    real = server._listen_sock
    server.stop(timeout=1.0)

    class _Flaky:
        calls = 0

        def accept(self):
            _Flaky.calls += 1
            if _Flaky.calls == 1:
                raise ConnectionAbortedError("aborted before accept")
            stop.set()
            raise socket.timeout()

    del real
    stop = threading.Event()
    server._listen_sock = _Flaky()
    server._accept_loop(stop)
    server._listen_sock = None
    assert _Flaky.calls == 2
