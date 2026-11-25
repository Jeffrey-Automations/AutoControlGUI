"""Regression tests for the remote-desktop robustness defects of the 2026-09-23 audit.

A malformed INPUT message or WebSocket frame killed the host's receive thread
without ``stop()``, leaving a handler that held a client slot; the viewer's
thread died the same way without telling the GUI. The TLS / WS / auth
handshake ran on the one accept thread, so a slow peer blocked every other
viewer, and the signaling client let a timeout or a hang-up out as something
other than ``SignalingError``.
"""
import socket
import threading
import time

import pytest

from je_auto_control.utils.exception.exceptions import AutoControlScreenException
from je_auto_control.utils.remote_desktop import host_capture, signaling_client, ws_protocol
from je_auto_control.utils.remote_desktop.auth import compute_response
from je_auto_control.utils.remote_desktop.host import RemoteDesktopHost
from je_auto_control.utils.remote_desktop.host_client import _ClientHandler
from je_auto_control.utils.remote_desktop.input_dispatch import InputDispatchError, dispatch_input
from je_auto_control.utils.remote_desktop.protocol import (
    AuthenticationError, MessageType, ProtocolError, encode_frame, read_message,
)
from je_auto_control.utils.remote_desktop.transport import WsMessageChannel
from je_auto_control.utils.remote_desktop.viewer import RemoteDesktopViewer
from je_auto_control.utils.remote_desktop.ws_protocol import WsProtocolError


@pytest.mark.parametrize("message", [
    {"action": "key_press"},                               # KeyError
    {"action": "mouse_move", "x": float("inf"), "y": 1},   # OverflowError
    {"action": "mouse_move", "x": "abc", "y": 1},          # ValueError
    {"action": "mouse_scroll", "amount": None},            # TypeError
], ids=["missing-field", "infinite", "not-a-number", "none"])
def test_a_malformed_input_message_is_an_input_error(message):
    # Every case fails while converting the message, before any wrapper call.
    with pytest.raises(InputDispatchError):
        dispatch_input(message)


def test_a_websocket_protocol_error_is_a_protocol_error():
    assert issubclass(WsProtocolError, ProtocolError)


def test_a_slow_handshake_does_not_block_other_viewers():
    host = RemoteDesktopHost(token="t", bind="127.0.0.1", port=0, frame_provider=lambda: None)
    host.start()
    silent = socket.create_connection(("127.0.0.1", host.port), timeout=5)  # never authenticates
    try:
        time.sleep(0.2)
        viewer = RemoteDesktopViewer(host="127.0.0.1", port=host.port, token="t",
                                     on_frame=lambda _frame: None, on_error=lambda _error: None)
        started = time.monotonic()
        viewer.connect(timeout=3.0)
        assert time.monotonic() - started < 3.0
        viewer.disconnect()
    finally:
        silent.close()
        host.stop(timeout=1.0)


def _one_shot_server(behaviour):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)

    def serve():
        connection, _ = listener.accept()
        with connection:
            connection.recv(4096)
            behaviour(connection)
        listener.close()

    threading.Thread(target=serve, daemon=True).start()
    return f"http://127.0.0.1:{listener.getsockname()[1]}/sessions/h/offer"


def test_a_signaling_server_that_hangs_up_is_a_signaling_error():
    url = _one_shot_server(lambda _connection: None)
    with pytest.raises(signaling_client.SignalingError):
        signaling_client._request("GET", url, timeout=3)


def test_a_signaling_read_timeout_is_a_signaling_error():
    url = _one_shot_server(lambda _connection: time.sleep(1.0))
    with pytest.raises(signaling_client.SignalingError):
        signaling_client._request("GET", url, timeout=0.3)


# --- 2026-11-26 review: peers that stall, trickle, or send what nothing expected ---

def _full_pair():
    """A connected pair whose first socket cannot send another byte."""
    left, right = socket.socketpair()
    left.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8192)
    left.settimeout(0.1)
    try:
        while True:
            left.sendall(b"x" * 65536)
    except OSError:
        pass
    left.settimeout(None)
    return left, right


def test_closing_a_websocket_whose_peer_stopped_reading_does_not_wait_for_it():
    """The CLOSE frame went into the full send buffer, so stop() hung for as long as the peer liked."""
    left, right = _full_pair()
    channel = WsMessageChannel(left, mask_outgoing=False)
    closer = threading.Thread(target=channel.close, daemon=True)
    closer.start()
    closer.join(timeout=5.0)
    stuck = closer.is_alive()
    right.close()
    assert not stuck


def test_closing_a_websocket_mid_write_does_not_wait_or_interleave():
    left, right = socket.socketpair()
    channel = WsMessageChannel(left, mask_outgoing=False)
    try:
        with channel._send_lock:           # another thread is inside a frame
            channel.close()
        right.settimeout(2)
        assert right.recv(64) == b""       # no CLOSE frame in the middle of it
    finally:
        right.close()


def test_closing_an_idle_websocket_still_says_goodbye():
    left, right = socket.socketpair()
    WsMessageChannel(left, mask_outgoing=False).close()
    right.settimeout(2)
    try:
        assert right.recv(64)[0] & 0x0F == ws_protocol.OPCODE_CLOSE
    finally:
        right.close()


