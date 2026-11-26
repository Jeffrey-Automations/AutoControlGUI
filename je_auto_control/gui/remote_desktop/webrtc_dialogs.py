"""Custom dialogs / list widgets used by the WebRTC GUI panels.

Kept out of ``webrtc_panel.py`` so that file stays focused on layout
construction and signal wiring. The known-hosts browser lives in
``webrtc_known_hosts`` and is re-exported here, so callers keep importing
every dialog from one place.
"""
from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any, Callable, Optional, Union

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QCloseEvent, QDragEnterEvent, QDragMoveEvent, QDropEvent, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from je_auto_control.gui._slow_op import app_stop_queue
from je_auto_control.gui._tab_task import TabTask
from je_auto_control.gui.remote_desktop.view_lifetime import ViewLifetime

from je_auto_control.gui.adaptive.flow_layout import field_pair, flow_of
from je_auto_control.gui.adaptive.surfaces import set_role
from je_auto_control.gui.remote_desktop._helpers import (
    _format_short_time, _iso_to_epoch, _t,
)
from je_auto_control.gui.remote_desktop.webrtc_known_hosts import (
    KnownHostsDialog,
)

if TYPE_CHECKING:
    from je_auto_control.utils.remote_desktop.audit_log import AuditLog


class PendingViewerDialog(QDialog):
    """Three-button accept/reject prompt with an optional 'trust' choice.

    ``exec()`` returns one of :pyattr:`Rejected`, :pyattr:`AcceptOnce`,
    :pyattr:`AcceptAndTrust`.
    """

    Rejected = 0
    AcceptOnce = 1
    AcceptAndTrust = 2

    def __init__(self, viewer_id: Optional[str],
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_t("rd_webrtc_pending_viewer_title"))
        self.setMinimumWidth(400)
        self._result = self.Rejected
        layout = QVBoxLayout(self)
        prompt = QLabel(_t("rd_webrtc_pending_viewer_prompt"))
        prompt.setWordWrap(True)
        layout.addWidget(prompt)
        if viewer_id:
            id_label = QLabel(f"viewer_id: {viewer_id[:12]}...{viewer_id[-4:]}")
            id_label.setTextFormat(Qt.TextFormat.PlainText)     # the viewer chose it
            id_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse,
            )
            layout.addWidget(id_label)
        button_row = QHBoxLayout()
        reject = QPushButton(_t("rd_webrtc_reject"))
        reject.clicked.connect(self._on_reject)
        button_row.addWidget(reject)
        accept = QPushButton(_t("rd_webrtc_accept_once"))
        accept.clicked.connect(self._on_accept_once)
        button_row.addWidget(accept)
        trust = QPushButton(_t("rd_webrtc_accept_and_trust"))
        trust.clicked.connect(self._on_accept_and_trust)
        trust.setEnabled(bool(viewer_id))
        button_row.addWidget(trust)
        layout.addLayout(button_row)

    def _on_reject(self) -> None:
        self._result = self.Rejected
        self.accept()

    def _on_accept_once(self) -> None:
        self._result = self.AcceptOnce
        self.accept()

    def _on_accept_and_trust(self) -> None:
        self._result = self.AcceptAndTrust
        self.accept()

    def choice(self) -> int:
        return self._result


class TrustedViewersList(QListWidget):
    """List widget rendering trusted viewers; emits ``removed`` on Delete."""

    removed = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSelectionMode(self.SelectionMode.SingleSelection)

    def populate(self, entries: list[dict[str, Any]]) -> None:
        self.clear()
        for entry in entries:
            viewer_id = entry.get("viewer_id", "")
            label = entry.get("label", "") or "(unlabeled)"
            last_used = _format_short_time(entry.get("last_used"))
            suffix = f"  ({last_used})" if last_used else ""
            display = f"{label} - {str(viewer_id)[:8]}...{suffix}"
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, viewer_id)
            self.addItem(item)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 Qt override
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            item = self.currentItem()
            if item is not None:
                viewer_id = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(viewer_id, str):
                    self.removed.emit(viewer_id)
                    return
        super().keyPressEvent(event)


def _format_size(value: Any) -> str:
    """``1,234`` for a byte count, or the value as the host sent it."""
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError, OverflowError):
        return str(value)


