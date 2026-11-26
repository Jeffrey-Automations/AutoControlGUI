"""Trace Replay tab — scrub through a time-travel recording.

Loads a directory containing ``manifest.json`` + ``actions.jsonl``
written by :class:`JpegSequenceRecorder` and shows the screenshot at
the selected step plus the actions that ran in its window. Pure
display + navigation; the real timeline logic lives in
:class:`TraceReplayController` so it can be unit-tested without Qt.

Opening a recording (its manifest and action log) and reading each frame run
as :class:`~je_auto_control.gui._tab_task.TabTask` work. Scrubbing asks for
one frame at a time: a step taken while a frame is still being read replaces
the frame waiting behind it, so only the latest is read next. A frame's file
name comes from ``manifest.json`` and is bounded to the recording directory
with :func:`~je_auto_control.utils.path_guard.path_guard.validate_path`, as the
headless player does.
"""
import functools
import json
from pathlib import Path
from typing import Callable, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QLabel, QMessageBox, QSlider,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from je_auto_control.gui._dispose import release_resources
from je_auto_control.gui._i18n_helpers import TranslatableMixin
from je_auto_control.gui._qt_typed import decoded_image
from je_auto_control.gui._tab_task import TabTask
from je_auto_control.gui.adaptive.responsive import ResponsiveSplitter, fit_columns
from je_auto_control.gui.adaptive.surfaces import Card, set_role
from je_auto_control.gui.language_wrapper.multi_language_wrapper import (
    language_wrapper,
)
from je_auto_control.utils.path_guard.path_guard import validate_path
from je_auto_control.utils.time_travel import (
    ReplayState, TimelinePlayer, TraceReplayController,
)


def _t(key: str) -> str:
    return language_wrapper.translate(key, key)


def _open_controller(directory: str) -> TraceReplayController:
    """Read the recording's manifest and action log (a worker thread, from the tab)."""
    return TraceReplayController(TimelinePlayer(directory))


def _read_frame(directory: Path, filename: str) -> QImage:
    """Worker thread: one frame, decoded; a file name leading outside the recording raises ``PathNotAllowedError``."""
    target = validate_path(directory / filename, allowed_roots=[directory])
    return decoded_image(target.read_bytes(), "JPEG")


_ACTION_COLUMNS = ("timestamp", "action_name", "args", "error")


