"""A stop no longer waits for four single backend calls that cannot look at it.

``wait_until_port``'s connect probe, an SMTP exchange, an ORB feature pass and
an agent's model round trip each block for as long as the backend takes. They
now go through ``run_control.stoppable_call``: inside a stoppable run a stop
ends the wait at once and the call finishes in the background, unused.
Every slow call is a fake that blocks for at most 1 s: no socket, SMTP server,
model or screen is touched.
"""
import importlib
import threading
import time

import numpy as np
import pytest

from je_auto_control.utils.executor.run_control import ExecutionStopped, StopToken, stoppable_run

_PROMPT_S = 0.7


class _Blocked:
    """A call that blocks until released or for 1 s, then returns ``value``."""

    def __init__(self, value=None) -> None:
        self.value = value
        self.release = threading.Event()
        self.entered = threading.Event()
        self.finished = threading.Event()

    def __call__(self, *_args, **_kwargs):
        self.entered.set()
        self.release.wait(1.0)
        self.finished.set()
        return self.value


def _stopped_quickly(call) -> None:
    """Run ``call()`` in a stoppable run stopped after 0.1 s; it must raise promptly."""
    token = StopToken()
    timer = threading.Timer(0.1, token.stop, ("test",))
    timer.daemon = True
    timer.start()
    began = time.monotonic()
    with stoppable_run(token=token), pytest.raises(ExecutionStopped):
        call()
    assert time.monotonic() - began < _PROMPT_S


def test_wait_until_port_stops_during_one_connect():
    from je_auto_control.utils.smart_waits.waits import wait_until_port
    connect = _Blocked(value=True)
    _stopped_quickly(lambda: wait_until_port("10.255.255.1", 80, timeout_s=30.0,
                                             connect_timeout_s=30.0, connector=connect))
    assert connect.entered.is_set() and not connect.finished.is_set()
    connect.release.set()


def test_send_email_stops_during_the_smtp_exchange(monkeypatch):
    from je_auto_control.utils.email_send import email_sender
    connect = _Blocked()

    class _SlowSMTP:
        def __init__(self, *args, **kwargs):
            connect(*args, **kwargs)

    monkeypatch.setattr(email_sender.smtplib, "SMTP", _SlowSMTP)
    message = {"sender": "a@example.com", "to": "b@example.com", "subject": "s", "body": "b"}
    _stopped_quickly(lambda: email_sender.send_email(message, {"host": "smtp.example.com"}))
    assert connect.entered.is_set() and not connect.finished.is_set()
    connect.release.set()


def test_feature_match_stops_during_the_orb_pass(monkeypatch):
    # The package re-exports the function under the module's own name.
    module = importlib.import_module("je_auto_control.utils.feature_match.feature_match")
    orb_pass = _Blocked()
    monkeypatch.setattr(module, "_keypoint_matches", orb_pass)
    template = np.zeros((16, 16, 3), dtype=np.uint8)
    scene = np.zeros((64, 64, 3), dtype=np.uint8)
    _stopped_quickly(lambda: module.feature_match(template, haystack=scene))
    assert orb_pass.entered.is_set() and not orb_pass.finished.is_set()
    orb_pass.release.set()


def test_agent_loop_stops_during_a_model_round_trip():
    from je_auto_control.utils.agent.agent_loop import AgentBackend, AgentLoop
    decide = _Blocked(value={"tool": "AC_never", "input": {}})
    ran = []

    class _SlowBackend(AgentBackend):
        def decide_next_action(self, goal, screenshot, history):
            return decide(goal, screenshot, history)

    loop = AgentLoop(_SlowBackend(), tool_runner=lambda tool, args: ran.append(tool),
                     screenshot_fn=lambda: None)
    _stopped_quickly(lambda: loop.run("open the settings"))
    assert decide.entered.is_set()
    decide.release.set()
    assert decide.finished.wait(1.0)
    time.sleep(0.05)
    assert ran == []                       # the late decision was never acted on


def test_outside_a_run_each_call_is_unchanged():
    from je_auto_control.utils.smart_waits.waits import wait_until_port
    caller = threading.current_thread()
    seen = []

    def connect(*_args):
        seen.append(threading.current_thread())
        return True

    assert wait_until_port("127.0.0.1", 9, timeout_s=1.0, connector=connect).succeeded
    assert seen == [caller]
