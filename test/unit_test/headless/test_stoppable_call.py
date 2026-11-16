"""A stop does not wait for one native call it cannot interrupt: an image search pass or an OCR pass.

``stoppable_call`` runs such a call on a helper thread inside a stoppable run
or a cancellation scope, and the caller returns as soon as either stops; the
call's late result is discarded. Every slow call here is a fake that waits on
an event, so nothing reads the real screen.
"""
import threading
import time
from concurrent.futures import CancelledError

import pytest

from je_auto_control.utils.exception.cancellation import CancellationToken, cancellation_scope
from je_auto_control.utils.executor.run_control import ExecutionStopped, StopToken, stoppable_call, stoppable_run


def _later(action, delay: float = 0.3) -> None:
    timer = threading.Timer(delay, action)
    timer.daemon = True
    timer.start()


class _Slow:
    """A call that blocks until released (or 10 s), noting the thread it ran on."""

    def __init__(self, value=7) -> None:
        self.value = value
        self.release = threading.Event()
        self.threads = []
        self.finished = threading.Event()

    def __call__(self, *args, **kwargs):
        self.threads.append(threading.current_thread())
        self.release.wait(10)
        self.finished.set()
        return self.value


def test_outside_any_run_it_is_a_plain_call():
    slow = _Slow()
    slow.release.set()
    assert stoppable_call(slow) == 7
    assert slow.threads == [threading.current_thread()]


def test_inside_a_run_the_result_and_errors_still_arrive():
    slow = _Slow(value={"ok": True})
    slow.release.set()
    with stoppable_run(token=StopToken("call-value")):
        assert stoppable_call(slow) == {"ok": True}

        def broken():
            raise ValueError("bad input")

        with pytest.raises(ValueError, match="bad input"):
            stoppable_call(broken)
    assert slow.threads != [threading.current_thread()]


def test_a_stop_returns_without_waiting_for_the_call():
    slow = _Slow()
    token = StopToken("call-stop")
    _later(lambda: token.stop("test"))
    started = time.monotonic()
    with stoppable_run(token=token), pytest.raises(ExecutionStopped):
        stoppable_call(slow)
    assert time.monotonic() - started < 2
    assert not slow.finished.is_set()          # still running; its result is discarded
    slow.release.set()


def test_a_cancellation_returns_without_waiting_for_the_call():
    slow = _Slow()
    token = CancellationToken(task_id=51)
    _later(token.cancel)
    started = time.monotonic()
    with cancellation_scope(token), pytest.raises(CancelledError):
        stoppable_call(slow)
    assert time.monotonic() - started < 2
    slow.release.set()


def test_a_stopped_run_never_starts_the_call():
    slow = _Slow()
    token = StopToken("call-stopped")
    token.stop("before")
    with stoppable_run(token=token), pytest.raises(ExecutionStopped):
        stoppable_call(slow)
    assert slow.threads == []


def test_a_stop_ends_an_image_search_stuck_in_its_match(monkeypatch):
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    pytest.importorskip("je_open_cv")
    from PIL import Image

    from je_auto_control.utils.cv2_utils import template_detection
    frame = Image.fromarray(np.zeros((60, 80, 3), dtype=np.uint8))
    monkeypatch.setattr(template_detection, "grab_logical", lambda region, all_screens=True: (frame.copy(), 0, 0))
    slow = _Slow(value=np.zeros((51, 71), dtype=np.float32))
    monkeypatch.setattr(cv2, "matchTemplate", slow)
    token = StopToken("image-stop")
    _later(lambda: token.stop("test"))
    started = time.monotonic()
    with stoppable_run(token=token), pytest.raises(ExecutionStopped):
        template_detection.find_image(np.zeros((10, 10), dtype=np.uint8), detect_threshold=0.9)
    assert time.monotonic() - started < 2
    assert slow.threads, "the search never reached the match"
    slow.release.set()


def test_a_stop_ends_an_ocr_pass(monkeypatch):
    from je_auto_control.utils.ocr import ocr_engine

    class _Engine:
        def __init__(self) -> None:
            self.slow = _Slow(value=[])

        def image_to_matches(self, frame, lang, min_confidence):
            return self.slow(frame, lang, min_confidence)

    engine = _Engine()
    monkeypatch.setattr(ocr_engine, "_grab", lambda region: (object(), 0, 0))
    token = StopToken("ocr-stop")
    _later(lambda: token.stop("test"))
    started = time.monotonic()
    with stoppable_run(token=token), pytest.raises(ExecutionStopped):
        ocr_engine.find_text_matches("Save", backend=engine)
    assert time.monotonic() - started < 2
    assert engine.slow.threads, "OCR never started"
    engine.slow.release.set()


def test_a_stop_ends_a_visual_match_stuck_in_its_match(monkeypatch):
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    from je_auto_control.utils.visual_match import visual_match
    noise = np.random.default_rng(7)
    haystack = noise.integers(0, 255, (60, 80), dtype=np.uint8)
    template = haystack[10:30, 20:45].copy()
    slow = _Slow(value=np.zeros((41, 56), dtype=np.float32))
    monkeypatch.setattr(cv2, "matchTemplate", slow)
    token = StopToken("visual-stop")
    _later(lambda: token.stop("test"))
    started = time.monotonic()
    with stoppable_run(token=token), pytest.raises(ExecutionStopped):
        visual_match.match_template(template, haystack=haystack)
    assert time.monotonic() - started < 2
    assert slow.threads, "the match never started"
    slow.release.set()


def test_every_template_match_in_the_package_goes_through_stoppable_call():
    """A new match path that calls ``cv2.matchTemplate`` directly would bring the waiting stop back."""
    import re
    from pathlib import Path
    package = Path(__file__).resolve().parents[3] / "je_auto_control"
    bare = []
    for path in package.rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if re.search(r"(?<!stoppable_call\()\bcv2\.matchTemplate\(", code):
                bare.append(f"{path.relative_to(package)}:{number}")
    assert bare == []
