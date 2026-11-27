"""Phase 5.1 + 5.2: chat broadcast and multi-viewer cursor relay tests."""
import threading
import time
from io import BytesIO

import pytest

from je_auto_control.utils.remote_desktop.host import RemoteDesktopHost
from je_auto_control.utils.remote_desktop.viewer import RemoteDesktopViewer


def _make_jpeg() -> bytes:
    from PIL import Image
    img = Image.new("RGB", (16, 16), color=(0, 0, 0))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return buf.getvalue()


@pytest.fixture
def jpeg_bytes():
    return _make_jpeg()


def _await_clients(host, expected: int = 1, timeout: float = 5.0) -> None:
    """Wait until the host has authenticated ``expected`` viewers.

    ``viewer.connect()`` returns once the *client* side is up; the host's accept
    thread may not have authenticated the viewer yet, so a broadcast issued
    immediately can reach zero clients (reliably so on a slow CI container). This
    closes that race using the host's own authenticated-client count.
    """
    deadline = time.monotonic() + timeout
    while host.connected_clients < expected and time.monotonic() < deadline:
        time.sleep(0.02)


# --- Phase 5.2: chat ----------------------------------------------------

def test_host_broadcasts_chat_to_viewer(jpeg_bytes):
    received = []
    lock = threading.Lock()

    def on_chat(sender: str, text: str) -> None:
        with lock:
            received.append((sender, text))

    host = RemoteDesktopHost(
        token="t", bind="127.0.0.1", port=0, fps=30.0,
        frame_provider=lambda: jpeg_bytes,
    )
    host.start()
    try:
        viewer = RemoteDesktopViewer(
            host="127.0.0.1", port=host.port, token="t",
            on_chat=on_chat,
        )
        viewer.connect(timeout=5.0)
        try:
            _await_clients(host)
            sent = host.broadcast_chat("hello viewer")
            assert sent == 1
            deadline = time.monotonic() + 2.0
            while not received and time.monotonic() < deadline:
                time.sleep(0.05)
            with lock:
                assert ("host", "hello viewer") in received
        finally:
            viewer.disconnect(timeout=1.0)
    finally:
        host.stop(timeout=1.0)


def test_viewer_can_chat_back_to_host(jpeg_bytes):
    received = []
    lock = threading.Lock()

    def host_on_chat(sender: str, text: str) -> None:
        with lock:
            received.append((sender, text))

    host = RemoteDesktopHost(
        token="t", bind="127.0.0.1", port=0, fps=30.0,
        frame_provider=lambda: jpeg_bytes,
        on_chat=host_on_chat,
    )
    host.start()
    try:
        viewer = RemoteDesktopViewer(host="127.0.0.1", port=host.port, token="t")
        viewer.connect(timeout=5.0)
        try:
            _await_clients(host)
            viewer.send_chat("ping from viewer", sender="alice")
            deadline = time.monotonic() + 2.0
            while not received and time.monotonic() < deadline:
                time.sleep(0.05)
            with lock:
                assert ("alice", "ping from viewer") in received
        finally:
            viewer.disconnect(timeout=1.0)
    finally:
        host.stop(timeout=1.0)


def test_broadcast_chat_with_empty_text_is_noop(jpeg_bytes):
    host = RemoteDesktopHost(
        token="t", bind="127.0.0.1", port=0, fps=30.0,
        frame_provider=lambda: jpeg_bytes,
    )
    host.start()
    try:
        assert host.broadcast_chat("") == 0
        assert host.broadcast_chat(None) == 0  # type: ignore[arg-type]  # NOSONAR python:S5655  # reason: intentional bad-type negative test
    finally:
        host.stop(timeout=1.0)


# --- Phase 5.1: multi-viewer cursor relay -------------------------------