class AddressBookList(QListWidget):
    """List widget rendering address-book entries; emits selection signals."""

    chosen = Signal(dict)
    deleted = Signal(dict)
    favorite_toggled = Signal(dict)
    tags_edit_requested = Signal(dict)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSelectionMode(self.SelectionMode.SingleSelection)
        self.itemDoubleClicked.connect(self._on_double_click)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

    def _on_context_menu(self, position: QPoint) -> None:
        entry = self.selected_entry()
        if entry is None:
            return
        menu = QMenu(self)
        connect_action = menu.addAction(_t("rd_webrtc_connect_selected"))
        fav_label = (
            "rd_webrtc_unfavorite" if entry.get("favorite")
            else "rd_webrtc_favorite"
        )
        fav_action = menu.addAction(_t(fav_label))
        tags_action = menu.addAction(_t("rd_webrtc_edit_tags"))
        delete_action = menu.addAction(_t("rd_webrtc_remove_selected"))
        chosen_act = menu.exec(self.viewport().mapToGlobal(position))
        if chosen_act is connect_action:
            self.chosen.emit(entry)
        elif chosen_act is fav_action:
            self.favorite_toggled.emit(entry)
        elif chosen_act is tags_action:
            self.tags_edit_requested.emit(entry)
        elif chosen_act is delete_action:
            self.deleted.emit(entry)

    def populate(self, entries: list[dict[str, Any]], tag_filter: str = "") -> None:
        if tag_filter:
            entries = [
                e for e in entries
                if tag_filter in (e.get("tags", []) or [])
            ]
        # Favorites first, then by last_used desc
        sorted_entries = sorted(
            entries,
            key=lambda e: (
                not bool(e.get("favorite", False)),
                -_iso_to_epoch(e.get("last_used")),
            ),
        )
        self.clear()
        for entry in sorted_entries:
            item = QListWidgetItem(self._format_entry(entry))
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.addItem(item)

    @staticmethod
    def _format_entry(entry: dict[str, Any]) -> str:
        """Build the one-line display label for an address-book entry."""
        label = entry.get("label", "") or "(unnamed)"
        host_id = entry.get("host_id", "")
        star = "★ " if entry.get("favorite") else ""
        last_used = _format_short_time(entry.get("last_used"))
        tags = entry.get("tags", []) or []
        tag_str = (" [" + ", ".join(tags) + "]") if tags else ""
        suffix = f"  ({last_used})" if last_used else ""
        return f"{star}{label} - {host_id}{tag_str}{suffix}"

    def selected_entry(self) -> Optional[dict[str, Any]]:
        item = self.currentItem()
        if item is None:
            return None
        entry = item.data(Qt.ItemDataRole.UserRole)
        return dict(entry) if isinstance(entry, dict) else None

    def _on_double_click(self, item: QListWidgetItem) -> None:
        entry = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(entry, dict):
            self.chosen.emit(dict(entry))

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 Qt override
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            entry = self.selected_entry()
            if entry is not None:
                self.deleted.emit(entry)
                return
        super().keyPressEvent(event)


