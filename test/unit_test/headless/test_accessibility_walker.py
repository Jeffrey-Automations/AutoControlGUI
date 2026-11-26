"""Accessibility walks run on one long-lived thread so a stop ends the wait. No Qt, no COM."""
import threading
import time

import pytest

from je_auto_control.utils.accessibility import accessibility_api
from je_auto_control.utils.accessibility.element import AccessibilityElement
from je_auto_control.utils.accessibility.walker import _WALKER, stoppable_read
from je_auto_control.utils.executor.run_control import ExecutionStopped, stoppable_run


class Backend:
    """Records the thread every call runs on; ``list_elements`` can be held until released."""

    def __init__(self):
        self.threads, self.entered, self.release = [], threading.Event(), threading.Event()
        self.release.set()

    def _note(self):
        self.threads.append(threading.current_thread())

    def list_elements(self, app_name=None, max_results=200, **_extra):
        self._note()
        self.entered.set()
        self.release.wait(10)
        return [AccessibilityElement("OK", "button", (0, 0, 10, 10), app_name or "app")]

    def focused_element(self):
        self._note()
        return AccessibilityElement("Edit", "edit", (0, 0, 10, 10), "app")

    def get_value(self, **_kwargs):
        self._note()
        return "v"

    def get_state(self, **_kwargs):
        self._note()
        return {"value": "v"}

    def read_table(self, **_kwargs):
        self._note()
        return [["a"]]

    def invoke(self, **_kwargs):
        self._note()
        return True


@pytest.fixture
def backend(monkeypatch):
    owned = Backend()
    monkeypatch.setattr(accessibility_api, "get_backend", lambda: owned)
    return owned


def test_outside_a_run_reads_stay_on_the_callers_thread(backend):
    assert accessibility_api.list_accessibility_elements()[0].name == "OK"
    assert backend.threads == [threading.current_thread()]


def test_inside_a_run_every_read_runs_on_the_one_walker_thread(backend):
    with stoppable_run():
        accessibility_api.list_accessibility_elements()
        accessibility_api.focused_accessibility_element()
        accessibility_api.control_get_value(name="x")
        accessibility_api.control_get_state(name="x")
        accessibility_api.read_control_table(name="x")
        accessibility_api.list_accessibility_elements()
    assert len(set(backend.threads)) == 1
    assert backend.threads[0] is _WALKER.thread and backend.threads[0] is not threading.current_thread()


def test_inside_a_run_a_write_runs_on_the_walker_too(backend):
    # As one job that finds, then checks the stop, then acts: see test_accessibility_walker_writes.
    with stoppable_run():
        assert accessibility_api.control_invoke(name="OK") is True
    assert backend.threads == [_WALKER.thread] and backend.threads[0] is not threading.current_thread()


def test_a_stop_ends_the_wait_for_a_slow_walk(backend):
    backend.release.clear()
    started = time.monotonic()
    try:
        with pytest.raises(ExecutionStopped):
            with stoppable_run() as token:
                threading.Thread(target=lambda: backend.entered.wait(5) and token.stop(), daemon=True).start()
                accessibility_api.list_accessibility_elements()
        assert time.monotonic() - started < 5
    finally:
        backend.release.set()


def test_a_read_error_reaches_the_caller():
    def broken():
        raise ValueError("backend read failed")
    with stoppable_run():
        with pytest.raises(ValueError, match="backend read failed"):
            stoppable_read(broken)


def test_the_callers_context_is_carried_to_the_walker():
    import contextvars
    marker = contextvars.ContextVar("marker", default="unset")
    marker.set("caller")
    with stoppable_run():
        assert stoppable_read(marker.get) == "caller"


def _stop_when(event, call):
    with pytest.raises(ExecutionStopped):
        with stoppable_run() as token:
            threading.Thread(target=lambda: event.wait(5) and token.stop(), daemon=True).start()
            call()


def test_a_hung_read_does_not_block_the_reads_after_it():
    entered, release, stuck = threading.Event(), threading.Event(), []

    def hung():
        stuck.append(threading.current_thread())
        entered.set()
        release.wait(30)
    try:
        _stop_when(entered, lambda: stoppable_read(hung))
        started = time.monotonic()
        with stoppable_run():
            assert stoppable_read(lambda: "next") == "next"
        assert time.monotonic() - started < 5
        assert _WALKER.thread is not stuck[0]  # the stuck thread was retired, not reused
    finally:
        release.set()


def test_a_read_queued_behind_a_hung_one_still_runs():
    entered, release, results = threading.Event(), threading.Event(), []

    def hung():
        entered.set()
        release.wait(30)

    def queued():
        entered.wait(5)
        with stoppable_run():
            results.append(stoppable_read(lambda: "queued"))
    waiter = threading.Thread(target=queued, daemon=True)
    waiter.start()
    try:
        def call():
            stoppable_read(hung)
        with pytest.raises(ExecutionStopped):
            with stoppable_run() as token:
                threading.Timer(1.0, token.stop).start()  # long enough for the other read to queue behind it
                call()
        waiter.join(5)
        assert results == ["queued"]
    finally:
        release.set()


def test_a_read_abandoned_before_it_started_never_runs():
    entered, release, ran = threading.Event(), threading.Event(), []

    def slow():
        entered.set()
        release.wait(30)
    holder = threading.Thread(target=lambda: _hold(slow), daemon=True)
    holder.start()
    assert entered.wait(5)
    with pytest.raises(ExecutionStopped):
        with stoppable_run() as token:
            threading.Timer(0.3, token.stop).start()
            stoppable_read(lambda: ran.append(True))
    release.set()
    holder.join(5)
    with stoppable_run():
        stoppable_read(lambda: None)  # anything still queued would have run by now
    assert ran == []


def _hold(function):
    with stoppable_run():
        stoppable_read(function)


def test_a_read_inside_a_read_runs_directly():
    from je_auto_control.utils.exception.cancellation import CancellationToken, cancellation_scope
    with cancellation_scope(CancellationToken(1)):  # carried into the walker by the context
        assert stoppable_read(lambda: stoppable_read(lambda: "inner")) == "inner"


def test_a_read_that_hangs_after_being_moved_to_a_fresh_worker_is_retired_too():
    entered, second, release = threading.Event(), threading.Event(), threading.Event()

    def hung(event):
        event.set()
        release.wait(30)

    def queued():
        entered.wait(5)
        _stop_when(second, lambda: stoppable_read(hung, second))
    waiter = threading.Thread(target=queued, daemon=True)
    waiter.start()
    try:
        with pytest.raises(ExecutionStopped):
            with stoppable_run() as token:
                threading.Timer(1.0, token.stop).start()  # the second read queues behind this one first
                stoppable_read(hung, entered)
        waiter.join(5)
        assert second.is_set() and not waiter.is_alive()
        finished = threading.Event()
        threading.Thread(target=lambda: (_hold(lambda: None), finished.set()), daemon=True).start()
        assert finished.wait(5)
    finally:
        release.set()
