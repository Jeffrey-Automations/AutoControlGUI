"""Independent image-detection panel with owned inputs and cancellable background work."""
from dataclasses import dataclass
from functools import partial
import math
from typing import Callable, Literal

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QGridLayout, QLabel, QLineEdit, QMessageBox,
    QTextEdit, QVBoxLayout, QWidget,
)

from je_auto_control.gui._i18n_helpers import TranslatableMixin
from je_auto_control.gui._tab_task import TabTask
from je_auto_control.gui._validators import double_validator
from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper
from je_auto_control.gui.selector import crop_template_to_file
from je_auto_control.utils.exception.exceptions import AutoControlException
from je_auto_control.wrapper.auto_control_image import locate_all_image, locate_image_center, locate_and_click
from je_auto_control.wrapper.auto_control_mouse import mouse_keys_table


def _t(key: str) -> str:
    return language_wrapper.translate(key, key)


@dataclass(frozen=True)
class _Detection:
    operation: Literal["center", "all", "click"]
    path: str
    threshold: float
    draw: bool
    button: str


def _detect(request: _Detection) -> str:
    if request.operation == "center":
        return f"Center: {locate_image_center(request.path, request.threshold, request.draw)}"
    if request.operation == "all":
        matches = locate_all_image(request.path, request.threshold, request.draw)
        return f"Found {len(matches)} matches:\n{matches}"
    point = locate_and_click(request.path, request.button, request.threshold, request.draw)
    return f"Clicked at: {point}"


class ImageDetectionTab(TranslatableMixin, QWidget):
    """Own image-detection inputs, result state and worker lifetime."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tr_init()
        layout = QVBoxLayout(self)
        grid = QGridLayout()
        grid.addWidget(self._tr(QLabel(), "template_image"), 0, 0)
        self.img_path_input = QLineEdit()
        grid.addWidget(self.img_path_input, 0, 1)
        grid.addWidget(self._tr(QLabel(), "threshold_label"), 1, 0)
        self.threshold_input = QLineEdit("0.8")
        self.threshold_input.setValidator(double_validator(0.0, 1.0, 2))
        grid.addWidget(self.threshold_input, 1, 1)
        self.draw_check = self._tr(QCheckBox(), "draw_image_check")
        grid.addWidget(self.draw_check, 1, 2)
        grid.addWidget(self._tr(QLabel(), "mouse_button"), 2, 0)
        self.mouse_button_combo = QComboBox()
        self.mouse_button_combo.addItems(list(mouse_keys_table))
        self.mouse_button_combo.setCurrentText("mouse_left")
        grid.addWidget(self.mouse_button_combo, 2, 1)
        layout.addLayout(grid)
        layout.addWidget(self._tr(QLabel(), "detection_result"))
        self.detect_result_text = QTextEdit()
        self.detect_result_text.setReadOnly(True)
        layout.addWidget(self.detect_result_text)
        self._status_key = ""
        self._task = TabTask(self)
        self._task.result.connect(self._on_result)
        self._task.error.connect(self._on_error)
        self._task.finished.connect(self._on_finished)

    def menu_actions(self) -> list[tuple[str, Callable[[], object]]]:
        """Expose file selection, detection and cancellation through Actions."""
        return [
            ("browse", self._browse_img), ("crop_template", self._crop_template),
            ("locate_image", self._locate_image), ("locate_all", self._locate_all),
            ("locate_click", self._locate_click), ("task_stop", self._stop),
        ]

    def _browse_img(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, _t("template_image"), "", "Images (*.png *.jpg *.bmp);;All (*)")
        if path:
            self.img_path_input.setText(path)

    def _crop_template(self) -> None:
        if self._task.running:
            return
        save_path, _ = QFileDialog.getSaveFileName(self, _t("crop_template"), "", "PNG (*.png)")
        if not save_path:
            return
        try:
            region = crop_template_to_file(save_path, self)
            if region is not None:
                self.img_path_input.setText(save_path)
                self._on_result(f"Template saved: {save_path} region={region}")
        except (AutoControlException, OSError, ValueError, RuntimeError) as error:
            QMessageBox.warning(self, "Error", str(error))

    def _start(self, operation: Literal["center", "all", "click"]) -> None:
        if self._task.running:
            return
        try:
            path = self.img_path_input.text()
            if not path:
                raise ValueError("Template image path is empty")
            threshold = float(self.threshold_input.text() or "0.8")
            if not math.isfinite(threshold) or not 0 <= threshold <= 1:
                raise ValueError("Threshold must be between 0 and 1")
            request = _Detection(operation, path, threshold, self.draw_check.isChecked(),
                                 self.mouse_button_combo.currentText())
        except (ValueError, TypeError) as error:
            self._on_error(error)
            return
        if self._task.start(partial(_detect, request)):
            self._status_key = "task_running"
            self.detect_result_text.setText(_t(self._status_key))

    def _locate_image(self) -> None:
        self._start("center")

    def _locate_all(self) -> None:
        self._start("all")

    def _locate_click(self) -> None:
        self._start("click")

    def _stop(self) -> None:
        if self._task.running:
            self._status_key = "task_stopping"
            self.detect_result_text.setText(_t(self._status_key))
            self._task.stop()

    def _on_result(self, result: str) -> None:
        self._status_key = ""
        self.detect_result_text.setText(result)

    def _on_error(self, error: object) -> None:
        self._on_result(f"Error: {error}")

    def _on_finished(self) -> None:
        if self._status_key in {"task_running", "task_stopping"}:
            self._status_key = "task_stopped"
            self.detect_result_text.setText(_t(self._status_key))

    def retranslate(self) -> None:
        """Refresh labels and transient status without discarding the last result."""
        super().retranslate()
        if self._status_key:
            self.detect_result_text.setText(_t(self._status_key))

    def dispose(self) -> None:
        """Cancel pending work and drop late outcomes; entered native calls may finish."""
        self._task.stop()
