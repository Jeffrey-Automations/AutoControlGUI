"""Connections still authenticating do not take the host's viewer slots.

A connection that never answered the challenge sat in the client table for up
to 60 s and counted against ``max_clients``, so a few silent sockets locked
every real viewer out. Connections in the handshake now have their own small
cap, refused at accept, and a shorter deadline; only a connection that
proved its credentials takes a ``max_clients`` slot. Loopback only; no real
input or capture runs.
"""
import socket
import ssl
import threading
import time

import pytest

from je_auto_control.utils.remote_desktop import host_admission
from je_auto_control.utils.remote_desktop.auth import compute_response
from je_auto_control.utils.remote_desktop.host import RemoteDesktopHost
from je_auto_control.utils.remote_desktop.protocol import (
    MessageType, encode_frame, read_message,
)

TOKEN = "pending-auth-token"


def _host(**kwargs) -> RemoteDesktopHost:
    kwargs.setdefault("frame_provider", lambda: b"\xff\xd8fake")
    kwargs.setdefault("input_dispatcher", lambda _message: None)
    kwargs.setdefault("enable_cursor_broadcast", False)
    host = RemoteDesktopHost(TOKEN, bind="127.0.0.1", port=0, host_id="123456789", **kwargs)
    host.start()
    return host


def _silent(host: RemoteDesktopHost) -> socket.socket:
    """Open a connection that reads the challenge and never answers it."""
    sock = socket.create_connection(("127.0.0.1", host.port), timeout=5)
    kind, _nonce = read_message(sock)
    assert kind is MessageType.AUTH_CHALLENGE
    return sock


def _login(host: RemoteDesktopHost, token: str = TOKEN):
    sock = socket.create_connection(("127.0.0.1", host.port), timeout=5)
    kind, nonce = read_message(sock)
    assert kind is MessageType.AUTH_CHALLENGE
    sock.sendall(encode_frame(MessageType.AUTH_RESPONSE, compute_response(token, nonce)))
    kind, _payload = read_message(sock)
    return sock, kind


def _closed_by_peer(sock: socket.socket, within: float) -> bool:
    """True when the peer closes ``sock`` within ``within`` seconds."""
    sock.settimeout(within)
    try:
        return sock.recv(1) == b""
    except ConnectionError:
        return True
    except socket.timeout:
        return False


def _close_all(*socks) -> None:
    for sock in socks:
        try:
            sock.close()
        except OSError:
            pass


def test_silent_connections_do_not_take_the_viewer_slots():
    host = _host(max_clients=1)
    silent = [_silent(host) for _ in range(3)]
    try:
        viewer, kind = _login(host)
        try:
            assert kind is MessageType.AUTH_OK
        finally:
            viewer.close()
    finally:
        _close_all(*silent)
        host.stop()


def test_connections_beyond_the_pending_cap_are_refused_at_accept():
    host = _host(max_pending_handshakes=2)
    silent = [_silent(host) for _ in range(2)]
    extra = socket.create_connection(("127.0.0.1", host.port), timeout=5)
    try:
        assert _closed_by_peer(extra, within=3.0), "a third pending connection was admitted"
    finally:
        _close_all(extra, *silent)
        host.stop()
    # The pending slots come back once those connections are gone.
    host = _host(max_pending_handshakes=2)
    try:
        for _ in range(3):
            sock, kind = _login(host)
            assert kind is MessageType.AUTH_OK
            sock.close()
    finally:
        host.stop()


def test_a_connection_that_does_not_authenticate_is_closed_at_the_auth_deadline():
    host = _host(auth_timeout=0.5)
    silent = _silent(host)
    started = time.monotonic()
    try:
        assert _closed_by_peer(silent, within=5.0)
        assert time.monotonic() - started < 3.0
    finally:
        _close_all(silent)
        host.stop()


def test_a_peer_trickling_its_response_is_bounded_by_the_deadline_as_a_whole():
    host = _host(auth_timeout=0.6)
    sock = _silent(host)
    frame = encode_frame(MessageType.AUTH_RESPONSE, b"x" * 32)
    started = time.monotonic()
    try:
        for byte in frame:
            try:
                sock.sendall(bytes([byte]))
            except OSError:
                break
            time.sleep(0.1)
            if time.monotonic() - started > 5.0:
                break
        assert _closed_by_peer(sock, within=1.0)
        assert time.monotonic() - started < 4.0
    finally:
        _close_all(sock)
        host.stop()


def test_the_host_approval_is_not_cut_short_by_the_auth_deadline():
    def approve_slowly(_pending):
        time.sleep(1.0)
        return True

    host = _host(auth_timeout=0.3, on_pending_viewer=approve_slowly)
    try:
        sock, kind = _login(host)
        assert kind is MessageType.AUTH_OK
        sock.close()
    finally:
        host.stop()


def test_a_viewer_awaiting_approval_holds_a_viewer_slot():
    entered, release = threading.Event(), threading.Event()

    def approve_when_released(_pending):
        entered.set()
        return release.wait(5.0)

    host = _host(max_clients=1, on_pending_viewer=approve_when_released)
    first_result = []
    first = threading.Thread(target=lambda: first_result.append(_login(host)), daemon=True)
    first.start()
    try:
        assert entered.wait(5.0)
        host._on_pending_viewer = None
        second = socket.create_connection(("127.0.0.1", host.port), timeout=5)
        try:
            # Refused before the challenge, as a full host always did.
            assert _closed_by_peer(second, within=3.0)
        finally:
            second.close()
    finally:
        release.set()
        first.join(timeout=5.0)
        for sock, _kind in first_result:
            sock.close()
        host.stop()
    assert first_result and first_result[0][1] is MessageType.AUTH_OK


def test_stop_closes_connections_still_authenticating():
    host = _host()
    silent = _silent(host)
    try:
        host.stop()
        assert _closed_by_peer(silent, within=3.0)
    finally:
        _close_all(silent)
        host.stop()


def test_a_tls_peer_that_never_says_hello_is_closed_at_the_auth_deadline(tmp_path):
    pytest.importorskip("cryptography")
    from .test_remote_desktop_tls import _generate_self_signed, _server_context
    context: ssl.SSLContext = _server_context(*_generate_self_signed(tmp_path))
    host = _host(auth_timeout=0.5, ssl_context=context)
    raw = socket.create_connection(("127.0.0.1", host.port), timeout=5)
    started = time.monotonic()
    try:
        assert _closed_by_peer(raw, within=5.0)
        assert time.monotonic() - started < 3.0
    finally:
        _close_all(raw)
        host.stop()


@pytest.mark.parametrize("kwargs", [
    {"max_pending_handshakes": 0}, {"auth_timeout": 0}, {"auth_timeout": -1.0},
])
def test_invalid_admission_settings_are_refused(kwargs):
    with pytest.raises(ValueError):
        RemoteDesktopHost(TOKEN, frame_provider=lambda: b"", host_id="123456789", **kwargs)


def test_the_documented_defaults():
    host = RemoteDesktopHost(TOKEN, frame_provider=lambda: b"", host_id="123456789")
    assert host_admission.DEFAULT_MAX_PENDING_HANDSHAKES == 8
    assert host_admission.DEFAULT_AUTH_TIMEOUT_S == 10.0
    assert host._max_pending_handshakes == host_admission.DEFAULT_MAX_PENDING_HANDSHAKES
    assert host._auth_timeout == host_admission.DEFAULT_AUTH_TIMEOUT_S
