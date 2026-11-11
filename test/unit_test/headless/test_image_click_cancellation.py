"""Image clicks observe scoped cancellation before each native input boundary."""
from concurrent.futures import CancelledError

import pytest

from je_auto_control.utils.exception.cancellation import CancellationToken, cancellation_scope
from je_auto_control.wrapper import auto_control_image as module


@pytest.mark.parametrize("cancel_at", ["before", "detection", "move"])
def test_cancellation_prevents_next_input_without_replay(monkeypatch, cancel_at):
    token = CancellationToken(1)
    events = []

    def detect(*args):
        events.append("detect")
        if cancel_at == "detection":
            token.cancel()
        return [True, [0, 0, 8, 8]]

    def move(*args):
        events.append("move")
        token.cancel()

    monkeypatch.setattr(module.template_detection, "find_image", detect)
    monkeypatch.setattr(module, "set_mouse_position", move)
    monkeypatch.setattr(module, "click_mouse", lambda *args: events.append("click"))
    if cancel_at == "before":
        token.cancel()
    with cancellation_scope(token), pytest.raises(CancelledError):
        module.locate_and_click("template.png", "mouse_left")
    assert events == {"before": [], "detection": ["detect"], "move": ["detect", "move"]}[cancel_at]