def test_viewer_cursor_payload_routes_to_separate_callback(jpeg_bytes):
    """A CURSOR message with viewer_id fires on_viewer_cursor, not on_cursor."""
    main_cursor = []
    viewer_cursors = []
    lock = threading.Lock()

    host = RemoteDesktopHost(
        token="t", bind="127.0.0.1", port=0, fps=30.0,
        frame_provider=lambda: jpeg_bytes,
        # Disable host cursor broadcast so we only see what we explicitly send.
        enable_cursor_broadcast=False,
    )
    host.start()
    try:
        viewer = RemoteDesktopViewer(
            host="127.0.0.1", port=host.port, token="t",
            on_cursor=lambda x, y: main_cursor.append((x, y)),
            on_viewer_cursor=lambda vid, x, y:
                viewer_cursors.append((vid, x, y)),
        )
        viewer.connect(timeout=5.0)
        try:
            _await_clients(host)
            # Simulate MultiViewerHost relaying another operator's cursor.
            host.broadcast_viewer_cursor("alice", 200, 300)
            deadline = time.monotonic() + 2.0
            while not viewer_cursors and time.monotonic() < deadline:
                time.sleep(0.05)
            with lock:
                assert ("alice", 200, 300) in viewer_cursors
                # The main on_cursor callback must NOT have fired — that
                # one is reserved for the host's own pointer.
                assert main_cursor == []
        finally:
            viewer.disconnect(timeout=1.0)
    finally:
        host.stop(timeout=1.0)


# --- a viewer that stopped reading must not hold the others --------------

class _StalledChannel:
    """A channel whose sends block until released, like a full TCP buffer."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.sent = []

    def send_typed(self, msg_type, payload) -> None:
        self.release.wait(timeout=10.0)
        self.sent.append((msg_type, payload))

    def close(self) -> None:
        self.release.set()


class _RecordingChannel:
    def __init__(self) -> None:
        self.sent = []

    def send_typed(self, msg_type, payload) -> None:
        self.sent.append((msg_type, payload))

    def close(self) -> None:
        """Nothing to release."""


def _host_with_viewers(*channels):
    from je_auto_control.utils.remote_desktop.host_client import _ClientHandler
    host = RemoteDesktopHost(token="t", host_id="123456789", frame_provider=lambda: b"frame",
                             input_dispatcher=lambda *_args: None, enable_cursor_broadcast=False)
    handlers = []
    for channel in channels:
        handler = _ClientHandler(host, channel, ("127.0.0.1", 1))
        handler.authenticated = True
        host._clients.append(handler)
        handlers.append(handler)
    return host, handlers


def _wait_for(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


@pytest.mark.parametrize("what", ["chat", "clipboard", "file"])
def test_a_stalled_viewer_does_not_block_host_sends_to_the_others(what, tmp_path):
    from je_auto_control.utils.remote_desktop.protocol import MessageType
    stalled, healthy = _StalledChannel(), _RecordingChannel()
    host, handlers = _host_with_viewers(stalled, healthy)
    source = tmp_path / "f.bin"
    source.write_bytes(b"x" * 10)
    send = {
        "chat": lambda: host.broadcast_chat("hi"),
        "clipboard": lambda: host.broadcast_clipboard_text("clip"),
        "file": lambda: host.send_file_to_viewers(str(source), "f.bin"),
    }[what]
    expected = {"chat": MessageType.CHAT, "clipboard": MessageType.CLIPBOARD, "file": MessageType.FILE_END}[what]
    try:
        started = time.monotonic()
        assert send() == 2
        assert time.monotonic() - started < 1.0
        assert _wait_for(lambda: expected in [kind for kind, _ in healthy.sent])
        assert stalled.sent == []
    finally:
        for handler in handlers:
            handler.stop()


def test_a_stalled_viewers_queue_is_bounded_and_overflow_is_not_counted():
    stalled, healthy = _StalledChannel(), _RecordingChannel()
    host, handlers = _host_with_viewers(stalled, healthy)
    try:
        counts = []
        # One job held by the blocked send, a full queue behind it, then overflow.
        for index in range(handlers[0]._OUTGOING_QUEUE_MAXSIZE + 2):
            counts.append(host.broadcast_chat(f"m{index}"))
            assert _wait_for(lambda: len(healthy.sent) == index + 1)
        assert counts[0] == 2
        assert counts[-1] == 1
    finally:
        for handler in handlers:
            handler.stop()
