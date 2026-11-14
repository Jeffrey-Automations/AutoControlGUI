"""Recording Editor tab: trim, filter and rescale recorded action lists."""
import json
from typing import Optional

from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog, QFormLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QMessageBox, QTextEdit, QVBoxLayout, QWidget,
)

from je_auto_control.gui._i18n_helpers import TranslatableMixin
from je_auto_control.gui.adaptive.flow_layout import field_pair, flow_of
from je_auto_control.gui.adaptive.responsive import ResponsiveBox
from je_auto_control.gui.adaptive.surfaces import Card, set_role
from je_auto_control.gui.language_wrapper.multi_language_wrapper import (
    language_wrapper,
)
from je_auto_control.utils.codegen.codegen import generate_code_file
from je_auto_control.utils.exception.exceptions import AutoControlException
from je_auto_control.utils.json.json_file import read_action_json, write_action_json
from je_auto_control.utils.recording_edit.editor import (
    adjust_delays, filter_actions, remove_action, scale_coordinates, trim_actions,
)


def _t(key: str) -> str:
    return language_wrapper.translate(key, key)


class RecordingEditorTab(TranslatableMixin, QWidget):
    """Load a recording JSON and apply non-destructive edits."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tr_init()
        self._actions: list = []
        self._undo_stack: list = []
        self._path_input = QLineEdit()
        self._list = QListWidget()
        self._preview = QTextEdit()
        self._preview.setReadOnly(True)
        self._status = QLabel("")
        self._trim_start = QLineEdit("0")
        self._trim_end = QLineEdit("")
        self._delay_factor = QLineEdit("1.0")
        self._delay_clamp = QLineEdit("0")
        self._scale_x = QLineEdit("1.0")
        self._scale_y = QLineEdit("1.0")
        self._build_layout()
        # Ctrl+Z restores the action list to before the last edit.
        self._undo_shortcut = QShortcut(
            QKeySequence.StandardKey.Undo, self, self._undo,
        )

    def retranslate(self) -> None:
        TranslatableMixin.retranslate(self)

    def _mutate(self, new_actions: list) -> None:
        """Apply an edit, snapshotting the prior state for undo (Ctrl+Z)."""
        self._undo_stack.append(list(self._actions))
        self._actions = new_actions
        self._refresh()

    def _undo(self) -> None:
        """Restore the action list to before the last edit."""
        if not self._undo_stack:
            return
        self._actions = self._undo_stack.pop()
        self._refresh()

    def _build_layout(self) -> None:
        # Load/save/export and every edit command run from the Actions
        # menu; the tab keeps only inputs, the list, preview, and status.
        root = QVBoxLayout(self)
        root.setSpacing(12)
        file_row = QFormLayout()
        file_row.addRow(self._tr(QLabel(), "re_file_label"), self._path_input)
        root.addWidget(Card().add(file_row))

        def pair(key: str, field: QWidget) -> QWidget:
            return field_pair(self._tr(QLabel(), key), field)

        edits = Card()
        edits.add(flow_of(pair("re_trim_start", self._trim_start), pair("re_trim_end", self._trim_end)))
        edits.add(flow_of(pair("re_delay_x", self._delay_factor), pair("re_floor_ms", self._delay_clamp),
                          pair("re_scale_x", self._scale_x), pair("re_scale_y", self._scale_y)))
        root.addWidget(edits)

        preview = Card().add(set_role(self._tr(QLabel(), "re_preview"), "sectionTitle"))
        preview.add(self._preview, stretch=1)
        root.addWidget(ResponsiveBox(Card().add(self._list, stretch=1), preview, stretches=(2, 3)), stretch=1)
        self._status.setWordWrap(True)
        set_role(self._status, "hint")
        root.addWidget(self._status)

    def menu_actions(self) -> list:
        """Expose tab commands to the window-level Actions menu."""
        return [
            ("re_browse", self._browse),
            ("re_load", self._load),
            ("re_save_as", self._save_as),
            ("re_export_code", self._export_code),
            ("journal_candidate_open", self._open_journal_candidate),
            ("re_apply_trim", self._apply_trim),
            ("re_remove_selected", self._remove_selected),
            ("re_undo", self._undo),
            ("re_apply_delays", self._apply_delays),
            ("re_apply_scale", self._apply_scale),
            ("re_keep_mouse", self._keep_mouse),
            ("re_keep_keyboard", self._keep_keyboard),
        ]

    def _keep_mouse(self) -> None:
        self._filter_prefix("AC_mouse")

    def _open_journal_candidate(self) -> None:
        """Preview source/diff/provenance without replacing this recording or replaying input."""
        # pylint: disable-next=import-outside-toplevel  # reason: load candidate UI only when its action is invoked
        from je_auto_control.gui.journal_candidate_dialog import show_journal_candidate
        try:
            show_journal_candidate(self, self._actions)
        except (AutoControlException, ValueError, TypeError) as error:
            QMessageBox.warning(self, "Error", str(error))

    # pylint: disable-next=invalid-name  # reason: Qt override
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802  # reason: Qt override
        """Cancel pending review tasks when the recording editor closes."""
        # pylint: disable-next=import-outside-toplevel  # reason: avoid loading review UI during tab registration
        from je_auto_control.gui.journal_candidate_dialog import close_candidate_dialogs
        close_candidate_dialogs(self)
        super().closeEvent(event)

    def _keep_keyboard(self) -> None:
        self._filter_prefix((
            "AC_type_keyboard", "AC_press_keyboard_key",
            "AC_release_keyboard_key", "AC_hotkey", "AC_write",
        ))

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, _t("re_dialog_open"), "", "JSON (*.json)",
        )
        if path:
            self._path_input.setText(path)

    def _load(self) -> None:
        path = self._path_input.text().strip()
        if not path:
            return
        try:
            self._actions = read_action_json(path)
        except (AutoControlException, OSError, ValueError) as error:
            QMessageBox.warning(self, "Error", str(error))
            return
        self._undo_stack.clear()  # a freshly loaded recording starts clean
        self._refresh()

    def _save_as(self) -> None:
        if not self._actions:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, _t("re_dialog_save"), "", "JSON (*.json)",
        )
        if not path:
            return
        try:
            write_action_json(path, self._actions)
        except (AutoControlException, OSError, ValueError) as error:
            QMessageBox.warning(self, "Error", str(error))
            return
        self._status.setText(f"Saved to {path}")

    _TARGET_FILTERS = {
        "pytest": "Python (*.py)",
        "python": "Python (*.py)",
        "robot": "Robot (*.robot)",
    }

    def _export_code(self) -> None:
        """Generate pytest/python/robot source from the loaded actions."""
        if not self._actions:
            return
        target, ok = QInputDialog.getItem(
            self, _t("re_export_target"), "target",
            list(self._TARGET_FILTERS), 0, False,
        )
        if not ok:
            return
        path, _filter = QFileDialog.getSaveFileName(
            self, _t("re_export_code"), "", self._TARGET_FILTERS[target],
        )
        if not path:
            return
        try:
            generate_code_file(self._actions, path, target=target)
        except (AutoControlException, OSError, ValueError) as error:
            QMessageBox.warning(self, "Error", str(error))
            return
        self._status.setText(f"Exported {target} code to {path}")

    def _refresh(self) -> None:
        self._list.clear()
        for idx, action in enumerate(self._actions):
            self._list.addItem(f"{idx}: {action[0]}")
        self._preview.setPlainText(json.dumps(self._actions, indent=2, ensure_ascii=False))
        self._status.setText(f"{len(self._actions)} actions")

    def _apply_trim(self) -> None:
        try:
            start = int(self._trim_start.text() or "0")
            end_text = self._trim_end.text().strip()
            end = int(end_text) if end_text else None
        except ValueError:
            QMessageBox.warning(self, "Error", "Trim indices must be integers")
            return
        self._mutate(trim_actions(self._actions, start, end))

    def _remove_selected(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        try:
            new_actions = remove_action(self._actions, row)
        except IndexError as error:
            QMessageBox.warning(self, "Error", str(error))
            return
        self._mutate(new_actions)

    def _apply_delays(self) -> None:
        try:
            factor = float(self._delay_factor.text() or "1.0")
            clamp = int(self._delay_clamp.text() or "0")
        except ValueError:
            QMessageBox.warning(self, "Error", "Factor/clamp must be numeric")
            return
        self._mutate(adjust_delays(self._actions, factor=factor, clamp_ms=clamp))

    def _apply_scale(self) -> None:
        try:
            fx = float(self._scale_x.text() or "1.0")
            fy = float(self._scale_y.text() or "1.0")
        except ValueError:
            QMessageBox.warning(self, "Error", "Scale factors must be numeric")
            return
        self._mutate(scale_coordinates(self._actions, fx, fy))

    def _filter_prefix(self, prefix) -> None:
        def keep(action: list) -> bool:
            if not (isinstance(action, list) and action):
                return False
            name = action[0]
            if isinstance(prefix, str):
                return name.startswith(prefix)
            return name in prefix
        self._mutate(filter_actions(self._actions, keep))