class RemoteFilesTable(QTableWidget):
    """Multi-select remote-file table with drag-upload + context menu.

    Emits:
      * ``pull_requested(list[str])`` — names of selected rows
      * ``delete_requested(list[str])``
      * ``upload_requested(list[str])`` — local paths from a drag-drop
      * ``copy_name_requested(str)`` — single name from context menu
    """

    pull_requested = Signal(list)
    delete_requested = Signal(list)
    upload_requested = Signal(list)
    copy_name_requested = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(0, 3, parent)
        self.retranslate()
        self.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch,
        )
        self.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows,
        )
        self.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection,
        )
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)  # Pull and Delete read the names
        self.setMaximumHeight(180)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def retranslate(self) -> None:
        """Re-read the column titles in the active language."""
        self.setHorizontalHeaderLabels([
            _t("rd_webrtc_browse_col_name"),
            _t("rd_webrtc_browse_col_size"),
            _t("rd_webrtc_browse_col_mtime"),
        ])

    def selected_names(self) -> list[str]:
        names: list[str] = []
        for row in sorted({i.row() for i in self.selectedIndexes()}):
            item = self.item(row, 0)
            if item is not None:
                names.append(item.text())
        return names

    def populate(self, files: list[Any], format_mtime: Callable[[Any], str]) -> None:
        """Replace contents. ``format_mtime(value) -> str`` formats the column.

        ``files`` comes from the remote host: an entry that is not an object
        is skipped, and a size that is not a number is shown as sent. Either
        used to raise out of the listing and leave the table half-filled.
        """
        rows = [entry for entry in files if isinstance(entry, dict)]
        self.setRowCount(len(rows))
        for row, entry in enumerate(rows):
            name = str(entry.get("name", ""))
            mtime_str = format_mtime(entry.get("mtime"))
            self.setItem(row, 0, QTableWidgetItem(name))
            self.setItem(row, 1, QTableWidgetItem(_format_size(entry.get("size", 0))))
            self.setItem(row, 2, QTableWidgetItem(mtime_str))

    # --- drag-and-drop ------------------------------------------------------

    def _accept_url_drag(self, event: QDragMoveEvent) -> None:
        """Shared drag handler: accept iff the payload carries file URLs."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 Qt override
        self._accept_url_drag(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802 Qt override
        self._accept_url_drag(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 Qt override
        urls = event.mimeData().urls()
        from pathlib import Path as _Path
        paths = [
            url.toLocalFile() for url in urls
            if url.isLocalFile() and url.toLocalFile()
        ]
        files = [p for p in paths if _Path(p).is_file()]
        if files:
            self.upload_requested.emit(files)
            event.acceptProposedAction()

    # --- context menu -------------------------------------------------------

    def _show_context_menu(self, position: QPoint) -> None:
        names = self.selected_names()
        if not names:
            return
        menu = QMenu(self)
        pull_action = menu.addAction(_t("rd_webrtc_browse_pull"))
        delete_action = menu.addAction(_t("rd_webrtc_browse_delete"))
        copy_action = menu.addAction(_t("rd_webrtc_browse_copy_name"))
        if len(names) > 1:
            copy_action.setEnabled(False)
        chosen = menu.exec(self.viewport().mapToGlobal(position))
        if chosen is pull_action:
            self.pull_requested.emit(names)
        elif chosen is delete_action:
            self.delete_requested.emit(names)
        elif chosen is copy_action and names:
            self.copy_name_requested.emit(names[0])


class AuditLogDialog(QDialog):
    """Browse the SQLite audit log with filter on event_type / host_id; each query runs off the GUI thread.

    ``audit_log`` may also be a function that opens the log (``default_audit_log``):
    it is then called on the query's worker too, since opening it creates the
    database. Refresh is disabled while a query is out, and closing the dialog
    drops a query that has not answered.
    """

    def __init__(self, audit_log: Union[AuditLog, Callable[[], AuditLog]],
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._log = audit_log
        self._task = TabTask(self, details=False)
        self._task.result.connect(self._show_rows)
        self._task.error.connect(self._show_error)
        self._task.finished.connect(self._query_done)
        self.setWindowTitle(_t("rd_webrtc_audit_title"))
        self.setMinimumSize(820, 380)
        layout = QVBoxLayout(self)
        self._type_edit = QLineEdit()
        self._type_edit.setPlaceholderText(_t("rd_webrtc_audit_filter_type_ph"))
        self._host_edit = QLineEdit()
        self._refresh_btn = QPushButton(_t("rd_webrtc_audit_refresh"))
        self._refresh_btn.clicked.connect(self._refresh)
        layout.addLayout(flow_of(
            field_pair(QLabel(_t("rd_webrtc_audit_filter_type")), self._type_edit),
            field_pair(QLabel(_t("rd_webrtc_audit_filter_host")), self._host_edit),
            self._refresh_btn))
        self._status = QLabel()
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        set_role(self._status, "hint")
        layout.addWidget(self._status)
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels([
            _t("rd_webrtc_audit_col_ts"),
            _t("rd_webrtc_audit_col_type"),
            _t("rd_webrtc_audit_col_host"),
            _t("rd_webrtc_audit_col_viewer"),
            _t("rd_webrtc_audit_col_detail"),
        ])
        self._table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch,
        )
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers,
        )
        layout.addWidget(self._table)
        button_row = QHBoxLayout()
        button_row.addStretch()
        close_btn = QPushButton(_t("rd_webrtc_kh_close"))
        close_btn.clicked.connect(self.accept)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)
        self._refresh()

    def _refresh(self) -> None:
        query = functools.partial(_query_audit_log, self._log, self._type_edit.text().strip() or None,
                                  self._host_edit.text().strip() or None)
        if self._task.start(query):
            self._refresh_btn.setEnabled(False)
            self._status.setText(_t("gui_op_loading"))

    def _query_done(self) -> None:
        self._refresh_btn.setEnabled(True)

    def _show_error(self, error: object) -> None:
        self._status.setText(str(error))

    def done(self, result: int) -> None:
        """Close the dialog; a query still out is dropped, not shown in a closed dialog."""
        self._task.stop()
        super().done(result)

    def _show_rows(self, rows: list[dict[str, Any]]) -> None:
        from datetime import datetime
        self._status.clear()
        self._table.setRowCount(len(rows))
        for r, entry in enumerate(rows):
            ts = entry.get("ts", "")
            try:
                ts = datetime.fromisoformat(ts).astimezone().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            except (TypeError, ValueError):
                pass
            cells = [
                ts,
                entry.get("event_type", ""),
                (entry.get("host_id") or "")[:16],
                (entry.get("viewer_id") or "")[:16],
                entry.get("detail") or "",
            ]
            for c, text in enumerate(cells):
                self._table.setItem(r, c, QTableWidgetItem(text))


def _query_audit_log(source: Union[AuditLog, Callable[[], AuditLog]], event_type: Optional[str],
                     host_id: Optional[str]) -> list[dict[str, Any]]:
    """Worker thread: open the log if ``source`` is its opener, then read the newest 500 matching rows."""
    audit_log = source() if callable(source) else source
    return audit_log.query(event_type=event_type, host_id=host_id, limit=500)


class LanBrowseDialog(QDialog):
    """Dialog that browses the LAN for AutoControl hosts via mDNS.

    Polls a ``HostBrowser`` instance and lists discovered hosts in real
    time. ``chosen`` signal carries the selected service dict.
    """

    chosen = Signal(dict)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        # The zeroconf thread reports through this lease: it holds the dialog
        # weakly, reaches the GUI thread queued, and drops reports once the
        # dialog has ended -- the browser must not be what keeps it alive.
        self._view = ViewLifetime(self)
        self.setWindowTitle(_t("rd_webrtc_lan_title"))
        self.setMinimumSize(620, 260)
        self._services: dict[str, dict[str, Any]] = {}
        layout = QVBoxLayout(self)
        help_label = QLabel(_t("rd_webrtc_lan_help"))
        help_label.setWordWrap(True)
        set_role(help_label, "hint")
        layout.addWidget(help_label)
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels([
            _t("rd_webrtc_lan_col_host"),
            _t("rd_webrtc_lan_col_ip"),
            _t("rd_webrtc_lan_col_signaling"),
            _t("rd_webrtc_lan_col_name"),
        ])
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch,
        )
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows,
        )
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection,
        )
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers,
        )
        layout.addWidget(self._table)
        button_row = QHBoxLayout()
        button_row.addStretch()
        use_btn = QPushButton(_t("rd_webrtc_lan_use"))
        use_btn.clicked.connect(self._on_use)
        button_row.addWidget(use_btn)
        cancel_btn = QPushButton(_t("rd_webrtc_kh_close"))
        cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(cancel_btn)
        layout.addLayout(button_row)
        # Defer browser start until the dialog is shown so we don't burn
        # mDNS sockets when the dialog is constructed lazily.
        self._browser: Optional[Any] = None
        self._start_browser()

    def _start_browser(self) -> None:
        try:
            from je_auto_control.utils.remote_desktop.lan_discovery import (
                HostBrowser, is_discovery_available,
            )
        except ImportError:
            return
        if not is_discovery_available():
            return
        try:
            self._browser = HostBrowser(on_change=self._view.callback("_on_services_changed"))
        except (RuntimeError, OSError):
            self._browser = None

    def _update_services(self, services: dict[str, dict[str, Any]]) -> None:
        """Any thread: report the hosts seen; the table is redrawn on the GUI thread."""
        self._view.post("_on_services_changed", dict(services))

    def _on_services_changed(self, services: dict[str, dict[str, Any]]) -> None:
        self._services = dict(services)
        self._refresh()

    def _refresh(self) -> None:
        items = sorted(self._services.values(), key=lambda s: s.get("host_id", ""))
        self._table.setRowCount(len(items))
        for r, svc in enumerate(items):
            self._table.setItem(r, 0, QTableWidgetItem(svc.get("host_id", "")))
            self._table.setItem(r, 1, QTableWidgetItem(svc.get("ip", "")))
            self._table.setItem(
                r, 2, QTableWidgetItem(svc.get("signaling_url", "")),
            )
            self._table.setItem(r, 3, QTableWidgetItem(svc.get("name", "")))

    def _on_use(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        item = self._table.item(row, 0)
        host_id = item.text() if item is not None else ""
        if host_id and host_id in [s.get("host_id") for s in self._services.values()]:
            for svc in self._services.values():
                if svc.get("host_id") == host_id:
                    self.chosen.emit(svc)
                    self.accept()
                    return

    def _stop_browser(self) -> None:
        """Let go of the browser now; closing it (which joins zeroconf's thread) runs on a worker.

        It goes to the application's stop queue, not one of the dialog's: the
        dialog is normally destroyed right after, and a stop that fails is kept
        by the stop custody with the browser that still owns its socket.
        """
        browser, self._browser = self._browser, None
        self._view.retire()
        if browser is not None:
            app_stop_queue().retire(browser.stop)

    def done(self, result: int) -> None:  # noqa: D401  # Qt override
        """Stop browsing however the dialog ends.

        ``accept()`` / ``reject()`` (Use, Cancel, Esc) end in ``done()`` and
        never reach ``closeEvent``, so each dialog closed that way left a
        zeroconf browser thread running.
        """
        self._stop_browser()
        super().done(result)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 Qt override
        self._stop_browser()
        super().closeEvent(event)


__all__ = [
    "PendingViewerDialog", "TrustedViewersList", "AddressBookList",
    "RemoteFilesTable", "KnownHostsDialog", "AuditLogDialog",
    "LanBrowseDialog",
]
