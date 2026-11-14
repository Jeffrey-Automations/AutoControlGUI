"""A VLM locate or click bound to a cancelled task stops before it costs a request or moves the mouse.

The GUI runs these calls as cancellable tasks (Stop, a deadline, a closed tab).
The HTTP request itself cannot be interrupted, so the answer can arrive after
the task was cancelled; :func:`click_by_description` must not click on it.
"""
import sys
import types
from concurrent.futures import CancelledError
from typing import Optional, Tuple

import pytest

from je_auto_control.utils.exception.cancellation import CancellationToken, cancellation_scope
from je_auto_control.utils.vision import vlm_api
from je_auto_control.utils.vision.backends.base import VLMBackend


class _Backend(VLMBackend):
    name = "fake"
    available = True

    def __init__(self, coords: Optional[Tuple[int, int]], token: Optional[CancellationToken] = None) -> None:
        self._coords = coords
        self._token = token
        self.calls = 0

    def locate(self, image_bytes: bytes, description: str, model: Optional[str] = None,
               image_mime: str = "image/png") -> Optional[Tuple[int, int]]:
        self.calls += 1
        if self._token is not None:
            self._token.cancel()            # Stop pressed while the model was thinking
        return self._coords


@pytest.fixture
def mouse(monkeypatch):
    """Stand in for the native mouse module ``click_by_description`` imports on a click."""
    moves = []
    fake = types.ModuleType("je_auto_control.wrapper.auto_control_mouse")
    fake.set_mouse_position = lambda x, y: moves.append(("move", x, y))
    fake.click_mouse = lambda button, x, y: moves.append(("click", x, y))
    monkeypatch.setitem(sys.modules, "je_auto_control.wrapper.auto_control_mouse", fake)
    monkeypatch.setattr(vlm_api, "_capture_screenshot_bytes", lambda screen_region=None: b"fake-png-bytes")
    return moves


def test_a_click_whose_task_was_cancelled_during_the_request_does_not_click(mouse):
    token = CancellationToken(task_id=1)
    backend = _Backend((10, 20), token)
    with cancellation_scope(token), pytest.raises(CancelledError):
        vlm_api.click_by_description("the OK button", backend=backend)
    assert backend.calls == 1
    assert mouse == []


def test_a_task_cancelled_before_the_request_does_not_send_it(mouse):
    token = CancellationToken(task_id=2)
    token.cancel()
    backend = _Backend((10, 20))
    with cancellation_scope(token), pytest.raises(CancelledError):
        vlm_api.locate_by_description("the OK button", backend=backend)
    assert backend.calls == 0


def test_without_a_task_the_click_still_lands(mouse):
    assert vlm_api.click_by_description("the OK button", backend=_Backend((10, 20))) is True
    assert mouse == [("move", 10, 20), ("click", 10, 20)]


def test_a_live_task_clicks(mouse):
    with cancellation_scope(CancellationToken(task_id=3)):
        assert vlm_api.click_by_description("the OK button", backend=_Backend((10, 20))) is True
    assert mouse == [("move", 10, 20), ("click", 10, 20)]
