"""A slow TCP viewer of an H.264 stream never decodes a P-frame without its reference.

The host kept only the newest packet, so a viewer that fell behind skipped
P-frames and its decoder showed corrupted video until the next keyframe.
Now a viewer that has to drop a frame is sent nothing until a keyframe, and
the encoder is asked (rate-limited) for one. A fake encoder and fake frames
stand in for PyAV and the screen; the JPEG path is unchanged.
"""
import io
import struct
import threading
import time
from typing import List, Optional, Tuple

import pytest

from je_auto_control.utils.remote_desktop.delta_frames import (
    DELTA_BACKLOG_FRAMES, DeltaFrameGate, DeltaFrameHistory, EncodedFrame,
    KeyframeRequests,
)
from je_auto_control.utils.remote_desktop.host import RemoteDesktopHost
from je_auto_control.utils.remote_desktop.host_client import _ClientHandler
from je_auto_control.utils.remote_desktop.protocol import MessageType, ProtocolError
from je_auto_control.utils.remote_desktop.video_codec import is_keyframe_packet

_IDR, _NON_IDR = 0x65, 0x41   # H.264 NAL headers: type 5 (IDR) and type 1


def _packet(index: int, keyframe: bool) -> bytes:
    return b"\x00\x00\x00\x01" + bytes([_IDR if keyframe else _NON_IDR]) + struct.pack(">I", index)


def _decode(wire: bytes) -> Tuple[int, bool]:
    """(index, keyframe) of a tagged FRAME body the fake encoder produced."""
    assert wire[0] == 0x02, "an H.264 frame carries the h264 tag"
    packet = wire[1:]
    return struct.unpack(">I", packet[-4:])[0], is_keyframe_packet("h264", packet)


class _FakeH264:
    """Numbers its packets; only the first and forced ones are keyframes."""

    name = "h264"

    def __init__(self) -> None:
        self.index = 0
        self.requests = 0
        self._force = False

    def encode_jpeg(self, _jpeg: bytes) -> List[bytes]:
        keyframe = self.index == 0 or self._force
        self._force = False
        packet = _packet(self.index, keyframe)
        self.index += 1
        return [packet]

    def request_keyframe(self) -> bool:
        self.requests += 1
        self._force = True
        return True


class _Channel:
    """Records what the sender sends; can hold the first frame or refuse a payload."""

    def __init__(self, hold_first_frame: bool = False, refuse: Optional[bytes] = None) -> None:
        self.sent: List[Tuple[MessageType, bytes]] = []
        self.release = threading.Event()
        self.holding = threading.Event()
        self._hold = hold_first_frame
        self._refuse = refuse

    def send_typed(self, kind: MessageType, payload: bytes) -> None:
        if kind is MessageType.FRAME and self._hold:
            self._hold = False
            self.holding.set()
            assert self.release.wait(5.0)
        if self._refuse is not None and payload == self._refuse:
            raise ProtocolError("payload over the cap")
        self.sent.append((kind, payload))

    def frames(self) -> List[bytes]:
        return [payload for kind, payload in self.sent if kind is MessageType.FRAME]

    def settimeout(self, _timeout) -> None:
        pass

    def close(self) -> None:
        pass


