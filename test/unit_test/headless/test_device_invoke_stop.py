"""A stop ends the wait for a device call that is still running.

Every mobile command reaches the device through ``DeviceSession.invoke``,
which ran the call on a helper thread but looked only at the session's own
cancel signal and timeout: a stop of the surrounding run waited for the call.
Now the stop ends the wait; the call finishes in the background, its result is
discarded, and the session is closed because nobody saw the state it left the
device in -- what a timeout already did. The device call is a fake that blocks
for at most 1 s; no adb or WebDriverAgent is involved.
"""
import threading
import time
from concurrent.futures import CancelledError

import pytest

from je_auto_control.utils.exception.cancellation import CancellationToken, cancellation_scope
from je_auto_control.utils.executor.run_control import ExecutionStopped, StopToken, shielded, stoppable_run
from je_auto_control.wrapper.device_context import DeviceClosedError, DeviceContext, open_device

_PROMPT_S = 0.7


@pytest.fixture
def session():
    opened = open_device(DeviceContext("android", "emulator-5554", timeout_s=5.0), adb=object())
    yield opened
    opened.close()


class _Blocked:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.finished = threading.Event()

    def __call__(self):
        self.release.wait(1.0)
        self.finished.set()
        return "late"


def _later(action) -> None:
    timer = threading.Timer(0.1, action)
    timer.daemon = True
    timer.start()


def test_a_run_stop_ends_the_wait_and_closes_the_session(session):
    call = _Blocked()
    token = StopToken("device-stop")
    _later(lambda: token.stop("test"))
    began = time.monotonic()
    with stoppable_run(token=token), pytest.raises(ExecutionStopped):
        session.invoke("capture", call)
    assert time.monotonic() - began < _PROMPT_S
    assert not call.finished.is_set()             # still running; its result is never used
    with pytest.raises(DeviceClosedError, match="stopped"):
        session.check_usable()
    call.release.set()


def test_a_cancellation_ends_the_wait_too(session):
    call = _Blocked()
    token = CancellationToken(7)
    _later(token.cancel)
    began = time.monotonic()
    with cancellation_scope(token), pytest.raises(CancelledError):
        session.invoke("capture", call)
    assert time.monotonic() - began < _PROMPT_S
    call.release.set()


def test_a_stopped_run_never_starts_the_call(session):
    started = []
    token = StopToken("device-before")
    token.stop("early")
    with stoppable_run(token=token), pytest.raises(ExecutionStopped):
        session.invoke("capture", lambda: started.append(True))
    assert started == []
    session.check_usable()                         # nothing ran, so nothing is unobserved


def test_cleanup_under_a_shield_still_gets_its_result(session):
    token = StopToken("device-shield")
    token.stop("once")
    with stoppable_run(token=token), shielded():
        assert session.invoke("press_key", lambda: "done") == "done"


def test_outside_a_run_the_result_arrives(session):
    assert session.invoke("capture", lambda: 5) == 5
