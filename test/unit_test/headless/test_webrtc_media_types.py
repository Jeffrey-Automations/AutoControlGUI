"""Exercise PyAV media boundaries and aiortc subclass contracts without devices."""
import asyncio
from types import SimpleNamespace

import pytest

av = pytest.importorskip("av")
pytest.importorskip("aiortc")

from aiortc.codecs.h264 import H264Encoder  # noqa: E402  # reason: optional media dependencies
from je_auto_control.utils.remote_desktop import (  # noqa: E402  # reason: optional media dependencies
    hw_codec, session_recorder,
)
from je_auto_control.utils.remote_desktop.webrtc_transport import (  # noqa: E402  # reason: optional media dependencies
    ScreenVideoTrack,
)


def test_nonvideo_hardware_codec_is_not_configured(monkeypatch):
    context = SimpleNamespace()
    fake_av = SimpleNamespace(
        CodecContext=SimpleNamespace(create=lambda *args: context),
        VideoCodecContext=av.VideoCodecContext,
    )
    monkeypatch.setattr(hw_codec, "av", fake_av)
    with pytest.raises(ValueError, match="requires a video codec"):
        hw_codec._open_configured("audio-codec", 64, 64, 1_000_000, 30)
    assert vars(context) == {}


@pytest.mark.parametrize("fail_add", [False, True])
def test_recording_releases_container_when_video_stream_cannot_be_created(monkeypatch, tmp_path, fail_add):
    closed = []

    def add_stream(*args, **kwargs):
        if fail_add:
            raise ValueError("unsupported codec")
        return object()

    container = SimpleNamespace(add_stream=add_stream, close=lambda: closed.append(True))
    monkeypatch.setattr(session_recorder.av, "open", lambda *args, **kwargs: container)
    recorder = session_recorder.SessionRecorder(str(tmp_path / "recording.mp4"))
    recorder.write_frame(av.VideoFrame(64, 64))
    assert closed == [True]
    assert not recorder.is_active and not recorder.has_output
    recorder.stop()
    assert closed == [True]


def test_h264_patch_encodes_and_restores_the_original_method(monkeypatch):
    original = H264Encoder._encode_frame
    monkeypatch.setattr(hw_codec, "_original_encode_frame", None)
    monkeypatch.setattr(hw_codec, "_active_codec", None)
    monkeypatch.setattr(hw_codec, "_can_open", lambda name: True)
    try:
        assert hw_codec.install_hardware_codec("libx264")
        frame = av.VideoFrame(64, 64, "yuv420p")
        for plane in frame.planes:
            plane.update(bytes(plane.buffer_size))
        encoded = list(H264Encoder()._encode_frame(frame, True))
        assert encoded and all(isinstance(packet, bytes) and packet for packet in encoded)
    finally:
        hw_codec.uninstall_hardware_codec()
    assert H264Encoder._encode_frame is original


def test_recording_keeps_video_frames_readable_after_flush(tmp_path):
    path = tmp_path / "recording.mp4"
    recorder = session_recorder.SessionRecorder(str(path))
    for _ in range(2):
        frame = av.VideoFrame(64, 64, "yuv420p")
        for plane in frame.planes:
            plane.update(bytes(plane.buffer_size))
        recorder.write_frame(frame)
    assert recorder.is_active
    recorder.stop()
    with av.open(str(path)) as saved:
        frames = list(saved.decode(video=0))
    assert len(frames) == 2
    assert {(frame.width, frame.height) for frame in frames} == {(64, 64)}


def test_screen_track_own_clock_does_not_replace_inherited_timestamp_storage():
    track = ScreenVideoTrack(show_cursor=False)
    try:
        own_pts, own_base = track._frame_timestamp()
        base_pts, base_time = asyncio.run(track.next_timestamp())
        assert own_pts == base_pts == 0
        assert own_base == base_time
        next_pts, _ = track._frame_timestamp()
        assert next_pts > own_pts
    finally:
        track.stop()
