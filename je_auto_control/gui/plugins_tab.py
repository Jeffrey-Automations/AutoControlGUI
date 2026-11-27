"""Plugins tab: load extra AC_ commands from a user directory.

Loading reads and imports every plugin file in the directory, so it runs as a
:class:`~je_auto_control.gui._tab_task.TabTask`; the commands it found are
registered with the executor back on the GUI thread. Loading is
``AC_load_plugins`` and is checked against the active RBAC role first.
"""
import functools
from typing import Any, Callable, Dict, Optional

from PySide6.QtWidgets import (
    QFileDialog, QFormLayout, QLabel, QLineEdit, QListWidget, QMessageBox,
    QVBoxLayout, QWidget,
)

from je_auto_control.gui._authorize import RefusalLabel
from je_auto_control.gui._dispose import release_resources
from je_auto_control.gui._i18n_helpers import TranslatableMixin
from je_auto_control.gui._tab_task import TabTask
from je_auto_control.gui.adaptive.surfaces import Card, set_role
from je_auto_control.gui.language_wrapper.multi_language_wrapper import (
    language_wrapper,
)
from je_auto_control.utils.plugin_loader.plugin_loader import (
    load_plugin_directory, register_plugin_commands,
)
from je_auto_control.utils.rbac.policy import authorize_command

_COMMAND = "AC_load_plugins"


def _t(key: str) -> str:
    return language_wrapper.translate(key, key)


def _load_work(path: str) -> Dict[str, Callable[..., Any]]:
    """Worker thread: read and import the plugin files, as the caller who asked."""
    authorize_command(_COMMAND)
    return load_plugin_directory(path)


class PluginsTab(TranslatableMixin, QWidget):
    """Pick a directory of plugins, register their ``AC_*`` callables."""

    #: Checked against the active RBAC role when the page is shown.
    REQUIRED_COMMANDS = (_COMMAND,)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tr_init()
        self._dir_input = QLineEdit()
        self._list = QListWidget()
        self._status = QLabel()
        self._status_text = self._keyed(self._status)
        self._status_text.show("pl_no_loaded")
        self._refusal = RefusalLabel()
        self._loading = TabTask(self)       # reading and importing the plugin files
        self._loading.result.connect(self._on_loaded)
        self._loading.error.connect(self._on_load_failed)
        self._loading_path = ""
        self._build_layout()

    def dispose(self) -> None:
        """Cancel a load still out; what it found is not registered. Safe to call twice."""
        release_resources(self)

    def _build_layout(self) -> None:
        # Browse/load commands run from the Actions menu; the tab keeps
        # only the directory input, the command list, and the status.
        root = QVBoxLayout(self)
        root.setSpacing(12)
        form = QFormLayout()
        form.addRow(self._tr(QLabel(), "pl_dir_label"), self._dir_input)
        root.addWidget(Card().add(form))
        listing = Card().add(self._tr(QLabel(), "pl_registered_label")).add(self._list, stretch=1)
        root.addWidget(listing, stretch=1)
        self._status.setWordWrap(True)
        set_role(self._status, "hint")
        root.addWidget(self._status)
        root.addWidget(self._refusal)

    def menu_actions(self) -> list[tuple[str, Callable[[], None]]]:
        """Expose tab commands to the window-level Actions menu."""
        return [
            ("browse", self._browse),
            ("pl_load", self._on_load),
        ]

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, _t("pl_dialog_plugin_dir"))
        if path:
            self._dir_input.setText(path)

    def _on_load(self) -> None:
        path = self._dir_input.text().strip()
        if not path or not self._refusal.allows(_COMMAND):
            return
        if not self._loading.start(functools.partial(_load_work, path)):
            self._status_text.show("task_busy")
            return
        self._loading_path = path
        self._status_text.show("task_running")

    def _on_load_failed(self, error: object) -> None:
        self._status_text.show_plain(str(error))
        QMessageBox.warning(self, _t("gui_error_title"), str(error))

    def _on_loaded(self, commands: Dict[str, Callable[..., Any]]) -> None:
        path = self._loading_path
        if not commands:
            self._status_text.show("pl_none_found", path=path)
            return
        registered = register_plugin_commands(commands)
        self._list.clear()
        for name in registered:
            self._list.addItem(name)
        self._status_text.show("pl_registered", count=len(registered), path=path)
