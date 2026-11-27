"""A stop ends ``AC_android_find_element`` / ``AC_ios_find_element`` while the SDK polls.

uiautomator2's and facebook-wda's ``query.wait(timeout=...)`` poll the device
inside the SDK for the whole timeout and never look at a stop. The wait now
goes through ``stoppable_call``: a stop ends it, and ``click_element`` then
never taps. The device handles are fakes; no adb or WebDriverAgent runs.
"""
import threading
import time

import pytest

from je_auto_control.android import UIAutomatorDevice
from je_auto_control.android import click_element as android_click
from je_auto_control.android import find_element as android_find
from je_auto_control.ios import IOSDevice
from je_auto_control.ios import find_element as ios_find
from je_auto_control.utils.executor.run_control import ExecutionStopped, StopToken, stoppable_run

_PROMPT_S = 0.7


class _PollingQuery:
    """A selector whose ``wait`` polls for at most 1 s and then finds nothing."""

    def __init__(self) -> None:
        self.release = threading.Event()

    def wait(self, timeout: float):
        self.release.wait(min(float(timeout), 1.0))
        return False


class _Handle:
    def __init__(self, query: _PollingQuery) -> None:
        self.query = query
        self.taps = []

    def __call__(self, **_selectors):
        return self.query

    def click(self, x, y):
        self.taps.append((x, y))


def _stopped_quickly(call) -> None:
    token = StopToken()
    timer = threading.Timer(0.1, token.stop, ("test",))
    timer.daemon = True
    timer.start()
    began = time.monotonic()
    with stoppable_run(token=token), pytest.raises(ExecutionStopped):
        call()
    assert time.monotonic() - began < _PROMPT_S


def test_android_find_is_ended_by_a_stop():
    handle = _Handle(_PollingQuery())
    _stopped_quickly(lambda: android_find(text="Login", timeout_s=30.0,
                                          device=UIAutomatorDevice(handle=handle)))
    handle.query.release.set()


def test_android_click_never_taps_after_a_stop():
    handle = _Handle(_PollingQuery())
    _stopped_quickly(lambda: android_click(text="Login", timeout_s=30.0,
                                           device=UIAutomatorDevice(handle=handle)))
    handle.query.release.set()
    assert handle.taps == []


def test_ios_find_is_ended_by_a_stop():
    handle = _Handle(_PollingQuery())
    _stopped_quickly(lambda: ios_find(name="Login", timeout_s=30.0, device=IOSDevice(handle=handle)))
    handle.query.release.set()
