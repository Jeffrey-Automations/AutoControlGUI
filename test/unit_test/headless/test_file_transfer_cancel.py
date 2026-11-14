"""A file transfer already sending stops at the next chunk when it is cancelled, and the host keeps nothing.

``send_file`` streamed the whole file whatever happened: closing the Remote
Desktop page, disconnecting, or stopping the task that ran it left the upload
going to its last byte. It now checks between chunks and, once stopped, sends a
``cancelled`` end so the receiver discards its part file.
"""
import threading
from concurrent.futures import CancelledError

import pytest

from je_auto_control.utils.exception.cancellation import CancellationToken, cancellation_scope
from je_auto_control.utils.remote_desktop.file_transfer import FileReceiver, decode_end, send_file
from je_auto_control.utils.remote_desktop.protocol import MessageType

_CHUNK = 1024


class _Wire:
    """A channel straight into a real receiver; ``on_chunk(n)`` runs after the n-th chunk."""

    def __init__(self, receiver, on_chunk=None):
        self.receiver, self.on_chunk, self.sent, self.chunks = receiver, on_chunk, [], 0

    def send_typed(self, kind, payload):
        self.sent.append(kind)
        if kind is MessageType.FILE_BEGIN:
            self.receiver.handle_begin(payload)
        elif kind is MessageType.FILE_CHUNK:
            self.receiver.handle_chunk(payload)
            self.chunks += 1
            if self.on_chunk is not None:
                self.on_chunk(self.chunks)
        elif kind is MessageType.FILE_END:
            self.last_end = decode_end(payload)
            self.receiver.handle_end(payload)


@pytest.fixture
def transfer(tmp_path):
    source = tmp_path / "big.bin"
    source.write_bytes(b"x" * (_CHUNK * 10))
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    outcomes = []
    receiver = FileReceiver(on_complete=lambda tid, ok, error, dest: outcomes.append((ok, error)), base_dir=inbox)
    return source, inbox, receiver, outcomes


def test_a_transfer_cancelled_mid_file_stops_and_the_receiver_keeps_nothing(transfer):
    source, inbox, receiver, outcomes = transfer
    stop = threading.Event()
    wire = _Wire(receiver, on_chunk=lambda n: stop.set() if n == 3 else None)
    with pytest.raises(CancelledError):
        send_file(wire, str(source), "big.bin", chunk_size=_CHUNK, cancelled=stop.is_set)
    assert wire.chunks == 3                                  # not the other seven
    assert wire.last_end[1] == "cancelled"
    assert outcomes == [(False, "cancelled by the sender")]
    assert list(inbox.iterdir()) == []                       # no file, no part file


def test_a_transfer_cancelled_before_it_starts_sends_nothing(transfer):
    source, _inbox, receiver, _outcomes = transfer
    wire = _Wire(receiver)
    with pytest.raises(CancelledError):
        send_file(wire, str(source), "big.bin", chunk_size=_CHUNK, cancelled=lambda: True)
    assert wire.sent == []


def test_the_callers_cancellation_scope_stops_it_by_default(transfer):
    source, inbox, receiver, _outcomes = transfer
    token = CancellationToken(task_id=1)
    wire = _Wire(receiver, on_chunk=lambda n: token.cancel() if n == 2 else None)
    with cancellation_scope(token), pytest.raises(CancelledError):
        send_file(wire, str(source), "big.bin", chunk_size=_CHUNK)
    assert wire.chunks == 2
    assert list(inbox.iterdir()) == []


def test_an_uncancelled_transfer_arrives_whole(transfer):
    source, inbox, receiver, outcomes = transfer
    result = send_file(_Wire(receiver), str(source), "big.bin", chunk_size=_CHUNK)
    assert result.success and result.bytes_sent == _CHUNK * 10
    assert outcomes == [(True, None)]
    assert (inbox / "big.bin").read_bytes() == source.read_bytes()


def test_a_closed_channel_does_not_hide_the_cancellation(transfer):
    source, _inbox, receiver, _outcomes = transfer
    stop = threading.Event()

    class _Closing(_Wire):
        def send_typed(self, kind, payload):
            if kind is MessageType.FILE_END and stop.is_set():
                raise ConnectionError("the session is gone")
            super().send_typed(kind, payload)

    wire = _Closing(receiver, on_chunk=lambda n: stop.set())
    with pytest.raises(CancelledError):
        send_file(wire, str(source), "big.bin", chunk_size=_CHUNK, cancelled=stop.is_set)


def test_the_viewer_tabs_upload_task_stops_its_transfer_when_cancelled(transfer, monkeypatch):
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QWidget
    QApplication.instance() or QApplication([])
    try:
        from je_auto_control.gui.remote_desktop import view_upload
        from je_auto_control.gui.remote_desktop.view_lifetime import ViewLifetime
    except ImportError:
        pytest.skip("the remote desktop GUI needs the webrtc extra")
    from headless._qt_settle import pump_until
    source, inbox, receiver, _outcomes = transfer
    second_chunk, release, done = threading.Event(), threading.Event(), threading.Event()

    def hold(n):
        if n == 2:
            second_chunk.set()
            assert release.wait(10.0)

    wire = _Wire(receiver, on_chunk=hold)

    class _Viewer:
        def send_file(self, source_path, dest_path, on_progress=None, *, cancelled=None):
            try:
                return send_file(wire, source_path, dest_path, chunk_size=_CHUNK, cancelled=cancelled)
            finally:
                done.set()

    owner = QWidget()
    try:
        handle = view_upload.start_upload(owner, _Viewer(), str(source), "big.bin", ViewLifetime(owner))
        assert second_chunk.wait(10.0)
        handle.cancel()                       # the panel closed or the session was dropped
        release.set()
        assert done.wait(10.0)
        assert pump_until(lambda: wire.chunks == 2 and getattr(wire, "last_end", None) is not None)
        assert wire.last_end[1] == "cancelled"
        assert list(inbox.iterdir()) == []
    finally:
        release.set()
        owner.deleteLater()
