"""A device timeout is a finite number above zero, wherever it is given.

``DeviceContext`` accepted NaN and infinity, and ``from_spec`` (like
``command_session``) replaced an explicit ``0`` with the 30 s default. NaN and
infinity disable the deadline check in ``DeviceSession.invoke``, so a stalled
SDK call was waited on forever; an override passed to ``invoke`` was not
checked at all. Each is now refused, before a worker thread starts. No adb or
WebDriverAgent is involved: the transport is a placeholder object.
"""
import math

import pytest

from je_auto_control.wrapper import device_context
from je_auto_control.wrapper.device_context import DEFAULT_TIMEOUT_S, DeviceContext, DeviceError, open_device
from je_auto_control.wrapper.mobile_commands import command_session

_INVALID = [0, 0.0, -1, math.nan, math.inf, -math.inf, True, "5", None, pytest.param(10 ** 400, id="huge-int")]


@pytest.mark.parametrize("value", _INVALID)
def test_context_refuses_a_timeout_that_is_not_finite_and_positive(value):
    with pytest.raises(DeviceError):
        DeviceContext("android", "x", timeout_s=value)


@pytest.mark.parametrize("value", [0, -2, math.nan, math.inf, "nan", "inf", "soon", True])
def test_spec_timeout_is_validated_not_replaced(value):
    with pytest.raises(DeviceError):
        DeviceContext.from_spec({"platform": "android", "serial": "x", "timeout_s": value})


def test_spec_without_a_timeout_takes_the_default_and_a_number_string_still_parses():
    assert DeviceContext.from_spec({"platform": "ios", "url": "u"}).timeout_s == DEFAULT_TIMEOUT_S
    assert DeviceContext.from_spec({"platform": "ios", "url": "u", "timeout_s": None}).timeout_s == DEFAULT_TIMEOUT_S
    assert DeviceContext.from_spec({"platform": "ios", "url": "u", "timeout_s": "2.5"}).timeout_s == 2.5


@pytest.mark.parametrize("value", [0, math.nan, math.inf])
def test_command_session_refuses_an_explicit_bad_timeout(value):
    with pytest.raises(DeviceError):
        with command_session("android", "x", timeout_s=value):
            pass


@pytest.mark.parametrize("value", [0, -1, math.nan, math.inf, True, "1"])
def test_invoke_override_is_refused_before_a_worker_starts(monkeypatch, value):
    started = []
    monkeypatch.setattr(device_context.threading, "Thread",
                        lambda *args, **kwargs: started.append(kwargs) or pytest.fail("worker started"))
    session = open_device(DeviceContext("android", "x", timeout_s=5.0), adb=object())
    try:
        with pytest.raises(DeviceError):
            session.invoke("probe", lambda: pytest.fail("device call ran"), timeout_s=value)
        assert started == []
        session.check_usable()   # a refused argument does not break the session
    finally:
        session.close()


def test_a_valid_override_still_runs_the_call():
    session = open_device(DeviceContext("android", "x", timeout_s=5.0), adb=object())
    try:
        assert session.invoke("probe", lambda: "ok", timeout_s=1) == "ok"
    finally:
        session.close()
