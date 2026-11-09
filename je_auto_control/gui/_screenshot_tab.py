"""Screenshot and pixel-probe panel with independently owned controls."""
from functools import partial
from typing import Callable, Literal, Optional

from PySide6.QtWidgets import (
    QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QTextEdit, QVBoxLayout, QWidget,
)

from je_auto_control.gui._validators import int_validator
from je_auto_control.gui._i18n_helpers import TranslatableMixin
from je_auto_control.gui._tab_task import TabTask
from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper
from je_auto_control.gui.selector import open_region_selector
from je_auto_control.wrapper.auto_control_screen import screen_size, screenshot, get_pixel


def _t(key: str) -> str:
    """language_wrapper shorthand"""
    return language_wrapper.translate(key, key)


class ScreenshotTab(TranslatableMixin, QWidget):
    """Own screenshot inputs and pixel-result state independently of the workspace."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tr_init()
        layout = QVBoxLayout(self)

        # Screen size (read via Actions menu -> Get Screen Size)
        size_group = self._tr(QGroupBox(), "screen_size_label")
        sg = QHBoxLayout()
        self.screen_size_label = QLabel("--")
        sg.addWidget(self.screen_size_label)
        size_group.setLayout(sg)
        layout.addWidget(size_group)

        # Screenshot inputs; capture runs from the Actions menu.
        ss_group = self._tr(QGroupBox(), "take_screenshot")
        ss_grid = QGridLayout()
        ss_grid.addWidget(self._tr(QLabel(), "file_path_label"), 0, 0)
        self.ss_path_input = QLineEdit()
        ss_grid.addWidget(self.ss_path_input, 0, 1)

        ss_grid.addWidget(self._tr(QLabel(), "region_label"), 1, 0)
        self.ss_region_input = QLineEdit()
        self.ss_region_input.setPlaceholderText("0, 0, 800, 600")
        ss_grid.addWidget(self.ss_region_input, 1, 1)
        ss_group.setLayout(ss_grid)
        layout.addWidget(ss_group)

        # Pixel probe inputs; lookup runs from the Actions menu.
        px_group = self._tr(QGroupBox(), "get_pixel_label")
        px_grid = QGridLayout()
        px_grid.addWidget(self._tr(QLabel(), "pixel_x"), 0, 0)
        self.pixel_x_input = QLineEdit("0")
        self.pixel_x_input.setValidator(int_validator())
        px_grid.addWidget(self.pixel_x_input, 0, 1)
        px_grid.addWidget(self._tr(QLabel(), "pixel_y"), 0, 2)
        self.pixel_y_input = QLineEdit("0")
        self.pixel_y_input.setValidator(int_validator())
        px_grid.addWidget(self.pixel_y_input, 0, 3)
        self.pixel_result_label = QLabel()
        self._pixel_result: tuple[Literal["value", "error", "running"], str] = ("value", "--")
        self._render_pixel_result()
        px_grid.addWidget(self.pixel_result_label, 1, 0, 1, 4)
        px_group.setLayout(px_grid)
        layout.addWidget(px_group)

        self.ss_result_text = QTextEdit()
        self.ss_result_text.setReadOnly(True)
        self.ss_result_text.setMaximumHeight(100)
        layout.addWidget(self.ss_result_text)
        layout.addStretch()
        self._task = TabTask(self)
        self._task.result.connect(self._on_result)
        self._task.error.connect(self._on_error)

    def menu_actions(self) -> list[tuple[str, Callable[[], object]]]:
        return [
            ("take_screenshot", self._take_screenshot),
            ("browse", self._browse_ss_path),
            ("pick_region", self._pick_ss_region),
            ("get_screen_size", self._get_screen_size),
            ("get_pixel_label", self._get_pixel_color),
        ]

    def _get_screen_size(self) -> None:
        if self._task.start(_read_screen_size, tag="size"):
            self.screen_size_label.setText(_t("task_running"))

    def _browse_ss_path(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, _t("save_screenshot"), "", "PNG (*.png);;All (*)")
        if path:
            self.ss_path_input.setText(path)

    def _pick_ss_region(self) -> None:
        region = open_region_selector(self)
        if region is None:
            return
        x, y, w, h = region
        self.ss_region_input.setText(f"{x}, {y}, {x + w}, {y + h}")

    def _take_screenshot(self) -> None:
        if self._task.running:
            return
        try:
            path = self.ss_path_input.text() or None
            region_text = self.ss_region_input.text().strip()
            region = tuple(int(x.strip()) for x in region_text.split(",")) if region_text else None
        except (ValueError, TypeError) as error:
            self.ss_result_text.setText(f"Error: {error}")
            return
        if self._task.start(partial(_capture, path, region), tag="screenshot"):
            self.ss_result_text.setText(_t("task_running"))

    def _get_pixel_color(self) -> None:
        if self._task.running:
            return
        try:
            x = int(self.pixel_x_input.text())
            y = int(self.pixel_y_input.text())
        except (ValueError, TypeError) as error:
            self._pixel_result = ("error", str(error))
            self._render_pixel_result()
            return
        if self._task.start(partial(_read_pixel, x, y), tag="pixel"):
            self._pixel_result = ("running", "")
            self._render_pixel_result()

    def _on_result(self, result: str) -> None:
        if self._task.tag == "size":
            self.screen_size_label.setText(result)
        elif self._task.tag == "pixel":
            self._pixel_result = ("value", result)
            self._render_pixel_result()
        else:
            self.ss_result_text.setText(result)

    def _on_error(self, error: object) -> None:
        if self._task.tag == "size":
            self.screen_size_label.setText(f"Error: {error}")
        elif self._task.tag == "pixel":
            self._pixel_result = ("error", str(error))
            self._render_pixel_result()
        else:
            self.ss_result_text.setText(f"Error: {error}")

    def _render_pixel_result(self) -> None:
        kind, text = self._pixel_result
        if kind == "running":
            self.pixel_result_label.setText(_t("task_running"))
        elif kind == "error":
            self.pixel_result_label.setText(f"Error: {text}")
        else:
            self.pixel_result_label.setText(f"{_t('pixel_result')} {text}")

    def retranslate(self) -> None:
        super().retranslate()
        self._render_pixel_result()

    def dispose(self) -> None:
        """Discard late results; an already-entered native operation may still finish."""
        self._task.stop()


def _read_screen_size() -> str:
    width, height = screen_size()
    return f"{width} x {height}"


def _capture(path: Optional[str], region: Optional[tuple[int, ...]]) -> str:
    screenshot(file_path=path, screen_region=list(region) if region is not None else None)
    return f"Screenshot saved: {path or '(not saved)'}"


def _read_pixel(x: int, y: int) -> str:
    return str(get_pixel(x, y))
