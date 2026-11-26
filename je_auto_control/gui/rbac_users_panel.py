"""RBAC users group of the REST API tab: list, add, re-role, rotate, remove.

A thin Qt surface over :mod:`je_auto_control.utils.rbac.admin` -- the same
functions ``AC_user_*`` and ``je_auto_control users`` call. Each operation
first asks RBAC for the ``AC_user_*`` command it stands for, as the executor
would, and shows a refusal on the panel instead of raising it; outside an
RBAC scope (the desktop default) nothing is refused.

A token is shown once, in the "new token" field, right after ``add`` or
``rotate``; the next operation clears it. It is never written to a log. The
field is masked until Show is pressed; Actions > Copy token copies it masked.

Every operation reads and rewrites the user file, so each runs as a tab task,
one at a time, and the table is refilled from what the worker read after it.
"""
import functools
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QGroupBox, QLabel,
    QLineEdit, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from je_auto_control.gui._authorize import RefusalLabel, refusal
from je_auto_control.gui._dispose import release_resources
from je_auto_control.gui._i18n_helpers import KeyedText, TranslatableMixin
from je_auto_control.gui._secret_field import SecretField
from je_auto_control.gui._tab_task import TabTask
from je_auto_control.gui._qt_typed import filled_item
from je_auto_control.gui.adaptive.flow_layout import field_pair, flow_of
from je_auto_control.gui.adaptive.surfaces import set_role
from je_auto_control.gui.language_wrapper.multi_language_wrapper import (
    language_wrapper,
)
from je_auto_control.utils.rbac import admin
from je_auto_control.utils.rbac.authorization import USERS_ENV
from je_auto_control.utils.rbac.users import Role, UserStore

_COLUMNS = ("rest_users_col_id", "rest_users_col_name", "rest_users_col_role")


def _t(key: str) -> str:
    return language_wrapper.translate(key, key)


