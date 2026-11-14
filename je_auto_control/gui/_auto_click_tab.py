"""Independent auto-click controls with owned timer and cancellable background input."""
from dataclasses import dataclass
from functools import partial
from typing import Callable, Optional

from PySide6.QtCore import QTimer

from PySide6.QtWidgets import (
    QWidget, QLineEdit, QComboBox, QVBoxLayout, QLabel, QFormLayout,
    QHBoxLayout, QRadioButton, QButtonGroup, QMessageBox,
    QGroupBox,
)

from je_auto_control.gui._i18n_helpers import TranslatableMixin
from je_auto_control.gui.adaptive.flow_layout import field_pair, flow_of
from je_auto_control.gui.adaptive.responsive import ResponsiveBox
from je_auto_control.gui.adaptive.surfaces import Card, set_role
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


def _form_panel(rows) -> QWidget:
    """A frameless panel holding ``(label, field)`` form rows; a ``None`` label spans the row."""
    panel = QWidget()
    panel.setProperty("role", "bare")
    form = QFormLayout(panel)
    form.setContentsMargins(0, 0, 0, 0)
    for label, field in rows:
        if label is None:
            form.addRow(field)
        else:
            form.addRow(label, field)
    return panel


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
        outer.setSpacing(12)
        outer.addWidget(self._build_click_card())
        # Start/stop, position probe, hotkey, write, and scroll commands all
        # run from the Actions menu; the tab keeps only their inputs.
        outer.addWidget(ResponsiveBox(self._build_position_group(), self._build_scroll_group()))
        outer.addWidget(ResponsiveBox(self._build_hotkey_group(), self._build_write_group()))
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        set_role(self.status_label, "hint")
        outer.addWidget(self.status_label)
        self._refresh_status()
        outer.addStretch()

        self.mouse_radio.toggled.connect(self._update_click_mode)
        self._update_click_mode()

    def _build_click_card(self) -> Card:
        """The click settings: how and how often on the left, what and where on the right."""
        self.mouse_radio = self._tr(QRadioButton(), "mouse_radio")
        self.keyboard_radio = self._tr(QRadioButton(), "keyboard_radio")
        self.mouse_radio.setChecked(True)
        self._input_group = QButtonGroup(self)
        self._input_group.addButton(self.mouse_radio)
        self._input_group.addButton(self.keyboard_radio)
        self.interval_input = QLineEdit("1000")
        self.interval_input.setValidator(int_validator(1, 999999999))
        self.click_type_combo = QComboBox()
        self._click_type_keys = ["single_click", "double_click"]
        self.click_type_combo.addItems(
            [self._translate(key) for key in self._click_type_keys]
        )
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
        how = _form_panel((
            (self._tr(QLabel(), "input_method"), flow_of(self.mouse_radio, self.keyboard_radio)),
            (self._tr(QLabel(), "interval_time"), self.interval_input),
            (self._tr(QLabel(), "click_type"), self.click_type_combo),
            (None, flow_of(self.repeat_until_stopped,
                           field_pair(self.repeat_count_times, self.repeat_count_input))),
        ))
        return Card().add(ResponsiveBox(how, self._build_target_panel()))

    def _build_target_panel(self) -> QWidget:
        """Cursor position and the mouse or keyboard button to press."""
        self.cursor_x_input = QLineEdit()
        self.cursor_x_input.setValidator(int_validator())
        self.cursor_y_input = QLineEdit()
        self.cursor_y_input.setValidator(int_validator())
        self.mouse_button_combo = QComboBox()
        self.mouse_button_combo.addItems(
            list(mouse_keys_table.keys()) if isinstance(mouse_keys_table, dict) else list(mouse_keys_table)
        )
        self.keyboard_button_combo = QComboBox()
        self.keyboard_button_combo.addItems(list(get_keyboard_keys_table().keys()))
        return _form_panel((
            (self._tr(QLabel(), "cursor_x"), self.cursor_x_input),
            (self._tr(QLabel(), "cursor_y"), self.cursor_y_input),
            (self._tr(QLabel(), "mouse_button"), self.mouse_button_combo),
            (self._tr(QLabel(), "keyboard_button"), self.keyboard_button_combo),
        ))

    def _build_position_group(self) -> QGroupBox:
        pos_group = self._tr(QGroupBox(), "get_position")
        pos_layout = QHBoxLayout(pos_group)
        self.pos_label = QLabel()
        self._pos_label_suffix = " --"
        self.pos_label.setText(
            self._translate("current_position") + self._pos_label_suffix,
        )
        pos_layout.addWidget(self.pos_label)
        return pos_group

    def _build_hotkey_group(self) -> QGroupBox:
        hotkey_group = self._tr(QGroupBox(), "hotkey_label")
        self.hotkey_input = QLineEdit()
        self.hotkey_input.setPlaceholderText("ctrl,a")
        QHBoxLayout(hotkey_group).addWidget(self.hotkey_input)
        return hotkey_group

    def _build_write_group(self) -> QGroupBox:
        write_group = self._tr(QGroupBox(), "write_label")
        self.write_input = QLineEdit()
        QHBoxLayout(write_group).addWidget(self.write_input)
        return write_group

    def _build_scroll_group(self) -> QGroupBox:
        scroll_group = self._tr(QGroupBox(), "mouse_scroll_label")
        self.scroll_value_input = QLineEdit("3")
        self.scroll_value_input.setValidator(int_validator())
        row = [field_pair(self._tr(QLabel(), "mouse_scroll_label"), self.scroll_value_input)]
        if special_mouse_keys_table:
            self.scroll_dir_combo: Optional[QComboBox] = QComboBox()
            self.scroll_dir_combo.addItems(list(special_mouse_keys_table.keys()))
            row.append(self.scroll_dir_combo)
        else:
            self.scroll_dir_combo = None
        QVBoxLayout(scroll_group).addLayout(flow_of(*row))
        return scroll_group

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
