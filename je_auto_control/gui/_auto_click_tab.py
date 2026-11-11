"""Independent auto-click controls with owned timer and cancellable background input."""
from dataclasses import dataclass
from functools import partial
from typing import Callable, Optional

from PySide6.QtCore import QTimer

from PySide6.QtWidgets import (
    QWidget, QLineEdit, QComboBox, QVBoxLayout, QLabel,
    QGridLayout, QHBoxLayout, QRadioButton, QButtonGroup, QMessageBox,
    QGroupBox,
)

from je_auto_control.gui._i18n_helpers import TranslatableMixin
from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper
from je_auto_control.gui._tab_task import TabTask, stop_all_script_runs
from je_auto_control.utils.exception.cancellation import cancellation_checkpoint
from je_auto_control.gui._validators import int_validator
from je_auto_control.utils.exception.exceptions import AutoControlException
from je_auto_control.wrapper.auto_control_keyboard import (
    type_keyboard, hotkey, write, get_keyboard_keys_table,
)
from je_auto_control.wrapper.auto_control_mouse import (
    click_mouse, get_mouse_position, mouse_scroll,
    mouse_keys_table, special_mouse_keys_table,
)


@dataclass(frozen=True)
class _Click:
    mouse: bool
    key: str
    x: int
    y: int
    count: int


def _click(request: _Click) -> None:
    for _ in range(request.count):
        cancellation_checkpoint()
        if request.mouse:
            click_mouse(request.key, request.x, request.y)
        else:
            type_keyboard(request.key)