def _wait_until(predicate, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _h264_host(codec, frame_provider, fps: float = 200.0) -> RemoteDesktopHost:
    return RemoteDesktopHost(token="t", bind="127.0.0.1", port=0, fps=fps, host_id="123456789",
                             codec_provider=codec, frame_provider=frame_provider,
                             input_dispatcher=lambda _message: None, enable_cursor_broadcast=False)


def _start_sender(host: RemoteDesktopHost, channel: _Channel) -> Tuple[_ClientHandler, threading.Thread]:
    handler = _ClientHandler(host, channel, ("127.0.0.1", 1))
    handler.authenticated = True
    sender = threading.Thread(target=handler._send_loop, daemon=True)
    sender.start()
    return handler, sender


def _assert_decodable(frames: List[Tuple[int, bool]]) -> None:
    """Every frame is a keyframe or the one right after the frame before it."""
    assert frames and frames[0][1], f"the first frame is not a keyframe: {frames[:3]}"
    for (previous, _), (index, keyframe) in zip(frames, frames[1:]):
        assert keyframe or index == previous + 1, (
            f"P-frame {index} sent after frame {previous}: its reference was dropped")


def _publish(host: RemoteDesktopHost, *frames: Tuple[int, bool]) -> None:
    for index, keyframe in frames:
        with host._frame_cond:
            host._latest_seq += 1
            wire = b"\x02" + _packet(index, keyframe)
            host._latest_frame = wire
            host._delta_history.append(EncodedFrame(host._latest_seq, wire, keyframe))
            host._frame_cond.notify_all()


# --- the gate, the backlog and the request limiter ------------------------

def _history(*frames: Tuple[int, bool]) -> DeltaFrameHistory:
    history = DeltaFrameHistory()
    for seq, keyframe in frames:
        history.append(EncodedFrame(seq, b"%d" % seq, keyframe))
    return history


def test_a_gate_in_step_passes_every_frame_in_order():
    gate = DeltaFrameGate()
    assert gate.take(_history((1, True), (2, False), (3, False))) == [b"1", b"2", b"3"]
    assert gate.take(_history((1, True), (2, False), (3, False), (4, False))) == [b"4"]
    assert not gate.needs_keyframe


def test_after_a_gap_nothing_is_sent_until_a_keyframe():
    gate = DeltaFrameGate()
    gate.take(_history((1, True)))
    assert gate.take(_history((5, False), (6, False))) == []
    assert gate.needs_keyframe and gate.resyncs == 1
    assert gate.take(_history((5, False), (6, False), (7, False), (8, True), (9, False))) == [b"8", b"9"]
    assert not gate.needs_keyframe


def test_a_new_viewer_starts_at_the_newest_keyframe_in_the_backlog():
    gate = DeltaFrameGate()
    assert gate.take(_history((3, False), (4, True), (5, False))) == [b"4", b"5"]
    fresh = DeltaFrameGate()
    assert fresh.take(_history((3, False), (5, False))) == [] and fresh.needs_keyframe


def test_a_frame_that_was_not_delivered_drops_the_frames_after_it():
    gate = DeltaFrameGate()
    gate.take(_history((1, True), (2, False)))
    gate.lose()
    assert gate.take(_history((1, True), (2, False), (3, False))) == []
    assert gate.take(_history((3, False), (4, True))) == [b"4"]


def test_the_backlog_is_bounded():
    history = DeltaFrameHistory()
    for seq in range(1, 100):
        history.append(EncodedFrame(seq, b"", False))
    assert len(history.after(0)) == DELTA_BACKLOG_FRAMES
    with pytest.raises(ValueError):
        DeltaFrameHistory(0)


def test_keyframe_requests_are_rate_limited_host_wide():
    now = [100.0]
    requests = KeyframeRequests(min_interval_s=1.0, clock=lambda: now[0])
    assert requests.request() is True
    assert requests.request() is False   # already pending
    assert requests.take() is True and requests.take() is False
    now[0] += 0.5
    assert requests.request() is False   # too soon after the last one
    now[0] += 0.6
    assert requests.request() is True


@pytest.mark.parametrize("codec, packet, expected", [
    ("h264", b"\x00\x00\x00\x01\x67\x00\x00\x00\x01\x68\x00\x00\x01\x65\x88", True),
    ("h264", b"\x00\x00\x01\x41\x9a", False),
    ("h264", b"", False),
    ("hevc", b"\x00\x00\x00\x01\x26\x01", True),     # IDR_W_RADL (19)
    ("hevc", b"\x00\x00\x00\x01\x02\x01", False),    # TRAIL_R (1)
    ("jpeg", b"\xff\xd8", True),
])
def test_keyframes_are_recognised_from_the_bitstream(codec, packet, expected):
    assert is_keyframe_packet(codec, packet) is expected


# --- the host ---------------------------------------------------------------

def test_a_slow_viewer_resumes_at_a_keyframe_and_never_gets_a_broken_p_frame():
    codec = _FakeH264()
    counter = iter(range(1_000_000))
    host = _h264_host(codec, lambda: b"frame-%d" % next(counter))
    channel = _Channel(hold_first_frame=True)
    stop = threading.Event()
    capture = threading.Thread(target=host._capture_loop, args=(stop,), daemon=True)
    handler, sender = _start_sender(host, channel)
    capture.start()
    try:
        assert channel.holding.wait(5.0)
        # The viewer stops reading while the backlog moves well past it.
        assert _wait_until(lambda: codec.index > 4 * DELTA_BACKLOG_FRAMES)
        channel.release.set()
        assert _wait_until(lambda: sum(key for _, key in map(_decode, channel.frames())) >= 2
                           and len(channel.frames()) >= 6)
    finally:
        stop.set()
        handler.stop()
        sender.join(timeout=2.0)
        capture.join(timeout=2.0)
    frames = [_decode(frame) for frame in channel.frames()]
    _assert_decodable(frames)
    assert codec.requests >= 1, "the encoder was never asked for a keyframe"


def test_a_viewer_joining_mid_gop_waits_for_a_keyframe_and_asks_for_one():
    host = _h264_host(_FakeH264(), lambda: b"")
    _publish(host, (0, True), *((index, False) for index in range(1, 3 * DELTA_BACKLOG_FRAMES)))
    channel = _Channel()
    handler, sender = _start_sender(host, channel)
    try:
        assert _wait_until(lambda: host._keyframe_requests.take(), seconds=3.0)
        assert channel.frames() == []
        _publish(host, (100, True), (101, False))
        assert _wait_until(lambda: len(channel.frames()) == 2)
    finally:
        handler.stop()
        sender.join(timeout=2.0)
    assert [_decode(frame) for frame in channel.frames()] == [(100, True), (101, False)]


def test_a_frame_too_large_to_send_drops_the_p_frames_that_depend_on_it():
    host = _h264_host(_FakeH264(), lambda: b"")
    channel = _Channel(refuse=b"\x02" + _packet(2, False))
    handler, sender = _start_sender(host, channel)
    try:
        _publish(host, (1, True), (2, False), (3, False))
        assert _wait_until(lambda: host._keyframe_requests.take(), seconds=3.0)
        _publish(host, (4, False), (5, True), (6, False))
        assert _wait_until(lambda: len(channel.frames()) == 3)
    finally:
        handler.stop()
        sender.join(timeout=2.0)
    assert [_decode(frame) for frame in channel.frames()] == [(1, True), (5, True), (6, False)]


def test_a_requested_keyframe_is_encoded_even_when_the_screen_has_not_changed():
    codec = _FakeH264()
    host = _h264_host(codec, lambda: b"static", fps=100.0)
    stop = threading.Event()
    capture = threading.Thread(target=host._capture_loop, args=(stop,), daemon=True)
    capture.start()
    try:
        assert _wait_until(lambda: host._latest_seq == 1)
        time.sleep(0.1)
        assert host._latest_seq == 1, "an unchanged screen is still not re-encoded"
        host._request_keyframe()
        assert _wait_until(lambda: host._latest_seq == 2)
    finally:
        stop.set()
        capture.join(timeout=2.0)
    assert codec.requests == 1
    assert _decode(host.latest_frame()) == (1, True)


def test_the_jpeg_stream_still_sends_only_the_newest_frame():
    host = RemoteDesktopHost(token="t", bind="127.0.0.1", port=0, host_id="123456789",
                             frame_provider=lambda: b"", enable_cursor_broadcast=False)
    assert host._delta_history is None
    host._latest_frame, host._latest_seq = b"jpeg-3", 3
    channel = _Channel(hold_first_frame=True)
    handler, sender = _start_sender(host, channel)
    try:
        assert channel.holding.wait(5.0)
        for seq in range(4, 10):   # the viewer is not reading meanwhile
            with host._frame_cond:
                host._latest_frame, host._latest_seq = b"jpeg-%d" % seq, seq
                host._frame_cond.notify_all()
        channel.release.set()
        assert _wait_until(lambda: channel.frames() == [b"jpeg-3", b"jpeg-9"])
    finally:
        handler.stop()
        sender.join(timeout=2.0)
    host._request_keyframe()
    assert host._keyframe_requests.take() is False


def test_the_h264_encoder_turns_a_keyframe_request_into_an_idr():
    pytest.importorskip("av")
    image_module = pytest.importorskip("PIL.Image")
    from je_auto_control.utils.remote_desktop.video_codec import H264CodecProvider

    def jpeg(shade: int) -> bytes:
        buffer = io.BytesIO()
        image_module.new("RGB", (64, 48), (shade, 40, 90)).save(buffer, format="JPEG")
        return buffer.getvalue()

    provider = H264CodecProvider(fps=30, gop_size=600)
    try:
        kinds = [[provider.is_keyframe(p) for p in provider.encode_jpeg(jpeg(shade))]
                 for shade in range(0, 40, 10)]
        assert provider.request_keyframe() is True
        forced = [provider.is_keyframe(p) for p in provider.encode_jpeg(jpeg(200))]
    finally:
        provider.close()
    assert kinds[0] == [True] and all(kind == [False] for kind in kinds[1:])
    assert forced == [True]
