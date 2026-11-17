"""Every page that runs background work reports it in the workspace's execution details.

Only Diagnostics published execution details; every other page showed
*This feature does not publish execution details* whatever it was doing. A
:class:`~je_auto_control.gui._tab_task.TabTask` now publishes each run for the
page it runs on -- also when the task belongs to a panel nested inside the page.
"""
import os
import threading

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

from je_auto_control.gui._task_details import page_of  # noqa: E402
from je_auto_control.gui._tab_task import TabTask  # noqa: E402
from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper  # noqa: E402
from je_auto_control.utils.exception.cancellation import TaskProgress  # noqa: E402
from headless._qt_settle import pump_until  # noqa: E402

_APP = QApplication.instance() or QApplication([])


class _Page(QWidget):
    """A page whose task belongs to a panel inside it, as Run History's journal browser does."""

    def __init__(self, details=True):
        super().__init__()
        self.panel = QWidget()
        QVBoxLayout(self).addWidget(self.panel)
        self.task = TabTask(self.panel, details=details)


@pytest.fixture
def shell():
    from je_auto_control.gui.tab_registry import TabEntry, TabRegistry
    from je_auto_control.gui.workspace import WorkspaceShell
    registry = TabRegistry([TabEntry("work", "work", _Page),
                            TabEntry("quiet", "quiet", lambda: _Page(details=False))])
    widget = WorkspaceShell(registry)
    widget.activate_tab("work")
    yield widget
    widget.deleteLater()
    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def _phase(shell):
    snapshot = shell.details.snapshot
    return None if snapshot is None else snapshot.phase


def _held():
    entered, release = threading.Event(), threading.Event()

    def work():
        entered.set()
        assert release.wait(10.0)
        return "done"
    return work, entered, release


def test_a_page_shows_its_run_and_then_that_it_succeeded(shell):
    page = shell.tabs.currentWidget()
    assert shell.details.snapshot is None           # no run yet: nothing published
    work, entered, release = _held()
    assert page.task.start(work)
    assert entered.wait(10.0)
    assert _phase(shell) == "running"
    release.set()
    assert pump_until(lambda: _phase(shell) == "succeeded")


def test_a_failed_run_says_why(shell):
    page = shell.tabs.currentWidget()

    def fail():
        raise ValueError("no such host")

    assert page.task.start(fail)
    assert pump_until(lambda: _phase(shell) == "error")
    assert shell.details.snapshot.summary == "ValueError: no such host"


def test_a_run_past_its_deadline_says_so(shell):
    page = shell.tabs.currentWidget()
    work, _entered, release = _held()
    try:
        assert page.task.start(work, timeout_s=0.05)
        assert pump_until(lambda: _phase(shell) == "error")
        assert shell.details.snapshot.summary == language_wrapper.translate("task_timed_out", "task_timed_out")
    finally:
        release.set()


def test_stopping_plain_work_shows_it_cancelled_at_once(shell):
    page = shell.tabs.currentWidget()
    work, entered, release = _held()
    try:
        assert page.task.start(work)
        assert entered.wait(10.0)
        page.task.stop()
        assert _phase(shell) == "cancelled"
    finally:
        release.set()


def test_work_that_unwinds_shows_stopping_then_cancelled_with_its_progress(shell):
    page = shell.tabs.currentWidget()
    reported, release = threading.Event(), threading.Event()

    def work(stop_event, report):
        report(TaskProgress(1, 2, 5))
        reported.set()
        assert stop_event.wait(10.0)
        assert release.wait(10.0)
        return "partial"

    assert page.task.start_until_stopped(work, reports=True)
    assert reported.wait(10.0)
    assert pump_until(lambda: shell.details.snapshot.completed == 2)
    assert (shell.details.snapshot.phase, shell.details.snapshot.total) == ("running", 5)
    page.task.stop()
    assert _phase(shell) == "stopping"
    release.set()
    assert pump_until(lambda: _phase(shell) == "cancelled")   # what it did, but it was stopped


def test_a_task_built_without_details_publishes_nothing(shell):
    shell.activate_tab("quiet")
    page = shell.tabs.currentWidget()
    assert page.task.start(lambda: "done")
    assert pump_until(lambda: not page.task.running)
    assert shell.details.snapshot is None


def test_off_the_workspace_a_task_reports_on_its_own_owner():
    owner = QWidget()
    child = QWidget(owner)
    try:
        assert page_of(child) is child
    finally:
        owner.deleteLater()
