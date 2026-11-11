"""Independent script-executor panel with owned background runs.

The three execute commands run the action list off the GUI thread, one run at
a time, as a stoppable executor run: the window stays responsive while a
script drives the desktop (or this window), and ``script_stop`` / Ctrl+4 end
the run at its next checkpoint.
"""
import functools
import json

from contextlib import nullcontext
from typing import Any, Callable, ContextManager

from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QTextEdit, QVBoxLayout,
    QWidget,
)

from je_auto_control.gui._tab_task import TabTask, was_stopped
from je_auto_control.gui._i18n_helpers import TranslatableMixin
from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper
from je_auto_control.gui.manual_run_controls import ManualRunControls, _requested_manual_run
from je_auto_control.utils.executor.action_executor import execute_action, execute_files
from je_auto_control.utils.file_process.get_dir_file_list import get_dir_files_as_list
from je_auto_control.utils.json.json_file import (
    read_action_json, read_executable_action_json,
)

_JSON_FILE_FILTER = "JSON (*.json)"


def _t(key: str) -> str:
    """language_wrapper shorthand"""
    return language_wrapper.translate(key, key)


def _run_script_file(path: str, capture: Callable[[], ContextManager[object]] = nullcontext) -> Any:
    """Worker thread: load and execute one action file, inside the capture the tab asked for."""
    with capture():
        return execute_action(read_executable_action_json(path))


def _run_script_dir(path: str, capture: Callable[[], ContextManager[object]] = nullcontext) -> Any:
    """Worker thread: execute every action file under ``path``, inside the capture the tab asked for."""
    with capture():
        return execute_files(get_dir_files_as_list(path))


def _run_script_text(text: str, capture: Callable[[], ContextManager[object]] = nullcontext) -> Any:
    """Worker thread: execute the action list typed into the editor, inside the capture the tab asked for."""
    with capture():
        return execute_action(json.loads(text))


class ScriptTab(TranslatableMixin, QWidget):
    """Own script inputs, manual capture settings and a stoppable background run."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tr_init()
        self._status_key = ""
        layout = QVBoxLayout(self)
        file_h = QHBoxLayout()
        file_h.addWidget(self._tr(QLabel(), "file_path_label"))
        self.script_path_input = QLineEdit()
        file_h.addWidget(self.script_path_input)
        layout.addLayout(file_h)

        dir_h = QHBoxLayout()
        dir_h.addWidget(self._tr(QLabel(), "execute_dir_label"))
        self.script_dir_input = QLineEdit()
        dir_h.addWidget(self.script_dir_input)
        layout.addLayout(dir_h)

        layout.addWidget(self._tr(QLabel(), "script_content"))
        self.script_editor = QTextEdit()
        self.script_editor.setPlaceholderText('[["AC_type_keyboard", {"keycode": "a"}]]')
        layout.addWidget(self.script_editor)

        self.script_history_controls = ManualRunControls()
        layout.addWidget(self.script_history_controls)
        layout.addWidget(self._tr(QLabel(), "execution_result"))
        self.script_result_text = QTextEdit()
        self.script_result_text.setReadOnly(True)
        layout.addWidget(self.script_result_text)
        self._loads = TabTask(self)
        self._loads.result.connect(self._loaded_script)
        self._loads.error.connect(self._load_error)
        self._script_runs = TabTask(self)
        self._script_runs.result.connect(self._show_script_result)
        self._script_runs.error.connect(self._show_script_error)
        self._script_runs.finished.connect(self._on_finished)

    def _start_script_run(self, work: Callable[[], Any]) -> None:
        """Run ``work`` as this tab's one stoppable script run."""
        if not self._script_runs.start_script(work):
            self.script_result_text.setText(_t("task_busy"))
            return
        self._status_key = "task_running"
        self.script_result_text.setText(_t(self._status_key))

    def _show_script_result(self, result: object) -> None:
        self._status_key = ""
        self.script_result_text.setText(json.dumps(result, indent=2, default=str, ensure_ascii=False))

    def _show_script_error(self, error: object) -> None:
        self._status_key = ""
        if was_stopped(error):
            self.script_result_text.setText(_t("task_stopped"))
            return
        self.script_result_text.setText(f"Error: {error}")

    def _stop_script(self) -> None:
        """Ask the running script to stop; it ends at its next checkpoint."""
        if self._script_runs.running:
            self._status_key = "task_stopping"
            self.script_result_text.setText(_t(self._status_key))
            self._script_runs.stop()

    def _browse_script(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, _t("load_script"), "", _JSON_FILE_FILTER)
        if path:
            self.load_script(path)

    def load_script(self, path: str) -> None:
        """Load a chosen file without starting execution."""
        if self._loads.start(functools.partial(read_action_json, path)):
            self.script_path_input.setText(path)

    def _loaded_script(self, data: object) -> None:
        self.script_editor.setText(json.dumps(data, indent=2, ensure_ascii=False))

    def _load_error(self, error: object) -> None:
        self.script_result_text.setText(f"Error loading: {error}")

    def _execute_script(self):
        path = self.script_path_input.text()
        if path:
            capture = _requested_manual_run(getattr(self, "script_history_controls", None),
                                            source_id="gui.file", script_path=path)
            self._start_script_run(functools.partial(_run_script_file, path, capture))

    def _browse_script_dir(self):
        path = QFileDialog.getExistingDirectory(self, _t("execute_dir_label"))
        if path:
            self.script_dir_input.setText(path)

    def _execute_dir(self):
        path = self.script_dir_input.text()
        if path:
            capture = _requested_manual_run(getattr(self, "script_history_controls", None),
                                            source_id="gui.directory", script_path=path)
            self._start_script_run(functools.partial(_run_script_dir, path, capture))

    def _execute_manual_script(self):
        text = self.script_editor.toPlainText().strip()
        if text:
            capture = _requested_manual_run(getattr(self, "script_history_controls", None),
                                            source_id="gui.editor", script_path="<editor>")
            self._start_script_run(functools.partial(_run_script_text, text, capture))

    def _on_finished(self) -> None:
        if self._status_key in {"task_running", "task_stopping"}:
            self._status_key = "task_stopped"
            self.script_result_text.setText(_t(self._status_key))

    def menu_actions(self) -> list[tuple[str, Callable[[], object]]]:
        """Expose loading, execution and Stop through Actions."""
        return [("load_script", self._browse_script), ("execute_script", self._execute_script),
                ("menu_choose_script_dir", self._browse_script_dir), ("execute_dir", self._execute_dir),
                ("execute_editor_script", self._execute_manual_script), ("task_stop", self._stop_script)]

    def retranslate(self) -> None:
        """Refresh labels and transient status while preserving output."""
        super().retranslate()
        self.script_history_controls.retranslate()
        if self._status_key:
            self.script_result_text.setText(_t(self._status_key))

    def dispose(self) -> None:
        """Stop this page's run; its controller discards outcomes after destruction."""
        self._script_runs.stop()
        self._loads.stop()
