"""Computer-Use tab: launch Anthropic's closed-loop agent from the GUI.

The run is a :class:`~je_auto_control.gui._tab_task.TabTask` started with
``start_until_stopped``: Stop ends it before its next step, and the tab stays
busy until it has, so a second run cannot start while the first still drives
the mouse. Closing the tab stops the run the same way and drops its outcome.
"""
import functools
import json
import threading
from typing import Optional

from PySide6.QtWidgets import (
    QFormLayout, QLabel, QLineEdit, QMessageBox,
    QSpinBox, QTextEdit, QVBoxLayout, QWidget,
)

from je_auto_control.gui._dispose import release_resources
from je_auto_control.gui._i18n_helpers import TranslatableMixin
from je_auto_control.gui._tab_task import TabTask
from je_auto_control.gui.adaptive.surfaces import Card, set_role
from je_auto_control.gui.language_wrapper.multi_language_wrapper import (
    language_wrapper,
)
from je_auto_control.utils.agent.computer_use import (
    result_to_dict, run_computer_use,
)


def _t(key: str) -> str:
    return language_wrapper.translate(key, key)


def _run_agent(params: dict, stop_event: threading.Event) -> dict:
    """Worker thread: run the agent until it finishes, hits a limit or ``stop_event`` is set."""
    return result_to_dict(run_computer_use(**params, stop_event=stop_event))


class ComputerUseTab(TranslatableMixin, QWidget):
    """Drive Anthropic Computer-Use against the current screen."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tr_init()
        self._goal_input = QLineEdit()
        self._model_input = QLineEdit("claude-opus-4-7")
        self._max_steps = QSpinBox()
        self._max_steps.setRange(1, 200)
        self._max_steps.setValue(25)
        self._wall_seconds = QSpinBox()
        self._wall_seconds.setRange(10, 3600)
        self._wall_seconds.setValue(300)
        self._max_tokens = QSpinBox()
        self._max_tokens.setRange(64, 8192)
        self._max_tokens.setValue(1024)
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._status = QLabel()
        # Stop ends the run before its next step; the tab stays busy until it has.
        self._run = TabTask(self)
        self._run.result.connect(self._on_worker_finished)
        self._run.error.connect(self._on_worker_failed)
        self._build_layout()

    def retranslate(self) -> None:
        TranslatableMixin.retranslate(self)
        self._apply_translations()

    # --- layout ----------------------------------------------------

    def _build_layout(self) -> None:
        # The run command runs from the Actions menu; the tab keeps only
        # the goal/model/limit inputs, the output view, and the status.
        root = QVBoxLayout(self)
        root.setSpacing(12)
        form = QFormLayout()
        self._goal_label = QLabel()
        self._model_label = QLabel()
        self._max_steps_label = QLabel()
        self._wall_seconds_label = QLabel()
        self._max_tokens_label = QLabel()
        form.addRow(self._goal_label, self._goal_input)
        form.addRow(self._model_label, self._model_input)
        form.addRow(self._max_steps_label, self._max_steps)
        form.addRow(self._wall_seconds_label, self._wall_seconds)
        form.addRow(self._max_tokens_label, self._max_tokens)
        root.addWidget(Card().add(form))
        self._output_label = QLabel()
        output = Card()
        output.add(self._output_label)
        output.add(self._output, stretch=1)
        root.addWidget(output, stretch=1)
        self._status.setWordWrap(True)
        set_role(self._status, "hint")
        root.addWidget(self._status)
        self._apply_translations()

    def _apply_translations(self) -> None:
        self._goal_label.setText(_t("computer_use_goal_label"))
        self._model_label.setText(_t("computer_use_model_label"))
        self._max_steps_label.setText(_t("computer_use_max_steps_label"))
        self._wall_seconds_label.setText(_t("computer_use_wall_seconds_label"))
        self._max_tokens_label.setText(_t("computer_use_max_tokens_label"))
        self._output_label.setText(_t("computer_use_output_label"))
        self._goal_input.setPlaceholderText(_t("computer_use_goal_placeholder"))

    def dispose(self) -> None:
        """Release what the tab holds beyond its widgets: the run still out, which is asked to stop.

        The worker ends before its next step and its outcome is dropped. Called by
        ``close_tab(key, release=True)`` before the widget is deleted; safe to call twice.
        """
        release_resources(self)

    def menu_actions(self) -> list:
        """Expose tab commands to the window-level Actions menu."""
        return [
            ("computer_use_run_btn", self._on_run),
            ("computer_use_stop_btn", self._on_stop),
        ]

    # --- run path --------------------------------------------------

    def _on_run(self) -> None:
        goal = self._goal_input.text().strip()
        if not goal:
            QMessageBox.warning(
                self, _t("computer_use_run_btn"),
                _t("computer_use_goal_required"),
            )
            return
        if self._run.running:
            self._status.setText(_t("computer_use_already_running"))
            return
        params = {
            "goal": goal,
            "model": self._model_input.text().strip() or "claude-opus-4-7",
            "max_steps": int(self._max_steps.value()),
            "wall_seconds": float(self._wall_seconds.value()),
            "max_tokens": int(self._max_tokens.value()),
        }
        self._status.setText(_t("computer_use_running"))
        self._spawn_worker(params)

    def _spawn_worker(self, params: dict) -> None:
        self._run.start_until_stopped(functools.partial(_run_agent, dict(params)))

    def _on_stop(self) -> None:
        if self._run.stop():
            self._status.setText(_t("computer_use_stopping"))

    def _on_worker_finished(self, data: dict) -> None:
        ok = bool(data.get("succeeded"))
        key = "computer_use_success" if ok else "computer_use_failure"
        self._status.setText(_t(key))
        self._output.setPlainText(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
        )

    def _on_worker_failed(self, error: object) -> None:
        self._status.setText(f"{_t('computer_use_error')}: {type(error).__name__}: {error}")


__all__ = ["ComputerUseTab"]
