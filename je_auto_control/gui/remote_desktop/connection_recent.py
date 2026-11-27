"""The Recent list of the Quick Connect screen: remembered targets and Wake-on-LAN.

One interaction group of ``connection_screen.QuickConnectScreen``, kept as a
mixin so the screen class still owns every widget and slot under its original
name. Writing to the address book (a JSON file) and sending the Wake-on-LAN
packet run off the GUI thread; the list is repainted once a write reports.
"""
import functools
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QInputDialog, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QWidget,
)

from je_auto_control.gui._weak_call import weak_slot
from je_auto_control.gui.remote_desktop._helpers import _t
from je_auto_control.gui.tab_task_controller import task_controller
from je_auto_control.utils.logging.logging_instance import autocontrol_logger
from je_auto_control.utils.remote_desktop.wake_on_lan import (
    send_magic_packet,
)

_TCP_RECENT_PREFIX = "tcp://"
_RECENT_MAX = 20


class _RecentConnectionsMixin:
    """Methods of ``QuickConnectScreen``; the module docstring says which group."""

    if TYPE_CHECKING:
        # Declared, never defined: the screen this is mixed into owns them.
        _book: Any
        _recent: QListWidget
        _connect_target: QLineEdit

    def _as_widget(self) -> QWidget:
        """This object as the widget it is once mixed into the screen (a dialog's parent)."""
        return cast(QWidget, self)

    def _remember_tcp(self, host: str, port: int) -> None:
        self._remember_url(f"{_TCP_RECENT_PREFIX}{host}:{port}")

    def _remember_url(self, url: str) -> None:
        """Record ``url`` in the address book, off the GUI thread, so it shows up in Recent."""
        self._in_background(functools.partial(self._book.upsert, host_id=url, server_url=url, label=""),
                            self._on_recent_changed, _log_book_failure)

    def _in_background(self, call: Callable[[], object], on_result: Callable[[Any], object],
                       on_error: Callable[[Any], object]) -> None:
        """Run ``call()`` on a worker; ``on_result`` / ``on_error`` (held weakly) follow on the GUI thread."""
        task = task_controller().submit(functools.partial(_without_token, call), owner=self._as_widget())
        task.result.connect(weak_slot(on_result))
        task.error.connect(weak_slot(on_error))

    def _on_recent_changed(self, _outcome: object = None) -> None:
        self._refresh_recent()

    def _refresh_recent(self) -> None:
        self._recent.clear()
        entries = self._book.list_entries()
        entries.sort(key=lambda e: e.get("last_used", ""), reverse=True)
        for entry in entries[:_RECENT_MAX]:
            host_id = str(entry.get("host_id", ""))
            label = str(entry.get("label") or host_id)
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, host_id)
            self._recent.addItem(item)

    def _on_recent_activated(self, item: QListWidgetItem) -> None:
        target = item.data(Qt.ItemDataRole.UserRole) or item.text()
        self._connect_target.setText(str(target))

    def _on_recent_menu(self, pos: Any) -> None:
        """Right-click menu on the Recent list: edit MAC, send WoL."""
        item = self._recent.itemAt(pos)
        if item is None:
            return
        host_id = str(item.data(Qt.ItemDataRole.UserRole) or item.text())
        entry = self._find_address_book_entry(host_id)
        menu = QMenu(self._recent)
        wake = menu.addAction(_t("rd_quick_wake_host"))
        edit = menu.addAction(_t("rd_quick_edit_mac"))
        chosen = menu.exec(self._recent.mapToGlobal(pos))
        if chosen is wake:
            self._send_wake_on_lan(entry, host_id)
        elif chosen is edit:
            self._edit_recent_mac(entry, host_id)

    def _find_address_book_entry(self, host_id: str) -> Optional[Dict[str, Any]]:
        for entry in self._book.list_entries():
            if entry.get("host_id") == host_id:
                return entry
        return None

    def _send_wake_on_lan(self, entry: Optional[Dict[str, Any]], host_id: str) -> None:
        mac = (entry or {}).get("mac_address")
        if not mac:
            mac, ok = QInputDialog.getText(
                self._as_widget(), _t("rd_quick_wake_host"),
                _t("rd_quick_wol_mac_prompt"),
            )
            if not ok or not mac:
                return
            self._save_mac_to_book(host_id, mac)
        broadcast = (entry or {}).get("broadcast_address")
        work = functools.partial(send_magic_packet, mac, broadcast_address=broadcast or "255.255.255.255")
        self._in_background(work, functools.partial(self._on_woken, mac), self._on_wake_failed)

    def _on_woken(self, mac: str, _outcome: object = None) -> None:
        QMessageBox.information(
            self._as_widget(), _t("rd_quick_wake_host"),
            _t("rd_quick_wol_sent").replace("{mac}", mac),
        )

    def _on_wake_failed(self, error: object) -> None:
        QMessageBox.warning(
            self._as_widget(), _t("rd_quick_wake_host"), str(error),
        )

    def _edit_recent_mac(self, entry: Optional[Dict[str, Any]], host_id: str) -> None:
        current = (entry or {}).get("mac_address") if entry else ""
        mac, ok = QInputDialog.getText(
            self._as_widget(), _t("rd_quick_edit_mac"),
            _t("rd_quick_wol_mac_prompt"),
            text=str(current or ""),
        )
        if not ok or not mac:
            return
        self._save_mac_to_book(host_id, mac)

    def _save_mac_to_book(self, host_id: str, mac: str) -> None:
        """Persist the MAC against the matching AddressBook entry."""
        entry = self._find_address_book_entry(host_id)
        if entry is not None:
            self._in_background(functools.partial(
                self._book.upsert, host_id=host_id, server_url=entry.get("server_url", host_id),
                label=entry.get("label", ""), mac_address=mac), self._on_recent_changed, _log_book_failure)


def _without_token(call: Callable[[], object], _token: object) -> object:
    """Worker thread: run ``call``; it has no cancellation checkpoint to hand the token to."""
    return call()


def _log_book_failure(error: object) -> None:
    """A Recent entry that could not be saved is skipped, as it was in the slot."""
    autocontrol_logger.debug("quick connect address book write failed: %r", error)


__all__ = ["_RecentConnectionsMixin"]
