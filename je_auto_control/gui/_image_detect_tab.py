"""Independent image-detection panel with owned inputs and cancellable background work."""
from dataclasses import dataclass
from functools import partial
import math
from typing import Callable, Literal

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QLabel, QLineEdit, QMessageBox,
    QTextEdit, QVBoxLayout, QWidget,
)

from je_auto_control.gui._i18n_helpers import TranslatableMixin
from je_auto_control.gui._tab_task import TabTask
from je_auto_control.gui._validators import double_validator
from je_auto_control.gui.adaptive.surfaces import Card, set_role
from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper
from je_auto_control.gui.selector.region_selector import open_region_selector
from je_auto_control.gui.selector.template_cropper import save_region_template
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


def _save_template(save_path: str, region: tuple[int, int, int, int]) -> str:
    """Worker thread: grab ``region`` and write it to ``save_path``; the line the tab shows."""
    saved = save_region_template(save_path, region)
    return f"Template saved: {save_path} region={saved}"


class ImageDetectionTab(TranslatableMixin, QWidget):
    """Own image-detection inputs, result state and worker lifetime."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tr_init()
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        form = QFormLayout()
        self.img_path_input = QLineEdit()
        form.addRow(self._tr(QLabel(), "template_image"), self.img_path_input)
        self.threshold_input = QLineEdit("0.8")
        self.threshold_input.setValidator(double_validator(0.0, 1.0, 2))
        form.addRow(self._tr(QLabel(), "threshold_label"), self.threshold_input)
        self.mouse_button_combo = QComboBox()
        self.mouse_button_combo.addItems(list(mouse_keys_table))
        self.mouse_button_combo.setCurrentText("mouse_left")
        form.addRow(self._tr(QLabel(), "mouse_button"), self.mouse_button_combo)
        self.draw_check = self._tr(QCheckBox(), "draw_image_check")
        form.addRow(self.draw_check)
        layout.addWidget(Card().add(form))
        result_card = Card().add(set_role(self._tr(QLabel(), "detection_result"), "sectionTitle"))
        self.detect_result_text = QTextEdit()
        self.detect_result_text.setReadOnly(True)
        layout.addWidget(result_card.add(self.detect_result_text, stretch=1), stretch=1)
        self._status_key = ""
        self._task = TabTask(self)
        self._task.result.connect(self._on_task_result)
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
            region = open_region_selector(self)     # the operator drags here, on the GUI thread
        except (AutoControlException, OSError, ValueError, RuntimeError) as error:
            QMessageBox.warning(self, "Error", str(error))
            return
        # The screen grab and the PNG write run off the GUI thread; the path is set once it is written.
        if region is not None and self._task.start(partial(_save_template, save_path, region), tag=save_path):
            self._status_key = "task_running"
            self.detect_result_text.setText(_t(self._status_key))

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

    def _on_task_result(self, result: str) -> None:
        if self._task.tag:                  # a crop: its tag is the template it wrote
            self.img_path_input.setText(self._task.tag)
        self._on_result(result)

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
