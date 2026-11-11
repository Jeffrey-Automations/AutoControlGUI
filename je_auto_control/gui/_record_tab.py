"""Independent recording view and cancellable playback.

Playback runs off the GUI thread as a stoppable executor run, one at a time.
"""
import copy
import functools
import json

from typing import Callable

from PySide6.QtWidgets import (
    QFileDialog, QLabel, QMessageBox, QTextEdit, QVBoxLayout, QWidget,
)

from je_auto_control.gui._tab_task import TabTask, was_stopped
from je_auto_control.gui._i18n_helpers import TranslatableMixin
from je_auto_control.wrapper import auto_control_record
from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper
from je_auto_control.utils.exception.exceptions import AutoControlException
from je_auto_control.utils.executor.action_executor import execute_action
from je_auto_control.utils.json.json_file import read_action_json, write_action_json
from je_auto_control.wrapper.auto_control_record import record, stop_record

_JSON_FILE_FILTER = "JSON (*.json)"


def _t(key: str) -> str:
    """language_wrapper shorthand"""
    return language_wrapper.translate(key, key)


def _play_actions(actions: list) -> object:
    """Worker thread: replay a recording."""
    return execute_action(actions)


def _start_recording() -> None:
    if not record():
        raise AutoControlException("Recording could not start; see the log")


class RecordTab(TranslatableMixin, QWidget):
    """Owns playback and view state; the shared recorder outlives this page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tr_init()
        self._record_data: list = []
        layout = QVBoxLayout(self)

        # Record/playback/save/load all run from the Actions menu.
        self._record_status_key = "record_idle"
        self.record_status_label = QLabel()
        self._apply_record_status_label()
        layout.addWidget(self.record_status_label)

        layout.addWidget(self._tr(QLabel(), "record_list_label"))
        self.record_list_text = QTextEdit()
        self.record_list_text.setReadOnly(True)
        layout.addWidget(self.record_list_text)
        self._playback_runs = TabTask(self)
        self._playback_runs.error.connect(self._on_playback_error)
        self._playback_runs.finished.connect(self._on_playback_finished)
        self._work = TabTask(self)
        self._work.result.connect(self._on_result)
        self._work.error.connect(self._on_playback_error)
        self._work.finished.connect(self.sync_with_engine)
        self.sync_with_engine()

    def _apply_record_status_label(self) -> None:
        if hasattr(self, "record_status_label"):
            self.record_status_label.setText(
                self._translate("record_status") + " "
                + self._translate(self._record_status_key),
            )

    def retranslate(self) -> None:
        super().retranslate()
        self._apply_record_status_label()

    def _translate(self, key: str) -> str:
        return _t(key)

    def sync_with_engine(self) -> None:
        state = getattr(auto_control_record.recorder, "is_recording", None)
        self._record_status_key = (
            "task_running" if self._work.running else
            "record_playing" if self._playback_runs.running else
            "record_recording" if state is True else
            "record_idle" if state is False else "record_unknown"
        )
        self._apply_record_status_label()

    def showEvent(self, event) -> None:
        self.sync_with_engine()
        super().showEvent(event)

    def _start_work(self, work: Callable[[], object], *, tag: str = "") -> None:
        self._work.start(work, tag=tag)
        self.sync_with_engine()

    def _start_record(self):
        self._start_work(_start_recording, tag="start")

    def _stop_record(self):
        self._start_work(stop_record, tag="data")

    def _on_result(self, result: object) -> None:
        if self._work.tag == "data" and isinstance(result, list):
            self._record_data = result
            self.record_list_text.setText(json.dumps(result, indent=2, ensure_ascii=False))

    def _playback_record(self):
        if not self._record_data:
            QMessageBox.warning(self, "Warning", "No recorded data")
            return
        # The worker gets its own copy: loading or recording again while the
        # playback runs must not change the list under it.
        if not self._playback_runs.start_script(
                functools.partial(_play_actions, copy.deepcopy(self._record_data))):
            return
        self._record_status_key = "record_playing"
        self._apply_record_status_label()

    def _stop_playback(self) -> None:
        """Ask the running playback to stop; it ends at its next checkpoint."""
        self._playback_runs.stop()

    def _on_playback_error(self, error: object) -> None:
        if not was_stopped(error):
            QMessageBox.warning(self, "Error", str(error))

    def _on_playback_finished(self) -> None:
        self.sync_with_engine()

    def _save_record(self):
        try:
            if not self._record_data:
                QMessageBox.warning(self, "Warning", "No recorded data")
                return
            path, _ = QFileDialog.getSaveFileName(self, _t("save_record"), "", _JSON_FILE_FILTER)
            if path:
                self._start_work(functools.partial(write_action_json, path, copy.deepcopy(self._record_data)))
        except (AutoControlException, OSError, ValueError, TypeError, RuntimeError) as error:
            QMessageBox.warning(self, "Error", str(error))

    def _load_record(self):
        try:
            path, _ = QFileDialog.getOpenFileName(self, _t("load_record"), "", _JSON_FILE_FILTER)
            if path:
                self._start_work(functools.partial(read_action_json, path), tag="data")
        except (AutoControlException, OSError, ValueError, TypeError, RuntimeError) as error:
            QMessageBox.warning(self, "Error", str(error))

    def menu_actions(self) -> list[tuple[str, Callable]]:
        return [("start_record", self._start_record), ("stop_record", self._stop_record),
                ("playback", self._playback_record), ("stop_playback", self._stop_playback),
                ("save_record", self._save_record), ("load_record", self._load_record)]

    def dispose(self) -> None:
        self._playback_runs.stop()
        self._work.stop()