def test_a_websocket_upgrade_sent_a_byte_at_a_time_is_bounded_as_a_whole():
    """Each byte reset the timeout, so one peer held a handshake slot for days."""
    server, client = socket.socketpair()
    server.settimeout(0.6)
    done = threading.Event()

    def trickle():
        while not done.wait(0.1):
            try:
                client.sendall(b"G")
            except OSError:
                return

    threading.Thread(target=trickle, daemon=True).start()
    started = time.monotonic()
    try:
        with pytest.raises((WsProtocolError, OSError)):
            ws_protocol.server_handshake(server)
        assert time.monotonic() - started < 3.0
        assert server.gettimeout() == pytest.approx(0.6)
    finally:
        done.set()
        server.close()
        client.close()


class _FlakyListener:
    """A listening socket whose first accept() fails the way an aborted connection does."""

    def __init__(self, real):
        self._real = real
        self.failures = 0

    def accept(self):
        if not self.failures:
            self.failures += 1
            raise ConnectionAbortedError("software caused connection abort")
        return self._real.accept()

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_an_aborted_connection_does_not_end_the_accept_loop():
    host = RemoteDesktopHost(token="t", bind="127.0.0.1", port=0, frame_provider=lambda: None)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(2)
    listener.settimeout(0.2)
    host._listen_sock = flaky = _FlakyListener(listener)
    stop = threading.Event()
    loop = threading.Thread(target=host._accept_loop, args=(stop,), daemon=True)
    loop.start()
    try:
        viewer = RemoteDesktopViewer(host="127.0.0.1", port=listener.getsockname()[1], token="t")
        viewer.connect(timeout=5.0)
        viewer.disconnect()
        assert flaky.failures == 1
    finally:
        stop.set()
        loop.join(timeout=3.0)
        host.stop(timeout=1.0)
        listener.close()


class _HostSocket:
    """What a viewer reads from a hostile host, and whether it was closed."""

    def __init__(self, data):
        self._data = data
        self.closed = False

    def recv(self, count):
        chunk, self._data = self._data[:count], self._data[count:]
        return chunk

    def sendall(self, data):
        del data

    def settimeout(self, timeout):
        del timeout

    def close(self):
        self.closed = True


