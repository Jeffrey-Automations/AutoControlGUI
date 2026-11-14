"""LLM Planner tab: describe a task in plain language → preview → run.

The tab calls the headless ``plan_actions`` helper, shows the resulting
JSON action list for review, and lets the user execute it through the
shared global executor. Planning and running both happen off the GUI thread
as :class:`~je_auto_control.gui._tab_task.TabTask` work, one of each at a time:
a run is a stoppable executor run, and a plan has a deadline and is dropped
when stopped. The Actions menu's Stop ends whichever is going.
"""
import copy
import functools
import json
from typing import List, Optional

from PySide6.QtWidgets import (
    QFormLayout, QGroupBox, QLabel, QLineEdit, QMessageBox,
    QTextEdit, QVBoxLayout, QWidget,
)

from je_auto_control.gui._dispose import release_resources
from je_auto_control.gui._i18n_helpers import TranslatableMixin
from je_auto_control.gui._tab_task import TabTask, was_stopped
from je_auto_control.gui.adaptive.responsive import ResponsiveBox
from je_auto_control.gui.adaptive.surfaces import set_role
from je_auto_control.gui.language_wrapper.multi_language_wrapper import (
    language_wrapper,
)
from je_auto_control.gui.tab_task_controller import TaskTimeout
from je_auto_control.utils.executor.action_executor import execute_action, executor
from je_auto_control.utils.llm.backends.base import LLMNotAvailableError
from je_auto_control.utils.llm.planner import plan_actions


def _t(key: str) -> str:
    return language_wrapper.translate(key, key)


def _run_plan(actions: list) -> object:
    """Worker thread: execute the reviewed plan."""
    return execute_action(actions)


#: How long one plan may take. The backend gives a request 60 s and its SDK
#: retries a failed one twice, so this leaves room for all three tries.
PLAN_DEADLINE_S = 200.0


def _plan(description: str, model: Optional[str], known_commands: List[str]) -> list:
    """Worker thread: ask the model for a plan."""
    return plan_actions(description, known_commands=known_commands, model=model)


def _plan_error_text(error: object) -> str:
    """What the status line says about a plan that failed."""
    if isinstance(error, TaskTimeout):
        return _t("task_timed_out")
    if isinstance(error, LLMNotAvailableError):
        return str(error)
    return f"{type(error).__name__}: {error}"


class LLMPlannerTab(TranslatableMixin, QWidget):
    """Translate plain-language descriptions into runnable AC_* scripts."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tr_init()
        self._description = QTextEdit()
        self._model = QLineEdit()
        self._actions_view = QTextEdit()
        self._actions_view.setReadOnly(True)
        self._result_view = QTextEdit()
        self._result_view.setReadOnly(True)
        self._status = QLabel()
        self._planned_actions: Optional[list] = None
        self._plans = TabTask(self)
        self._plans.result.connect(self._on_plan_finished)
        self._plans.error.connect(self._on_plan_failed)
        self._runs = TabTask(self)
        self._runs.result.connect(self._show_run_result)
        self._runs.error.connect(self._show_run_error)
        self._build_layout()
        self._apply_placeholders()

    def retranslate(self) -> None:
        TranslatableMixin.retranslate(self)
        self._apply_placeholders()

    def _apply_placeholders(self) -> None:
        self._description.setPlaceholderText(_t("llm_desc_placeholder"))
        self._model.setPlaceholderText(_t("llm_model_placeholder"))

    def _build_layout(self) -> None:
        # Plan/run commands run from the Actions menu; the tab keeps only
        # the description/model inputs, the plan/result views, and status.
        root = QVBoxLayout(self)
        root.setSpacing(12)

        desc_group = self._tr(QGroupBox(), "llm_desc_group")
        desc_layout = QVBoxLayout()
        desc_layout.addWidget(self._description)
        model_row = QFormLayout()
        model_row.addRow(self._tr(QLabel(), "llm_model_label"), self._model)
        desc_layout.addLayout(model_row)
        desc_group.setLayout(desc_layout)
        root.addWidget(desc_group)

        actions_group = self._tr(QGroupBox(), "llm_plan_group")
        actions_layout = QVBoxLayout()
        actions_layout.addWidget(self._actions_view)
        actions_group.setLayout(actions_layout)

        result_group = self._tr(QGroupBox(), "llm_result_group")
        result_layout = QVBoxLayout()
        result_layout.addWidget(self._result_view)
        result_group.setLayout(result_layout)
        root.addWidget(ResponsiveBox(actions_group, result_group), stretch=1)

        self._status.setWordWrap(True)
        set_role(self._status, "hint")
        root.addWidget(self._status)

    def dispose(self) -> None:
        """Release what the tab holds beyond its widgets: the command still running in the background.

        A script run is stopped; a plan still out is cancelled: the request runs to its end and
        its answer is dropped. Called by ``close_tab(key, release=True)``; safe to call twice.
        """
        release_resources(self)

    def menu_actions(self) -> list:
        """Expose tab commands to the window-level Actions menu."""
        return [
            ("llm_plan_btn", self._on_plan),
            ("llm_run_btn", self._on_run),
            ("task_stop", self._on_stop),
        ]

    def _on_plan(self) -> None:
        description = self._description.toPlainText().strip()
        if not description:
            self._status.setText(_t("llm_desc_required"))
            return
        model = self._model.text().strip() or None
        work = functools.partial(_plan, description, model, sorted(executor.known_commands()))
        if not self._plans.start(work, timeout_s=PLAN_DEADLINE_S):
            self._status.setText(_t("task_busy"))
            return
        self._status.setText(_t("llm_planning"))
        self._actions_view.clear()
        self._planned_actions = None

    def _on_plan_finished(self, actions: list) -> None:
        self._planned_actions = actions
        self._actions_view.setText(
            json.dumps(actions, indent=2, ensure_ascii=False)
        )
        self._status.setText(
            _t("llm_plan_count").replace("{n}", str(len(actions)))
        )

    def _on_plan_failed(self, error: object) -> None:
        self._planned_actions = None
        message = _plan_error_text(error)
        if not isinstance(error, TaskTimeout):
            QMessageBox.warning(self, _t("llm_plan_btn"), message)
        self._status.setText(message)

    def _on_run(self) -> None:
        if not self._planned_actions:
            self._status.setText(_t("llm_no_plan"))
            return
        if not self._runs.start_script(
                functools.partial(_run_plan, copy.deepcopy(self._planned_actions))):
            self._status.setText(_t("task_busy"))
            return
        self._status.setText(_t("llm_running"))

    def _on_stop(self) -> None:
        if self._runs.stop():
            self._status.setText(_t("task_stopping"))
        elif self._plans.stop():
            self._status.setText(_t("task_stopped"))

    def _show_run_result(self, record: object) -> None:
        self._result_view.setText(
            json.dumps(record, indent=2, ensure_ascii=False, default=str)
        )
        self._status.setText(_t("llm_run_done"))

    def _show_run_error(self, error: object) -> None:
        if was_stopped(error):
            self._status.setText(_t("task_stopped"))
            return
        QMessageBox.warning(self, _t("llm_run_btn"), str(error))
        self._status.setText(str(error))
