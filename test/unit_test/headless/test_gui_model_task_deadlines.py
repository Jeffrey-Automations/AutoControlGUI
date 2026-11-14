"""The VLM tab and the LLM Planner's plan step: Stop, a deadline, and no late effect.

Both used to hand the model round trip to a bare worker: no Stop, no deadline,
and a VLM Click whose answer came back after the tab was closed still clicked.
They now run as :class:`~je_auto_control.gui._tab_task.TabTask` work.
"""
import functools
import os
import sys
import threading
import types

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from je_auto_control.gui import llm_planner_tab, vlm_tab  # noqa: E402
from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper  # noqa: E402
from je_auto_control.utils.vision import vlm_api  # noqa: E402
from je_auto_control.utils.vision.backends.base import VLMBackend  # noqa: E402
from headless._qt_settle import pump_until  # noqa: E402

_APP = QApplication.instance() or QApplication([])


def _t(key):
    return language_wrapper.translate(key, key)


class _SlowBackend(VLMBackend):
    """Answers ``(10, 20)`` once ``release`` is set."""

    name = "slow"
    available = True

    def __init__(self):
        self.release = threading.Event()
        self.asked = threading.Event()
        self.answered = threading.Event()

    def locate(self, image_bytes, description, model=None, image_mime="image/png"):
        self.asked.set()
        self.release.wait(30.0)
        self.answered.set()
        return (10, 20)


@pytest.fixture
def slow_click(monkeypatch):
    """The real ``click_by_description`` against a slow model and a recording mouse."""
    backend = _SlowBackend()
    moves = []
    mouse = types.ModuleType("je_auto_control.wrapper.auto_control_mouse")
    mouse.set_mouse_position = lambda x, y: moves.append(("move", x, y))
    mouse.click_mouse = lambda button, x, y: moves.append(("click", x, y))
    monkeypatch.setitem(sys.modules, "je_auto_control.wrapper.auto_control_mouse", mouse)
    monkeypatch.setattr(vlm_api, "_capture_screenshot_bytes", lambda screen_region=None: b"fake-png-bytes")
    monkeypatch.setattr(vlm_tab, "click_by_description",
                        functools.partial(vlm_api.click_by_description, backend=backend))
    tab = vlm_tab.VLMTab()
    tab._description.setText("the OK button")
    yield tab, backend, moves
    backend.release.set()
    tab.deleteLater()


def _menu(tab, key):
    return dict(tab.menu_actions())[key]


def test_a_stopped_vlm_click_does_not_click_when_the_model_answers(slow_click):
    tab, backend, moves = slow_click
    _menu(tab, "vlm_click")()
    assert backend.asked.wait(10.0)
    _menu(tab, "task_stop")()
    assert tab._status.text() == _t("task_stopped")
    assert not tab._task.running            # free for the next request at once
    backend.release.set()
    assert backend.answered.wait(10.0)
    # The model answered after the Stop; give the worker the chance to click.
    assert pump_until(lambda: moves != [], timeout=0.5) is False
    assert moves == []


def test_a_vlm_click_past_its_deadline_reports_it_and_does_not_click(slow_click, monkeypatch):
    tab, backend, moves = slow_click
    monkeypatch.setattr(vlm_tab, "REQUEST_DEADLINE_S", 0.05)
    _menu(tab, "vlm_click")()
    assert pump_until(lambda: tab._status.text() == _t("task_timed_out"))
    backend.release.set()
    assert backend.answered.wait(10.0)
    assert pump_until(lambda: moves != [], timeout=0.5) is False
    assert tab._status.text() == _t("task_timed_out")


def test_a_vlm_click_that_finishes_clicks(slow_click):
    tab, backend, moves = slow_click
    backend.release.set()
    _menu(tab, "vlm_click")()
    assert pump_until(lambda: tab._status.text() == _t("vlm_ok"))
    assert moves == [("move", 10, 20), ("click", 10, 20)]


def test_a_second_vlm_request_while_one_is_out_is_refused(slow_click):
    tab, backend, _moves = slow_click
    _menu(tab, "vlm_click")()
    _menu(tab, "vlm_locate")()
    assert tab._status.text() == _t("task_busy")


@pytest.fixture
def slow_plan(monkeypatch):
    release = threading.Event()

    def plan(description, known_commands=None, model=None):
        release.wait(30.0)
        return [["AC_x", {}]]

    monkeypatch.setattr(llm_planner_tab, "plan_actions", plan)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    tab = llm_planner_tab.LLMPlannerTab()
    tab._description.setPlainText("open the editor")
    yield tab, release, warnings
    release.set()
    tab.deleteLater()


def test_stop_drops_a_plan_still_out(slow_plan):
    tab, release, _warnings = slow_plan
    _menu(tab, "llm_plan_btn")()
    assert tab._plans.running
    _menu(tab, "task_stop")()
    assert tab._status.text() == _t("task_stopped")
    release.set()
    assert pump_until(lambda: tab._actions_view.toPlainText() != "", timeout=0.5) is False
    assert tab._planned_actions is None


def test_a_plan_past_its_deadline_says_so_without_a_dialog(slow_plan, monkeypatch):
    tab, _release, warnings = slow_plan
    monkeypatch.setattr(llm_planner_tab, "PLAN_DEADLINE_S", 0.05)
    _menu(tab, "llm_plan_btn")()
    assert pump_until(lambda: tab._status.text() == _t("task_timed_out"))
    assert warnings == []
    assert tab._planned_actions is None


def test_a_plan_that_fails_shows_its_error(monkeypatch):
    def plan(description, known_commands=None, model=None):
        raise ValueError("no plan")

    monkeypatch.setattr(llm_planner_tab, "plan_actions", plan)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    tab = llm_planner_tab.LLMPlannerTab()
    try:
        tab._description.setPlainText("open the editor")
        _menu(tab, "llm_plan_btn")()
        assert pump_until(lambda: tab._status.text() == "ValueError: no plan")
        assert len(warnings) == 1
    finally:
        tab.deleteLater()
