"""Tab cancellation reaches cooperative headless work without native UI operations."""
import os
import queue
import threading
import time
import weakref
from concurrent.futures import CancelledError

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402
from je_auto_control.gui._tab_task import TabTask, _call_plain  # noqa: E402
from je_auto_control.gui.tab_task_controller import CancellationToken, TaskTimeout  # noqa: E402
from je_auto_control.utils.accessibility.backends.windows_events import wait_for_event  # noqa: E402
from je_auto_control.utils.exception.cancellation import current_cancellation_token  # noqa: E402


def _pump(app, predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    return predicate()


def _destroy(app, owner):
    owner.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    app.processEvents()


@pytest.mark.parametrize("reason", ["stop", "timeout", "owner_destroyed"])
def test_tab_cancellation_ends_headless_wait(reason):
    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    tab = TabTask(owner)
    entered, exited = threading.Event(), threading.Event()
    events = queue.Queue()
    cancelled, results, errors = [], [], []

    def work():
        entered.set()
        try:
            return wait_for_event(events, 10)
        except CancelledError:
            cancelled.append(True)
            raise
        finally:
            exited.set()

    tab.result.connect(results.append)
    tab.error.connect(errors.append)
    assert tab.start(work, timeout_s=0.5 if reason == "timeout" else None)
    try:
        assert _pump(app, entered.is_set)
        if reason == "stop":
            assert tab.stop()
        elif reason == "owner_destroyed":
            _destroy(app, owner)
        assert _pump(app, exited.is_set), "cancel did not reach the headless wait"
        assert cancelled == [True]
        assert results == []
        if reason == "timeout":
            assert len(errors) == 1 and isinstance(errors[0], TaskTimeout)
        else:
            assert errors == []
    finally:
        events.put({"cleanup": True})
        assert _pump(app, exited.is_set)
        if reason != "owner_destroyed":
            _destroy(app, owner)


def test_precancelled_tab_work_never_starts_and_scope_is_restored():
    token = CancellationToken()
    token.cancel()
    called = []
    with pytest.raises(CancelledError):
        _call_plain(lambda: called.append(True), token)
    assert called == []
    assert current_cancellation_token() is None


def test_tab_work_delivers_normal_result_with_scope():
    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    tab = TabTask(owner)
    results, scopes = [], []

    def work():
        token = current_cancellation_token()
        assert token is not None
        scopes.append(weakref.ref(token))
        events = queue.Queue()
        events.put({"name": "ready"})
        return wait_for_event(events, 1)

    tab.result.connect(results.append)
    try:
        assert tab.start(work)
        assert _pump(app, lambda: not tab.running)
        assert results == [{"name": "ready"}]
        assert current_cancellation_token() is None
        assert _pump(app, lambda: scopes[0]() is None), "completed work retained its cancellation scope"
    finally:
        _destroy(app, owner)
