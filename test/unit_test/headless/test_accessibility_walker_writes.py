"""Accessibility writes inside a run: a stop before the act prevents it, one after it waits for it. No Qt, no COM."""
from concurrent.futures import CancelledError
import threading
import time

import pytest

from je_auto_control.utils.accessibility import accessibility_api, walker
from je_auto_control.utils.accessibility.walker import (
    _WALKER, AccessibilityWriteOutcomeUnknown, begin_act, stoppable_read, stoppable_write,
)
from je_auto_control.utils.exception.cancellation import CancellationToken, cancellation_scope
from je_auto_control.utils.exception.exceptions import AutoControlException
from je_auto_control.utils.executor.run_control import ExecutionStopped, stoppable_run


class GatedBackend:
    """Finds, passes the act gate, then acts; the find and the act can each be held."""

    gates_writes = True

    def __init__(self):
        self.threads, self.acts = [], []
        self.finding, self.found = threading.Event(), threading.Event()
        self.acting, self.act_done = threading.Event(), threading.Event()
        self.found.set()
        self.act_done.set()

    def _write(self, what):
        self.threads.append(threading.current_thread())
        self.finding.set()
        self.found.wait(5)
        begin_act()
        self.acting.set()
        self.act_done.wait(5)
        self.acts.append(what)
        return True

    def set_value(self, value, **_filters):
        return self._write(("set_value", value))

    def invoke(self, **_filters):
        return self._write(("invoke",))

    def toggle(self, **_filters):
        return self._write(("toggle",))


class PlainBackend(GatedBackend):
    """A backend that never calls the gate: the whole call counts as the act."""

    gates_writes = False

    def _write(self, what):
        self.threads.append(threading.current_thread())
        self.acting.set()
        self.act_done.wait(5)
        self.acts.append(what)
        return True


def _use(monkeypatch, backend):
    monkeypatch.setattr(accessibility_api, "get_backend", lambda: backend)
    return backend


@pytest.fixture
def gated(monkeypatch):
    return _use(monkeypatch, GatedBackend())


@pytest.fixture
def short_grace(monkeypatch):
    monkeypatch.setattr(walker, "_ACT_GRACE_SECONDS", 0.3)


def _stop_on(event, token, then=None):
    def run():
        if event.wait(5):
            token.stop()
            if then is not None:
                then()
    threading.Thread(target=run, daemon=True).start()


def test_outside_a_run_a_write_stays_on_the_callers_thread(gated):
    assert accessibility_api.control_set_value("x", name="Field") is True
    assert gated.threads == [threading.current_thread()]


def test_inside_a_run_every_write_runs_on_the_walker(gated):
    with stoppable_run():
        assert accessibility_api.control_set_value("x", name="Field") is True
        assert accessibility_api.control_invoke(name="OK") is True
        assert accessibility_api.control_toggle(name="Box") is True
    assert gated.acts == [("set_value", "x"), ("invoke",), ("toggle",)]
    assert set(gated.threads) == {_WALKER.thread} and _WALKER.thread is not threading.current_thread()


def test_a_stop_during_the_find_ends_the_wait_and_the_act_never_happens(gated):
    gated.found.clear()
    started = time.monotonic()
    with pytest.raises(ExecutionStopped):
        with stoppable_run() as token:
            _stop_on(gated.finding, token)
            accessibility_api.control_set_value("x", name="Field")
    assert time.monotonic() - started < 1
    gated.found.set()
    gated.threads[0].join(1)  # the retired worker ends once the abandoned find reaches its gate
    assert not gated.threads[0].is_alive() and gated.acts == []


def test_a_stop_after_the_act_began_waits_for_it_and_reports_the_result(gated):
    gated.act_done.clear()
    with stoppable_run() as token:
        _stop_on(gated.acting, token, then=lambda: threading.Timer(0.2, gated.act_done.set).start())
        assert accessibility_api.control_invoke(name="OK") is True
    assert gated.acts == [("invoke",)]


def test_an_act_that_does_not_finish_in_the_bound_has_an_unknown_outcome(gated, short_grace):
    gated.act_done.clear()
    try:
        with pytest.raises(AccessibilityWriteOutcomeUnknown) as raised:
            with stoppable_run() as token:
                _stop_on(gated.acting, token)
                accessibility_api.control_toggle(name="Box")
        assert isinstance(raised.value, AutoControlException)
        assert isinstance(raised.value.__cause__, ExecutionStopped)
        stuck = gated.threads[0]
        with stoppable_run():
            assert stoppable_read(lambda: "next") == "next"
        assert _WALKER.thread is not stuck  # the worker still inside the act was retired
    finally:
        gated.act_done.set()


def test_a_write_whose_caller_stopped_before_it_started_never_runs(gated):
    entered, release = threading.Event(), threading.Event()

    def slow():
        entered.set()
        release.wait(5)
    holder = threading.Thread(target=lambda: _read_in_a_run(slow), daemon=True)
    holder.start()
    assert entered.wait(5)
    with pytest.raises(ExecutionStopped):
        with stoppable_run() as token:
            threading.Timer(0.3, token.stop).start()
            accessibility_api.control_set_value("x", name="Field")
    release.set()
    holder.join(5)
    with stoppable_run():
        stoppable_read(lambda: None)
    assert gated.threads == [] and gated.acts == []


def _read_in_a_run(function):
    with stoppable_run():
        stoppable_read(function)


def test_a_write_queued_behind_a_hung_read_still_runs_once_that_read_is_given_up(gated):
    entered, release, results = threading.Event(), threading.Event(), []

    def hung():
        entered.set()
        release.wait(30)

    def queued():
        entered.wait(5)
        with stoppable_run():
            results.append(accessibility_api.control_set_value("x", name="Field"))
    waiter = threading.Thread(target=queued, daemon=True)
    waiter.start()
    try:
        with pytest.raises(ExecutionStopped):
            with stoppable_run() as token:
                threading.Timer(0.5, token.stop).start()  # long enough for the write to queue behind it
                stoppable_read(hung)
        waiter.join(5)
        assert results == [True] and gated.acts == [("set_value", "x")]
    finally:
        release.set()


def test_a_cancel_during_the_find_prevents_the_act(gated):
    gated.found.clear()
    token = CancellationToken(7)
    threading.Thread(target=lambda: gated.finding.wait(5) and token.cancel(), daemon=True).start()
    with cancellation_scope(token):
        with pytest.raises(CancelledError):
            accessibility_api.control_invoke(name="OK")
    gated.found.set()
    gated.threads[0].join(1)
    assert not gated.threads[0].is_alive() and gated.acts == []


def test_a_backend_without_the_gate_is_waited_for_once_it_started(monkeypatch):
    plain = _use(monkeypatch, PlainBackend())
    plain.act_done.clear()
    with stoppable_run() as token:
        _stop_on(plain.acting, token, then=lambda: threading.Timer(0.2, plain.act_done.set).start())
        assert accessibility_api.control_set_value("y", name="Field") is True
    assert plain.acts == [("set_value", "y")]


def test_the_gate_is_inert_outside_a_write_on_the_walker():
    begin_act()  # on the caller's thread
    with stoppable_run():
        assert stoppable_read(lambda: (begin_act(), "read")[1]) == "read"


def test_a_write_error_reaches_the_caller():
    def broken():
        begin_act()
        raise ValueError("backend write failed")
    with stoppable_run():
        with pytest.raises(ValueError, match="backend write failed"):
            stoppable_write(broken, gated=True)