class TraceReplayTab(TranslatableMixin, QWidget):
    """Open a recording, scrub the timeline, inspect per-step actions."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tr_init()
        self._controller: Optional[TraceReplayController] = None
        self._frame_label = QLabel()
        self._frame_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._frame_label.setTextFormat(Qt.TextFormat.PlainText)     # a failed read's error, never markup
        self._frame_label.setMinimumSize(320, 240)
        self._frame_label.setStyleSheet("background-color: #1e1e1e;")
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setMinimum(0)
        self._slider.setMaximum(0)
        self._slider.valueChanged.connect(self._on_slider_changed)
        self._status = QLabel()
        self._status_text = self._keyed(self._status)
        self._actions_table = QTableWidget(0, len(_ACTION_COLUMNS))
        self._opening = TabTask(self)                  # the manifest and the action log
        self._opening.result.connect(self._install)
        self._opening.error.connect(self._on_open_failed)
        self._frames = TabTask(self, details=False)    # one frame read at a time, while scrubbing
        self._frames.result.connect(self._show_frame)
        self._frames.error.connect(self._on_frame_failed)
        self._frames.finished.connect(self._read_wanted_frame)
        self._wanted_frame: Optional[Tuple[Path, str]] = None
        self._build_layout()

    def dispose(self) -> None:
        """Cancel an open or frame read still out; its answer is dropped. Safe to call twice."""
        self._wanted_frame = None
        release_resources(self)

    def retranslate(self) -> None:
        TranslatableMixin.retranslate(self)
        self._apply_translations()

    # --- layout ---------------------------------------------------

    def _build_layout(self) -> None:
        # Open/first/prev/next/last commands run from the Actions menu;
        # the tab keeps only the slider, frame, table, and status.
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.addWidget(Card().add(self._slider))
        frame = Card().add(self._frame_label, stretch=1)
        actions = Card().add(self._actions_table, stretch=1)
        root.addWidget(ResponsiveSplitter(frame, actions, stretches=(3, 2)), stretch=1)
        self._status.setWordWrap(True)
        set_role(self._status, "hint")
        root.addWidget(self._status)
        self._apply_translations()

    def menu_actions(self) -> list[tuple[str, Callable[[], None]]]:
        """Expose tab commands to the window-level Actions menu."""
        return [
            ("trace_open_btn", self._on_open),
            ("trace_first_btn", self._on_first),
            ("trace_prev_btn", self._on_prev),
            ("trace_next_btn", self._on_next),
            ("trace_last_btn", self._on_last),
        ]

    def _apply_translations(self) -> None:
        headers = [_t(f"trace_col_{col}") for col in _ACTION_COLUMNS]
        self._actions_table.setHorizontalHeaderLabels(headers)

    # --- public ---------------------------------------------------

    def load_recording(self, directory: str) -> None:
        """Open ``directory`` now, on the calling thread, and wire it into the slider + table."""
        self._install(_open_controller(directory))

    def _install(self, controller: TraceReplayController) -> None:
        self._controller = controller
        total = max(0, self._controller.total_steps - 1)
        self._slider.blockSignals(True)
        self._slider.setMaximum(total)
        self._slider.setValue(0)
        self._slider.blockSignals(False)
        self._render(self._controller.state())

    # --- handlers -------------------------------------------------

    def _on_open(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, _t("trace_open_btn"),
        )
        if not directory:
            return
        if not self._opening.start(functools.partial(_open_controller, directory)):
            self._status_text.show("task_busy")
            return
        self._status_text.show("task_running")

    def _on_open_failed(self, error: object) -> None:
        # A truncated manifest.json used to escape the slot as JSONDecodeError.
        self._status_text.clear()
        QMessageBox.warning(self, _t("trace_open_btn"), str(error))

    def _on_first(self) -> None:
        if self._controller is None:
            return
        self._render(self._controller.jump_to_start())

    def _on_last(self) -> None:
        if self._controller is None:
            return
        self._render(self._controller.jump_to_end())

    def _on_prev(self) -> None:
        if self._controller is None:
            return
        self._render(self._controller.step_backward())

    def _on_next(self) -> None:
        if self._controller is None:
            return
        self._render(self._controller.step_forward())

    def _on_slider_changed(self, value: int) -> None:
        if self._controller is None:
            return
        self._render(self._controller.seek(int(value)))

    # --- rendering ------------------------------------------------

    def _render(self, state: ReplayState) -> None:
        self._slider.blockSignals(True)
        self._slider.setValue(state.step)
        self._slider.blockSignals(False)
        self._status_text.show("trace_status", step=state.step + 1, total=max(state.total_steps, 1),
                               seconds=f"{state.relative_time_s:.2f}")
        self._render_frame(state)
        self._render_actions(state)

    def _render_frame(self, state: ReplayState) -> None:
        if (state.frame_filename is None or self._controller is None
                or self._controller.player.directory is None):
            self._wanted_frame = None
            self._frame_label.clear()
            return
        self._wanted_frame = (Path(self._controller.player.directory), state.frame_filename)
        self._read_wanted_frame()

    def _read_wanted_frame(self) -> None:
        """Read the latest frame asked for, unless one is being read already (it is asked for again once done)."""
        if self._wanted_frame is None or self._frames.running:
            return
        directory, filename = self._wanted_frame
        self._wanted_frame = None
        self._frames.start(functools.partial(_read_frame, directory, filename))

    def _on_frame_failed(self, error: object) -> None:
        if self._wanted_frame is None:      # a newer frame replaces this one's error
            self._frame_label.setText(str(error))

    def _show_frame(self, image: QImage) -> None:
        if self._wanted_frame is not None:  # the user moved on; the newer frame is read next
            return
        if image.isNull():
            self._frame_label.clear()
            return
        scaled = QPixmap.fromImage(image).scaled(
            self._frame_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._frame_label.setPixmap(scaled)

    def _render_actions(self, state: ReplayState) -> None:
        self._actions_table.setRowCount(len(state.actions))
        for row, action in enumerate(state.actions):
            values = (
                f"{float(action.get('timestamp', 0.0)):.3f}",
                str(action.get("action_name", "")),
                json.dumps(action.get("args") or {}, ensure_ascii=False),
                str(action.get("error") or ""),
            )
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                self._actions_table.setItem(row, col, item)
        fit_columns(self._actions_table)


__all__ = ["TraceReplayTab"]
