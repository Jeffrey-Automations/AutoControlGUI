"""Pacing sleeps inside one gesture wake on a stop of the surrounding run. No Qt, no real input."""
import importlib
import threading
import time

import pytest

from je_auto_control.utils.executor import run_control
from je_auto_control.utils.executor.run_control import ExecutionStopped, stoppable_run

LONG = 30.0  # a pause a stop must cut short; the test fails long before it would end


def _stop_soon(token, delay=0.1):
    timer = threading.Timer(delay, token.stop)
    timer.start()
    return timer


def _stopped_quickly(started):
    return time.monotonic() - started < 5


def test_humanized_typing_delay_wakes_on_stop():
    from je_auto_control.utils.humanize.typing import type_text_humanized
    typed = []
    started = time.monotonic()
    with pytest.raises(ExecutionStopped):
        with stoppable_run() as token:
            _stop_soon(token)
            type_text_humanized("abc", base_delay=LONG, jitter=0.0, typer=typed.append)
    assert _stopped_quickly(started)
    assert typed == ["a"]


def test_humanized_motion_step_wakes_on_stop(monkeypatch):
    from je_auto_control.utils.humanize import motion
    from je_auto_control.wrapper import auto_control_mouse
    moves = []
    monkeypatch.setattr(auto_control_mouse, "get_mouse_position", lambda: (0, 0))
    monkeypatch.setattr(auto_control_mouse, "set_mouse_position", lambda x, y: moves.append((x, y)))
    started = time.monotonic()
    with pytest.raises(ExecutionStopped):
        with stoppable_run() as token:
            _stop_soon(token)
            motion.move_mouse_humanized(400, 300, duration_s=LONG * 50)
    assert _stopped_quickly(started)
    assert len(moves) == 1


def test_injected_sleep_is_still_used_outside_a_run():
    from je_auto_control.utils.humanize.typing import type_text_humanized
    slept = []
    type_text_humanized("ab", base_delay=0.5, jitter=0.0, typer=lambda _c: None, sleep=slept.append)
    assert slept == [0.5, 0.5]


def test_plain_calls_outside_a_run_still_sleep_with_time_sleep(monkeypatch):
    from je_auto_control.utils.humanize import typing as humanized_typing
    slept = []
    monkeypatch.setattr(humanized_typing.time, "sleep", slept.append)
    humanized_typing.type_text_humanized("ab", base_delay=0.25, jitter=0.0, typer=lambda _c: None)
    assert slept == [0.25, 0.25]


@pytest.mark.parametrize("delays,expected", [
    # A step rest: pressed, moved to the first point, then released right there, not at the end.
    ({"step_delay_s": LONG}, [("press", 0, 0), ("move", 0, 0), ("release", 0, 0)]),
    # The settle before the press: the button never went down, so nothing is released.
    ({"settle_s": LONG}, [("move", 0, 0)]),
])
def test_a_stopped_drag_releases_its_button_where_it_was(delays, expected):
    tween_drag = importlib.import_module("je_auto_control.utils.tween_drag.tween_drag")
    events = []
    started = time.monotonic()
    with pytest.raises(ExecutionStopped):
        with stoppable_run() as token:
            _stop_soon(token)
            tween_drag._drag_through([[0, 0], [10, 10], [20, 20]], "mouse_left", events.append, **delays)
    assert _stopped_quickly(started)
    assert [(event["op"], event["x"], event["y"]) for event in events] == expected


def test_click_interval_wakes_on_stop_between_whole_clicks(monkeypatch):
    from je_auto_control.wrapper import auto_control_mouse
    pressed, released = [], []
    monkeypatch.setattr(auto_control_mouse, "mouse_preprocess", lambda key, x, y: (1, 5, 5))
    monkeypatch.setattr(auto_control_mouse, "_mouse_input", lambda kind, *_a: (pressed if kind == "mouse_press"
                                                                               else released).append(kind))
    monkeypatch.setattr(auto_control_mouse, "_click_plan", lambda clicks, interval: (clicks, interval))
    monkeypatch.setattr(auto_control_mouse.mouse, "click_mouse", lambda *_a: None, raising=False)
    monkeypatch.setattr(auto_control_mouse.sys, "platform", "win32")
    started = time.monotonic()
    with pytest.raises(ExecutionStopped):
        with stoppable_run() as token:
            _stop_soon(token)
            auto_control_mouse.click_mouse("mouse_left", 5, 5, clicks=3, interval=LONG)
    assert _stopped_quickly(started)
    assert len(pressed) == len(released) == 1


def test_pause_is_the_shared_seam(monkeypatch):
    calls = []
    monkeypatch.setattr(run_control, "pause", lambda seconds, sleep=None: calls.append(seconds))
    tween_drag = importlib.import_module("je_auto_control.utils.tween_drag.tween_drag")
    tween_drag._pause(0.2)
    assert calls == [0.2]
