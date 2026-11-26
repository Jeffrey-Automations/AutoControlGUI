"""A stop ends ``AC_assert_audio``'s recording window and ``AC_assert_video``'s decode.

``measure_audio_rms`` blocked in ``sounddevice.wait()`` for the whole window
and the video measure decoded every frame of the segment without looking at
a stop. A fake ``sounddevice`` module and a fake capture stand in for the
real device and file, so no microphone is opened and no video is read.
"""
import sys
import threading
import time
import types

import numpy as np
import pytest

from je_auto_control.utils.executor.run_control import ExecutionStopped, StopToken, stoppable_run
from je_auto_control.utils.media_assert import media

_PROMPT_S = 0.7


def _stop_soon(token: StopToken) -> None:
    timer = threading.Timer(0.1, token.stop, ("test",))
    timer.daemon = True
    timer.start()


@pytest.fixture
def fake_sounddevice(monkeypatch):
    stopped = threading.Event()
    module = types.ModuleType("sounddevice")
    module.PortAudioError = type("PortAudioError", (Exception,), {})
    module.rec = lambda frames, **_kwargs: np.zeros((frames, 1))
    module.wait = lambda: stopped.wait(1.0)        # a 1 s recording window
    module.stop = stopped.set
    monkeypatch.setitem(sys.modules, "sounddevice", module)
    return stopped


def test_a_stop_ends_the_audio_window_and_stops_the_stream(fake_sounddevice):
    token = StopToken("audio-stop")
    _stop_soon(token)
    began = time.monotonic()
    with stoppable_run(token=token), pytest.raises(ExecutionStopped):
        media.measure_audio_rms(duration_s=1.0, samplerate=100)
    assert time.monotonic() - began < _PROMPT_S
    assert fake_sounddevice.is_set()               # the stream was stopped, not left recording


def test_outside_a_run_the_window_is_recorded(fake_sounddevice):
    fake_sounddevice.set()                         # the window has already elapsed
    assert media.measure_audio_rms(duration_s=0.1, samplerate=100) == 0.0


class _LongCapture:
    """A video 1 s long to decode: a frame every 1 ms until then."""

    def __init__(self) -> None:
        self.reads = 0
        self.ends_at = time.monotonic() + 1.0

    def read(self):
        if time.monotonic() >= self.ends_at:
            return False, None
        self.reads += 1
        time.sleep(0.001)
        return True, np.full((4, 4, 3), self.reads % 255, dtype=np.uint8)


def test_a_stop_ends_the_video_decode():
    import cv2
    capture = _LongCapture()
    token = StopToken("video-stop")
    _stop_soon(token)
    began = time.monotonic()
    with stoppable_run(token=token), pytest.raises(ExecutionStopped):
        # end_frame None: the whole video, which a stop has to cut short.
        media._sum_frame_diffs(capture, cv2, 0, None, None)
    assert time.monotonic() - began < _PROMPT_S
    assert capture.reads > 0


def test_outside_a_run_the_decode_runs_to_its_end_frame():
    import cv2
    count, _total = media._sum_frame_diffs(_LongCapture(), cv2, 0, 5, None)
    assert count == 5
