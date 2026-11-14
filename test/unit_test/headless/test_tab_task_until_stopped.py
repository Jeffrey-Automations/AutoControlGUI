"""Work that stops at its next step keeps the tab busy until it has, then reports what it did.

Computer use drives the mouse, and a DAG run keeps scheduling until it
notices. A Stop that freed the tab at once would let a second run start while
the first was still finishing its step, so
:meth:`TabTask.start_until_stopped` hands the work a stop event instead and
stays running until the work returns.
"""
import os
import threading

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from je_auto_control.gui import computer_use_tab, dag_tab  # noqa: E402
from je_auto_control.gui._tab_task import TabTask  # noqa: E402
from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper  # noqa: E402
from headless._qt_settle import pump_until  # noqa: E402

_APP = QApplication.instance() or QApplication([])


def _t(key):
    return language_wrapper.translate(key, key)


class _Step:
    """Work that waits for its stop event, then for ``finish``, and returns what it saw."""

    def __init__(self):
        self.stopped, self.finish = threading.Event(), threading.Event()

    def __call__(self, stop_event):
        assert stop_event.wait(30.0)
        self.stopped.set()
        self.finish.wait(30.0)          # the step in progress, still running after the Stop
        return "stopped after one step"


@pytest.fixture
def owner():
    widget = QWidget()
    yield widget
    widget.deleteLater()


def test_stop_sets_the_event_and_the_task_stays_busy_until_the_work_returns(owner):
    task, work, results = TabTask(owner), _Step(), []
    task.result.connect(results.append)
    assert task.start_until_stopped(work)
    assert task.stop() is True
    assert work.stopped.wait(10.0)
    assert task.running and task.stopping
    assert task.start_until_stopped(_Step()) is False       # no second run while the first unwinds
    work.finish.set()
    assert pump_until(lambda: not task.running)
    assert results == ["stopped after one step"]
    assert task.stopping is False


def test_destroying_the_owner_sets_the_event():
    import shiboken6
    owner, work = QWidget(), _Step()
    assert TabTask(owner).start_until_stopped(work)
    shiboken6.delete(owner)
    try:
        assert work.stopped.wait(10.0)
    finally:
        work.finish.set()


def test_computer_use_stop_waits_for_the_run_and_shows_its_outcome(monkeypatch):
    work = _Step()
    monkeypatch.setattr(computer_use_tab, "run_computer_use", lambda stop_event=None, **_params: work(stop_event))
    monkeypatch.setattr(computer_use_tab, "result_to_dict", lambda result: {"succeeded": False, "detail": result})
    tab = computer_use_tab.ComputerUseTab()
    try:
        tab._goal_input.setText("open the editor")
        actions = dict(tab.menu_actions())
        actions["computer_use_run_btn"]()
        actions["computer_use_stop_btn"]()
        assert tab._status.text() == _t("computer_use_stopping")
        assert work.stopped.wait(10.0)
        actions["computer_use_run_btn"]()                    # still finishing its step
        assert tab._status.text() == _t("computer_use_already_running")
        work.finish.set()
        assert pump_until(lambda: tab._status.text() == _t("computer_use_failure"))
        assert "stopped after one step" in tab._output.toPlainText()
    finally:
        work.finish.set()
        tab.deleteLater()


def test_a_computer_use_error_names_its_type(monkeypatch):
    def run(stop_event=None, **_params):
        raise ValueError("no API key")

    monkeypatch.setattr(computer_use_tab, "run_computer_use", run)
    tab = computer_use_tab.ComputerUseTab()
    try:
        tab._goal_input.setText("open the editor")
        dict(tab.menu_actions())["computer_use_run_btn"]()
        assert pump_until(lambda: tab._status.text() == f"{_t('computer_use_error')}: ValueError: no API key")
    finally:
        tab.deleteLater()


def test_a_dag_stop_waits_for_the_run_and_shows_what_it_did(monkeypatch):
    import types
    work = _Step()

    def run(_definition, max_parallel=1, stop_event=None):
        work(stop_event)
        return types.SimpleNamespace(succeeded=False, elapsed_s=0.5, nodes={})

    monkeypatch.setattr(dag_tab, "run_dag", run)
    tab = dag_tab.DagTab()
    try:
        tab._editor.setPlainText('{"nodes": []}')
        actions = dict(tab.menu_actions())
        actions["dag_run_btn"]()
        tab._on_stop()
        assert tab._status_label.text() == _t("dag_stopping")
        assert work.stopped.wait(10.0)
        actions["dag_run_btn"]()                             # the run is still unwinding
        assert tab._status_label.text() == _t("dag_already_running")
        work.finish.set()
        assert pump_until(lambda: tab._status_label.text() == _t("dag_failure").replace("{seconds}", "0.50"))
    finally:
        work.finish.set()
        tab.deleteLater()