class RbacUsersPanel(TranslatableMixin, QGroupBox):
    """The user store behind the REST API: its path, its users, one-time tokens."""

    #: Checked against the active RBAC role when the page is shown.
    REQUIRED_COMMANDS = ("AC_user_list", "AC_user_add", "AC_user_set_role", "AC_user_rotate_token",
                         "AC_user_remove")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tr_init()
        self._tr(self, "rest_users_group", "setTitle")
        self._path_input = QLineEdit(os.environ.get(USERS_ENV, "").strip())
        self._tr(self._path_input, "rest_users_path_ph")
        self._enable_check = QCheckBox()
        self._enable_check.setChecked(bool(self._path_input.text()))
        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.itemSelectionChanged.connect(self._on_row_selected)
        self._id_input = QLineEdit()
        self._name_input = QLineEdit()
        self._role_input = QComboBox()
        self._role_input.addItems(Role.all())
        self._token_value = QLineEdit()
        self._token_value.setReadOnly(True)
        self._status_label = QLabel()
        self._status = KeyedText(self._status_label)     # a language switch re-reads what it says
        self._status_label.setWordWrap(True)
        self._status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._refusal = RefusalLabel()
        self._ops = TabTask(self)           # every operation reads and rewrites the user file
        self._ops.result.connect(self._on_ops_done)
        self._ops.error.connect(self._on_ops_failed)
        self._build_layout()
        self._retitle_columns()

    def _build_layout(self) -> None:
        root = QVBoxLayout(self)
        path_form = QFormLayout()
        path_form.addRow(self._tr(QLabel(), "rest_users_path"), self._path_input)
        root.addLayout(path_form)
        self._tr(self._enable_check, "rest_users_enable")
        root.addWidget(self._enable_check)
        root.addWidget(self._table, stretch=1)
        root.addLayout(flow_of(*(field_pair(self._tr(QLabel(), key), field) for key, field in (
            ("rest_users_id", self._id_input), ("rest_users_name", self._name_input),
            ("rest_users_role", self._role_input)))))
        token_form = QFormLayout()
        # Copying stays in the Actions menu (rest_users_copy_token), so the field adds only Show.
        token_form.addRow(self._tr(QLabel(), "rest_users_new_token"),
                          SecretField(self._token_value, self._tr, copyable=False))
        root.addLayout(token_form)
        set_role(self._status_label, "hint")
        root.addWidget(self._status_label)
        root.addWidget(self._refusal)

    def retranslate(self) -> None:
        """Re-apply the registered keys and the table's column titles."""
        super().retranslate()
        self._status.retranslate()
        self._retitle_columns()

    def _retitle_columns(self) -> None:
        self._table.setHorizontalHeaderLabels([_t(key) for key in _COLUMNS])

    def menu_actions(self) -> List[Tuple[str, object]]:
        """The panel's commands, for the tab's Actions menu."""
        return [
            ("rest_users_refresh", self.refresh),
            ("rest_users_add", self._on_add),
            ("rest_users_set_role", self._on_set_role),
            ("rest_users_rotate", self._on_rotate),
            ("rest_users_remove", self._on_remove),
            ("rest_users_copy_token", self._on_copy_token),
        ]

    def users_path(self) -> Optional[str]:
        """The store path typed into the panel, or ``None`` when it is empty."""
        return self._path_input.text().strip() or None

    def enabled_users_path(self) -> Optional[str]:
        """The store path the REST server should authenticate against, when ticked; no file is read."""
        path = self.users_path()
        return path if path is not None and self._enable_check.isChecked() else None

    def user_store(self) -> Optional[UserStore]:
        """The store the REST server should authenticate against, when ticked (it reads the file)."""
        path = self.enabled_users_path()
        return None if path is None else admin.management_store(path)

    def dispose(self) -> None:
        """Drop an operation still out (a write runs to its end, its answer and token are not shown)."""
        release_resources(self)

    def refresh(self) -> None:
        """Re-read the store and show its users; forgets a token still on show."""
        self._token_value.clear()
        self._reload()

    def _reload(self) -> None:
        path = self.users_path()
        if path is None:
            self._table.setRowCount(0)
            self._status.show("rest_users_no_store")
            return
        refused = refusal("AC_user_list")
        if refused is not None:
            self._table.setRowCount(0)
            self._status.show_plain(refused)
            return
        self._run(path, None)

    def _run(self, path: str, change: Optional[Callable[[], Any]]) -> None:
        """Make ``change`` (when given) and list the users again, off the GUI thread."""
        if not self._ops.start(functools.partial(_change_then_list, path, change)):
            self._status.show("task_busy")
            return
        self._status.show("task_running")

    def _on_ops_done(self, outcome: Dict[str, Any]) -> None:
        users, refused = outcome["users"], outcome["refused"]
        self._table.setRowCount(len(users))
        for row, user in enumerate(users):
            for column, key in enumerate(("user_id", "display_name", "role")):
                self._table.setItem(row, column, QTableWidgetItem(str(user[key])))
        if refused:
            self._status.show_plain(refused)
        else:
            self._status.show("rest_users_count", count=len(users), path=outcome["path"])
        issued = outcome["issued"]
        if isinstance(issued, dict) and "token" in issued:
            self._token_value.setText(str(issued["token"]))
            self._status.show("rest_users_token_issued", user=issued["user_id"])

    def _on_ops_failed(self, error: object) -> None:
        self._status.show_plain(str(error))

    def _on_row_selected(self) -> None:
        row = self._table.currentRow()
        if row < 0 or self._table.item(row, 0) is None:
            return
        self._id_input.setText(filled_item(self._table, row, 0).text())
        self._name_input.setText(filled_item(self._table, row, 1).text())
        self._role_input.setCurrentText(filled_item(self._table, row, 2).text())

    def _target(self, command: str) -> Optional[Tuple[str, str]]:
        """``(store path, user id)`` of ``command``, or ``None`` with the reason (or the refusal) shown."""
        self._token_value.clear()
        if not self._refusal.allows(command):
            return None
        path = self.users_path()
        if path is None:
            self._status.show("rest_users_no_store")
            return None
        user_id = self._id_input.text().strip()
        if not user_id:
            self._status.show("rest_users_no_user")
            return None
        return path, user_id

    def _on_add(self) -> None:
        target = self._target("AC_user_add")
        if target is not None:
            self._run(target[0], functools.partial(
                admin.add_user, target[1], role=self._role_input.currentText(),
                display_name=self._name_input.text().strip(), users_path=target[0]))

    def _on_rotate(self) -> None:
        target = self._target("AC_user_rotate_token")
        if target is not None:
            self._run(target[0], functools.partial(admin.rotate_user_token, target[1], users_path=target[0]))

    def _on_set_role(self) -> None:
        target = self._target("AC_user_set_role")
        if target is not None:
            self._run(target[0], functools.partial(admin.set_user_role, target[1], self._role_input.currentText(),
                                                   users_path=target[0]))

    def _on_remove(self) -> None:
        target = self._target("AC_user_remove")
        if target is None:
            return
        confirm = QMessageBox.question(
            self, _t("rest_users_remove"),
            _t("rest_users_remove_confirm").format(user=target[1]))
        if confirm == QMessageBox.StandardButton.Yes:
            self._run(target[0], functools.partial(admin.remove_user, target[1], users_path=target[0]))

    def _on_copy_token(self) -> None:
        text = self._token_value.text()
        if text:
            QGuiApplication.clipboard().setText(text)


def _change_then_list(path: str, change: Optional[Callable[[], Any]]) -> Dict[str, Any]:
    """Worker thread: make ``change``, then read the users back (unless listing them is refused).

    Each ``admin`` call checks the caller's authority itself, as ``AC_user_*`` does.
    """
    issued = change() if change is not None else None
    refused = refusal("AC_user_list")
    users = [] if refused is not None else admin.list_users(users_path=path)
    return {"issued": issued, "users": users, "refused": refused, "path": path}


__all__ = ["RbacUsersPanel"]
