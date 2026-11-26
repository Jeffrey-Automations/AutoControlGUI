"""Secrets tab: unlock the vault and manage ${secrets.NAME} entries.

Creating, unlocking and re-keying the vault derive its key with 600,000
PBKDF2 iterations, and every change rewrites the vault file, so each command
runs as a :class:`~je_auto_control.gui._tab_task.TabTask`, one at a time; the
dialogs that ask for names and passphrases stay on the GUI thread. The worker
also reads the entry names back, so the GUI thread never waits on the vault's
lock while a command holds it. Each command is checked against the
``AC_secret_*`` command it stands for, in the slot (the refusal is shown in
the tab) and again on the worker, as whoever started it.
"""
import functools
from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple

from PySide6.QtWidgets import (
    QAbstractItemView, QFormLayout, QGroupBox, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QVBoxLayout, QWidget,
)

from je_auto_control.gui._authorize import RefusalLabel
from je_auto_control.gui._dispose import release_resources
from je_auto_control.gui._i18n_helpers import TranslatableMixin
from je_auto_control.gui._tab_task import TabTask
from je_auto_control.gui.adaptive.surfaces import set_role
from je_auto_control.gui.language_wrapper.multi_language_wrapper import (
    language_wrapper,
)
from je_auto_control.utils.rbac.policy import authorize_command
from je_auto_control.utils.secrets import SecretStoreError, default_secret_manager

#: What a finished command says, keyed by its label key; unlock says only when the passphrase was wrong.
_DONE_MESSAGES = {"secret_init": "secret_init_done", "secret_change_passphrase": "secret_change_done"}


def _t(key: str) -> str:
    return language_wrapper.translate(key, key)


@dataclass(frozen=True)
class _VaultView:
    """What the tab shows of the vault: read on the worker, after the command."""

    initialized: bool
    unlocked: bool
    names: Tuple[str, ...] = ()


def _read_view(manager: Any) -> _VaultView:
    """The vault's state and, while it is unlocked, its entry names (never their values)."""
    names: Tuple[str, ...] = ()
    if manager.is_unlocked:
        try:
            names = tuple(manager.list_names())
        except SecretStoreError:    # reason: locked or re-keyed meanwhile; there is nothing to list
            names = ()
    return _VaultView(bool(manager.is_initialized), bool(manager.is_unlocked), names)


def _vault_work(command: str, manager: Any, call: Optional[Callable[[], Any]]) -> Tuple[Any, _VaultView]:
    """Worker thread: run ``call`` as ``command`` for whoever started it, then read the vault back."""
    authorize_command(command)
    outcome = call() if call is not None else None
    return outcome, _read_view(manager)