class AutoClickTab(TranslatableMixin, QWidget):
    """Own the timer, input snapshots and worker for this auto-click page."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tr_init()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._timer_tick)
        self.repeat_count = 0
        self.repeat_max = 0
        self._task = TabTask(self)
        self._task.result.connect(self._on_result)
        self._task.error.connect(self._on_error)
        self._task.finished.connect(self._refresh_status)
        outer = QVBoxLayout(self)
        click_group = self._tr(QGroupBox(), "tab_auto_click")
        grid = QGridLayout()
        row = 0

        grid.addWidget(self._tr(QLabel(), "input_method"), row, 0)
        self.mouse_radio = self._tr(QRadioButton(), "mouse_radio")
        self.keyboard_radio = self._tr(QRadioButton(), "keyboard_radio")
        self.mouse_radio.setChecked(True)
        self._input_group = QButtonGroup(self)
        self._input_group.addButton(self.mouse_radio)
        self._input_group.addButton(self.keyboard_radio)
        h = QHBoxLayout()
        h.addWidget(self.mouse_radio)
        h.addWidget(self.keyboard_radio)
        grid.addLayout(h, row, 1)

        row += 1
        grid.addWidget(self._tr(QLabel(), "interval_time"), row, 0)
        self.interval_input = QLineEdit("1000")
        self.interval_input.setValidator(int_validator(1, 999999999))
        grid.addWidget(self.interval_input, row, 1)

        row += 1
        grid.addWidget(self._tr(QLabel(), "cursor_x"), row, 0)
        self.cursor_x_input = QLineEdit()
        self.cursor_x_input.setValidator(int_validator())
        grid.addWidget(self.cursor_x_input, row, 1)

        row += 1
        grid.addWidget(self._tr(QLabel(), "cursor_y"), row, 0)
        self.cursor_y_input = QLineEdit()
        self.cursor_y_input.setValidator(int_validator())
        grid.addWidget(self.cursor_y_input, row, 1)

        row += 1
        grid.addWidget(self._tr(QLabel(), "mouse_button"), row, 0)
        self.mouse_button_combo = QComboBox()
        self.mouse_button_combo.addItems(
            list(mouse_keys_table.keys()) if isinstance(mouse_keys_table, dict) else list(mouse_keys_table)
        )
        grid.addWidget(self.mouse_button_combo, row, 1)

        row += 1
        grid.addWidget(self._tr(QLabel(), "keyboard_button"), row, 0)
        self.keyboard_button_combo = QComboBox()
        self.keyboard_button_combo.addItems(list(get_keyboard_keys_table().keys()))
        grid.addWidget(self.keyboard_button_combo, row, 1)

        row += 1
        grid.addWidget(self._tr(QLabel(), "click_type"), row, 0)
        self.click_type_combo = QComboBox()
        self._click_type_keys = ["single_click", "double_click"]
        self.click_type_combo.addItems(
            [self._translate(key) for key in self._click_type_keys]
        )
        grid.addWidget(self.click_type_combo, row, 1)

        row += 1
        self.repeat_until_stopped = self._tr(
            QRadioButton(), "repeat_until_stopped_radio",
        )
        self.repeat_count_times = self._tr(QRadioButton(), "repeat_radio")
        self.repeat_count_input = self._tr(QLineEdit(), "times")
        self.repeat_count_input.setValidator(int_validator(1, 999999999))
        rg = QButtonGroup(self)
        rg.addButton(self.repeat_until_stopped)
        rg.addButton(self.repeat_count_times)
        self.repeat_until_stopped.setChecked(True)
        rh = QHBoxLayout()
        rh.addWidget(self.repeat_until_stopped)
        rh.addWidget(self.repeat_count_times)
        rh.addWidget(self.repeat_count_input)
        grid.addLayout(rh, row, 0, 1, 2)

        click_group.setLayout(grid)
        outer.addWidget(click_group)

        # Start/stop, position probe, hotkey, write, and scroll commands all
        # run from the Actions menu; the tab keeps only their inputs.
        pos_group = self._tr(QGroupBox(), "get_position")
        pos_layout = QHBoxLayout()
        self.pos_label = QLabel()
        self._pos_label_suffix = " --"
        self.pos_label.setText(
            self._translate("current_position") + self._pos_label_suffix,
        )
        pos_layout.addWidget(self.pos_label)
        pos_group.setLayout(pos_layout)
        outer.addWidget(pos_group)

        hotkey_group = self._tr(QGroupBox(), "hotkey_label")
        hk_layout = QHBoxLayout()
        self.hotkey_input = QLineEdit()
        self.hotkey_input.setPlaceholderText("ctrl,a")
        hk_layout.addWidget(self.hotkey_input)
        hotkey_group.setLayout(hk_layout)
        outer.addWidget(hotkey_group)

        write_group = self._tr(QGroupBox(), "write_label")
        wr_layout = QHBoxLayout()
        self.write_input = QLineEdit()
        wr_layout.addWidget(self.write_input)
        write_group.setLayout(wr_layout)
        outer.addWidget(write_group)

        scroll_group = self._tr(QGroupBox(), "mouse_scroll_label")
        sc_layout = QHBoxLayout()
        self.scroll_value_input = QLineEdit("3")
        self.scroll_value_input.setValidator(int_validator())
        sc_layout.addWidget(self._tr(QLabel(), "mouse_scroll_label"))
        sc_layout.addWidget(self.scroll_value_input)
        if special_mouse_keys_table:
            self.scroll_dir_combo: Optional[QComboBox] = QComboBox()
            self.scroll_dir_combo.addItems(list(special_mouse_keys_table.keys()))
            sc_layout.addWidget(self.scroll_dir_combo)
        else:
            self.scroll_dir_combo = None
        scroll_group.setLayout(sc_layout)
        outer.addWidget(scroll_group)

        self.status_label = QLabel()
        outer.addWidget(self.status_label)
        self._refresh_status()
        outer.addStretch()

        self.mouse_radio.toggled.connect(self._update_click_mode)
        self._update_click_mode()


    def retranslate(self) -> None:
        """Re-translate composite labels and combo items that ``_tr`` can't own."""
        super().retranslate()
        self._refresh_status()
        if hasattr(self, "click_type_combo") and hasattr(self, "_click_type_keys"):
            current_index = self.click_type_combo.currentIndex()
            self.click_type_combo.clear()
            self.click_type_combo.addItems(
                [self._translate(key) for key in self._click_type_keys]
            )
            if 0 <= current_index < self.click_type_combo.count():
                self.click_type_combo.setCurrentIndex(current_index)
        if hasattr(self, "pos_label"):
            self.pos_label.setText(
                self._translate("current_position") + self._pos_label_suffix,
            )

    def _update_click_mode(self):
        use_mouse = self.mouse_radio.isChecked()
        self.cursor_x_input.setEnabled(use_mouse)
        self.cursor_y_input.setEnabled(use_mouse)
        self.mouse_button_combo.setEnabled(use_mouse)
        self.keyboard_button_combo.setEnabled(not use_mouse)

    def _start_auto_click(self):
        try:
            interval = int(self.interval_input.text())
        except ValueError:
            QMessageBox.warning(self, "Warning", "Interval must be a number")
            return
        # The validator's bottom of 1 is a hint only: "0" set a 0 ms timer,
        # which clicked on every event-loop pass (18,579 clicks in 0.5 s).
        if interval < 1:
            QMessageBox.warning(self, "Warning", "Interval must be at least 1 ms")
            return
        self.repeat_count = 0
        try:
            self.repeat_max = int(self.repeat_count_input.text())
        except ValueError:
            self.repeat_max = 0
        self.timer.setInterval(interval)
        self.timer.start()
        self._refresh_status()

    def _stop_auto_click(self):
        """Stop the auto-clicker and ask every running script to stop (Ctrl+4)."""
        self.dispose()
        stop_all_script_runs()

    def _timer_tick(self) -> None:
        if self._task.running:
            return
        if self.repeat_until_stopped.isChecked():
            self._do_click()
        elif self.repeat_count_times.isChecked():
            self.repeat_count += 1
            if self.repeat_count <= self.repeat_max:
                self._do_click()
            else:
                self.repeat_count = 0
                self.timer.stop()
                self._refresh_status()

    def _do_click(self) -> None:
        if self._task.running:
            return
        try:
            mouse = self.mouse_radio.isChecked()
            key = self.mouse_button_combo.currentText() if mouse else self.keyboard_button_combo.currentText()
            request = _Click(mouse, key, int(self.cursor_x_input.text() or "0"),
                             int(self.cursor_y_input.text() or "0"),
                             2 if self.click_type_combo.currentIndex() == 1 else 1)
            self._start_work(partial(_click, request))
        except (AutoControlException, OSError, ValueError, TypeError, RuntimeError) as error:
            self._on_error(error)

    def _on_error(self, error: object) -> None:
        self.timer.stop()
        self._refresh_status()
        QMessageBox.warning(self, "Error", str(error))

    def _get_mouse_pos(self) -> None:
        self._start_work(get_mouse_position, tag="position")

    def _on_result(self, result: object) -> None:
        if self._task.tag != "position":
            return
        if not isinstance(result, tuple) or len(result) != 2:
            self._on_error(AutoControlException("the OS did not report a cursor position"))
            return
        x, y = result
        self._pos_label_suffix = f" ({x}, {y})"
        self.pos_label.setText(self._translate("current_position") + self._pos_label_suffix)
        self.cursor_x_input.setText(str(x))
        self.cursor_y_input.setText(str(y))

    def _send_hotkey(self) -> None:
        keys = [key.strip() for key in self.hotkey_input.text().split(",") if key.strip()]
        if keys:
            self._start_work(partial(hotkey, keys))

    def _send_write(self) -> None:
        text = self.write_input.text()
        if text:
            self._start_work(partial(write, text))

    def _send_scroll(self) -> None:
        try:
            value = int(self.scroll_value_input.text() or "3")
            direction = self.scroll_dir_combo.currentText() if self.scroll_dir_combo else "scroll_up"
            self._start_work(partial(mouse_scroll, value, scroll_direction=direction))
        except (ValueError, TypeError) as error:
            self._on_error(error)

    def _start_work(self, work: Callable[[], object], *, tag: str = "") -> None:
        self._task.start(work, tag=tag)
        self._refresh_status()

    def _refresh_status(self) -> None:
        key = "task_running" if self.timer.isActive() or self._task.running else "task_stopped"
        self.status_label.setText(self._translate(key))

    def _translate(self, key: str) -> str:
        return language_wrapper.translate(key, key)

    def menu_actions(self) -> list[tuple[str, Callable[[], object]]]:
        """Expose owned input controls through the workspace Actions menu."""
        return [("start", self._start_auto_click), ("stop", self._stop_auto_click),
                ("get_position", self._get_mouse_pos), ("hotkey_send", self._send_hotkey),
                ("write_send", self._send_write), ("scroll_send", self._send_scroll)]

    def dispose(self) -> None:
        """Stop this page's timer and pending work without stopping other pages."""
        self.timer.stop()
        self._task.stop()
        self._refresh_status()