@pytest.mark.parametrize("data", [
    encode_frame(MessageType.AUTH_CHALLENGE, b"short"),
    encode_frame(MessageType.AUTH_CHALLENGE, b"n" * 32) + encode_frame(MessageType.AUTH_FAIL, b"no"),
    encode_frame(MessageType.AUTH_CHALLENGE, b"n" * 32) + encode_frame(MessageType.AUTH_OK, b"[" * 100_000),
    encode_frame(MessageType.AUTH_CHALLENGE, b"n" * 32) + encode_frame(
        MessageType.AUTH_OK, b'{"resume_ttl": 1' + b"0" * 400 + b"}"),
], ids=["bad-nonce", "refused", "nested-json", "huge-ttl"])
def test_a_failed_connect_closes_the_wrapped_socket_and_stays_in_the_family(monkeypatch, data):
    """wrap_socket() detaches the raw socket, so closing only that one leaked the TLS connection."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    wrapped = _HostSocket(data)
    viewer = RemoteDesktopViewer(host="127.0.0.1", port=listener.getsockname()[1], token="t",
                                 expected_host_id="123456789")
    monkeypatch.setattr(viewer, "_maybe_wrap_tls", lambda raw: wrapped)
    try:
        with pytest.raises(AuthenticationError):
            viewer.connect(timeout=2.0)
        assert wrapped.closed
    finally:
        listener.close()


_UNPARSABLE = [b"[" * 100_000, b'{"text": ' + b"1" * 5000 + b"}"]


@pytest.mark.parametrize("payload", _UNPARSABLE, ids=["nested", "huge-int"])
@pytest.mark.parametrize("message", [MessageType.INPUT, MessageType.CHAT, MessageType.CLIPBOARD,
                                     MessageType.FILE_BEGIN, MessageType.FILE_END])
def test_json_the_parser_gives_up_on_does_not_end_the_session(message, payload):
    """RecursionError and the int-digit limit are not JSONDecodeError; they ended the receive thread."""
    host = RemoteDesktopHost(token="t", bind="127.0.0.1", port=0, frame_provider=lambda: None,
                             on_chat=lambda _sender, _text: None)
    handler = _ClientHandler(host, None, ("127.0.0.1", 1))
    handler.authenticated = True
    handler._route_incoming(message, payload)

    viewer = RemoteDesktopViewer(host="h", port=1, token="t", on_chat=lambda _s, _t: None)
    viewer._handle_clipboard_payload(payload)
    for receive in (viewer._on_recv_chat, viewer._on_recv_cursor, viewer._on_recv_usb_list):
        receive(payload, message)
    viewer._handle_file_payload(MessageType.FILE_BEGIN, payload)


def test_clipboard_text_with_a_lone_surrogate_does_not_end_the_session():
    applied = []
    host = RemoteDesktopHost(token="t", bind="127.0.0.1", port=0, frame_provider=lambda: None)
    host._apply_clipboard = lambda kind, data: applied.append((kind, data))
    handler = _ClientHandler(host, None, ("127.0.0.1", 1))
    handler.authenticated = True
    handler._route_incoming(MessageType.CLIPBOARD, b'{"kind": "text", "text": "a\\ud800"}')
    assert applied == [("text", "a\ud800")]


def test_an_action_that_is_not_text_is_an_input_error():
    with pytest.raises(InputDispatchError):
        dispatch_input({"action": ["mouse_move"]})


class _RecordingChannel:
    def __init__(self, refuse=()):
        self.sent = []
        self._refuse = refuse

    def send_typed(self, message_type, payload):
        if payload in self._refuse:
            raise ProtocolError("payload too large")
        self.sent.append((message_type, payload))

    def close(self):
        pass


def test_a_frame_too_large_to_send_does_not_silence_the_viewer():
    """ProtocolError ended the sender thread while the viewer stayed connected and in control."""
    host = RemoteDesktopHost(token="t", bind="127.0.0.1", port=0, frame_provider=lambda: None)
    channel = _RecordingChannel(refuse=(b"huge",))
    handler = _ClientHandler(host, channel, ("127.0.0.1", 1))
    handler.authenticated = True
    host._latest_frame, host._latest_seq = b"huge", 1
    sender = threading.Thread(target=handler._send_loop, daemon=True)
    sender.start()
    try:
        time.sleep(0.2)
        with host._frame_cond:
            host._latest_frame, host._latest_seq = b"small", 2
            host._frame_cond.notify_all()
        deadline = time.monotonic() + 3.0
        while not channel.sent and time.monotonic() < deadline:
            time.sleep(0.02)
        assert (MessageType.FRAME, b"small") in channel.sent
    finally:
        handler.stop()
        sender.join(timeout=2.0)


def test_a_mouse_backend_error_skips_a_tick_instead_of_ending_the_cursor_stream(monkeypatch):
    from je_auto_control.wrapper import auto_control_mouse
    from je_auto_control.utils.exception.exceptions import AutoControlMouseException

    def fail():
        raise AutoControlMouseException("no pointer here")

    monkeypatch.setattr(auto_control_mouse, "get_mouse_position", fail)
    assert host_capture._default_cursor_provider()() is None


def test_a_capture_backend_error_does_not_end_the_capture_loop():
    frames = iter([AutoControlScreenException("screen locked"), b"frame"])
    stop = threading.Event()

    def provide():
        item = next(frames, None)
        if item is None:
            stop.set()
            return b"frame"
        if isinstance(item, Exception):
            raise item
        return item

    host = RemoteDesktopHost(token="t", bind="127.0.0.1", port=0, fps=200.0, frame_provider=provide)
    host._capture_loop(stop)
    assert host.latest_frame() == b"frame"


def test_a_stalled_viewer_does_not_freeze_the_cursor_of_the_others():
    """The cursor thread wrote to every socket itself, so one full buffer stopped it for everyone."""
    counter = iter(range(1_000_000))
    frame = [b"\x00" * (4 * 1024 * 1024)]
    host = RemoteDesktopHost(token="t", bind="127.0.0.1", port=0, fps=30.0,
                             frame_provider=lambda: frame[0] + str(next(counter)).encode(),
                             cursor_provider=lambda: (next(counter), 1))
    host.start()
    stalled = socket.create_connection(("127.0.0.1", host.port), timeout=5)
    seen = []
    viewer = RemoteDesktopViewer(host="127.0.0.1", port=host.port, token="t",
                                 on_cursor=lambda x, y: seen.append(x))
    try:
        _type, nonce = read_message(stalled)
        stalled.sendall(encode_frame(MessageType.AUTH_RESPONSE, compute_response("t", nonce)))
        deadline = time.monotonic() + 5.0
        while host.connected_clients < 1 and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(0.5)                 # its buffers are full by now; it never reads again
        viewer.connect(timeout=5.0)
        before = len(seen)
        deadline = time.monotonic() + 5.0
        while len(seen) < before + 10 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert len(seen) >= before + 10
    finally:
        viewer.disconnect(timeout=1.0)
        stalled.close()
        host.stop(timeout=1.0)


def test_an_encoder_error_does_not_end_the_capture_loop():
    """PyAV's ExternalError (an encoder that cannot open) derives from Exception alone."""
    class EncoderError(Exception):
        pass

    class _Codec:
        name = "h264"
        calls = 0

        def encode_jpeg(self, _jpeg):
            _Codec.calls += 1
            if _Codec.calls == 1:
                raise EncoderError("avcodec_open2")
            stop.set()
            return [b"packet"]

    stop = threading.Event()
    frames = iter(range(1000))
    host = RemoteDesktopHost(token="t", bind="127.0.0.1", port=0, fps=200.0, codec_provider=_Codec(),
                             frame_provider=lambda: str(next(frames)).encode())
    host._capture_loop(stop)
    assert host.latest_frame() == b"\x02packet"