class SecretsTab(TranslatableMixin, QWidget):
    """Manage the encrypted secret vault used by ``${secrets.NAME}``."""

    #: Checked against the active RBAC role when the page is shown.
    REQUIRED_COMMANDS = ("AC_secret_init", "AC_secret_unlock", "AC_secret_lock",
                         "AC_secret_set", "AC_secret_remove")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tr_init()
        self._status_label = QLabel()
        self._refusal = RefusalLabel()
        self._passphrase = QLineEdit()
        self._passphrase.setEchoMode(QLineEdit.EchoMode.Password)
        self._list = QListWidget()
        self._list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._view = _VaultView(False, False)
        self._runs = TabTask(self)          # one vault command at a time, off the GUI thread
        self._runs.result.connect(self._on_done)
        self._runs.error.connect(self._on_failed)
        self._runs.finished.connect(self._show_status)     # the task is no longer running only by now
        self._build_layout()
        self._show_view(_read_view(default_secret_manager))

    def dispose(self) -> None:
        """Cancel a vault command still out; its result is dropped. Safe to call twice."""
        release_resources(self)

    def retranslate(self) -> None:
        TranslatableMixin.retranslate(self)
        self._show_status()

    def _build_layout(self) -> None:
        # Vault commands (init/unlock/lock/add/remove/change passphrase)
        # run from the Actions menu; the tab keeps only passphrase input,
        # the entry list, and the status line.
        root = QVBoxLayout(self)
        root.setSpacing(12)
        unlock_box = self._tr(QGroupBox(), "secret_unlock_group")
        unlock_layout = QFormLayout(unlock_box)
        self._tr(self._passphrase, "secret_passphrase_placeholder")
        unlock_layout.addRow(self._tr(QLabel(), "secret_passphrase_label"), self._passphrase)
        root.addWidget(unlock_box)

        manage_box = self._tr(QGroupBox(), "secret_manage_group")
        manage_layout = QVBoxLayout(manage_box)
        manage_layout.addWidget(self._list)
        root.addWidget(manage_box, stretch=1)

        self._status_label.setWordWrap(True)
        set_role(self._status_label, "hint")
        root.addWidget(self._status_label)
        root.addWidget(self._refusal)

    def menu_actions(self) -> list[tuple[str, Callable[[], None]]]:
        """Expose tab commands to the window-level Actions menu."""
        return [
            ("secret_unlock", self._on_unlock),
            ("secret_lock", self._on_lock),
            ("secret_add", self._on_add),
            ("secret_remove", self._on_remove),
            ("secret_init", self._on_init),
            ("secret_change_passphrase", self._on_change_passphrase),
        ]

    def _show_status(self) -> None:
        if self._runs.running:
            self._status_label.setText(_t("task_running"))
        elif not self._view.initialized:
            self._status_label.setText(_t("secret_status_uninitialized"))
        elif self._view.unlocked:
            self._status_label.setText(_t("secret_status_unlocked"))
        else:
            self._status_label.setText(_t("secret_status_locked"))

    def _show_view(self, view: _VaultView) -> None:
        self._view = view
        self._list.clear()
        for name in view.names:
            self._list.addItem(QListWidgetItem(name))
        self._show_status()

    def _consume_passphrase(self) -> str:
        text = self._passphrase.text()
        self._passphrase.clear()
        return text

    def _start(self, command: str, tag: str, call: Optional[Callable[[], Any]]) -> None:
        """Run ``call`` off the GUI thread as ``command`` when the role allows it and no command is running."""
        if not self._refusal.allows(command):
            return
        work = functools.partial(_vault_work, command, default_secret_manager, call)
        if not self._runs.start(work, tag=tag):
            self._status_label.setText(_t("task_busy"))
            return
        self._show_status()

    def _on_done(self, result: Tuple[Any, _VaultView]) -> None:
        outcome, view = result
        tag = self._runs.tag
        self._show_view(view)
        if tag == "secret_unlock" and outcome is False:
            QMessageBox.warning(self, _t(tag), _t("secret_wrong_passphrase"))
        elif tag in _DONE_MESSAGES:
            QMessageBox.information(self, _t(tag), _t(_DONE_MESSAGES[tag]))

    def _on_failed(self, error: object) -> None:
        QMessageBox.warning(self, _t(self._runs.tag or "secret_manage_group"), str(error))

    def _on_init(self) -> None:
        passphrase = self._consume_passphrase()
        if not passphrase:
            QMessageBox.warning(self, _t("secret_init"),
                                _t("secret_passphrase_required"))
            return
        self._start("AC_secret_init", "secret_init",
                    functools.partial(default_secret_manager.initialize, passphrase))

    def _on_unlock(self) -> None:
        passphrase = self._consume_passphrase()
        if not passphrase:
            return
        self._start("AC_secret_unlock", "secret_unlock",
                    functools.partial(default_secret_manager.unlock, passphrase))

    def _on_lock(self) -> None:
        self._start("AC_secret_lock", "secret_lock", default_secret_manager.lock)

    def _on_add(self) -> None:
        if not self._refusal.allows("AC_secret_set"):
            return
        if not self._view.unlocked:
            QMessageBox.information(self, _t("secret_add"),
                                    _t("secret_unlock_first"))
            return
        name, ok = QInputDialog.getText(
            self, _t("secret_add"), _t("secret_name_prompt"),
        )
        if not ok or not name.strip():
            return
        value, ok = QInputDialog.getText(
            self, _t("secret_add"), _t("secret_value_prompt"),
            QLineEdit.EchoMode.Password,
        )
        if not ok:
            return
        self._start("AC_secret_set", "secret_add",
                    functools.partial(default_secret_manager.set, name.strip(), value))

    def _on_remove(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        self._start("AC_secret_remove", "secret_remove",
                    functools.partial(default_secret_manager.remove, item.text()))

    def _on_change_passphrase(self) -> None:
        # Re-keying the vault is creating it anew under another passphrase.
        if not self._refusal.allows("AC_secret_init"):
            return
        old, ok = QInputDialog.getText(
            self, _t("secret_change_passphrase"),
            _t("secret_old_passphrase_prompt"), QLineEdit.EchoMode.Password,
        )
        if not ok:
            return
        new, ok = QInputDialog.getText(
            self, _t("secret_change_passphrase"),
            _t("secret_new_passphrase_prompt"), QLineEdit.EchoMode.Password,
        )
        if not ok or not new:
            return
        self._start("AC_secret_init", "secret_change_passphrase",
                    functools.partial(default_secret_manager.change_passphrase, old, new))
