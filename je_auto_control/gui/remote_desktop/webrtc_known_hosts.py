"""Known-hosts browser for the WebRTC GUI panels.

Split out of ``webrtc_dialogs.py``: the TOFU pin store gets its own table
dialog plus a small out-of-band pinning form, and neither shares state with
the viewer / address-book / audit dialogs next door. The shared fingerprint
and timestamp formatters live in ``_helpers``.

Every pin, forget, import and export reads or writes a file, so each runs off
the GUI thread, one at a time (``_read_task`` reads an import, ``_write_task``
writes); the table is repainted once it has reported, and closing the dialog
drops what is still out.
"""
from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QLineEdit, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from je_auto_control.gui._dispose import release_resources
from je_auto_control.gui.adaptive.flow_layout import flow_of
from je_auto_control.gui.remote_desktop._helpers import (
    _format_last_seen, _short_fp, _t, _write_json_file,
)
from je_auto_control.gui.remote_desktop.webrtc_panel_common import start_panel_call
from je_auto_control.gui.tab_task_controller import TaskHandle

if TYPE_CHECKING:
    from datetime import datetime, timedelta

    from je_auto_control.utils.remote_desktop.fingerprint import KnownHosts


class KnownHostsDialog(QDialog):
    """Browse + forget the persistent KnownHosts (TOFU app + DTLS fingerprints)."""

    def __init__(self, known_hosts: KnownHosts, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._known = known_hosts
        self._read_task: Optional[TaskHandle] = None
        self._write_task: Optional[TaskHandle] = None
        self.setWindowTitle(_t("rd_webrtc_known_hosts_title"))
        self.setMinimumSize(720, 360)
        layout = QVBoxLayout(self)
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels([
            _t("rd_webrtc_kh_col_host"),
            _t("rd_webrtc_kh_col_app_fp"),
            _t("rd_webrtc_kh_col_dtls_fp"),
            _t("rd_webrtc_kh_col_last_seen"),
        ])
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch,
        )
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch,
        )
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows,
        )
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection,
        )
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers,
        )
        layout.addWidget(self._table)
        buttons = []
        for key, slot in (
            ("rd_webrtc_kh_add", self._on_add_manual),
            ("rd_webrtc_kh_import", self._on_import),
            ("rd_webrtc_kh_export", self._on_export),
            ("rd_webrtc_kh_copy_app", self._on_copy_app),
            ("rd_webrtc_kh_copy_dtls", self._on_copy_dtls),
            ("rd_webrtc_kh_forget", self._on_forget),
            ("rd_webrtc_kh_forget_stale", self._on_forget_stale),
            ("rd_webrtc_kh_clear_all", self._on_clear_all),
        ):
            button = QPushButton(_t(key))
            button.clicked.connect(slot)
            buttons.append(button)
        # Eight actions wrap onto a second line in a narrow dialog; Close stays on the right.
        button_row = QHBoxLayout()
        button_row.addLayout(flow_of(*buttons, spacing=8), stretch=1)
        close_btn = QPushButton(_t("rd_webrtc_kh_close"))
        close_btn.clicked.connect(self.accept)
        button_row.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(button_row)
        self._refresh()

    def _refresh(self) -> None:
        from datetime import datetime, timedelta, timezone
        stale_after = timedelta(days=90)
        now = datetime.now(timezone.utc)
        stale_color = QColor("#888")
        entries = self._known.list_entries()
        self._table.setRowCount(len(entries))
        for row, (host_id, fps) in enumerate(sorted(entries.items())):
            self._populate_row(row, host_id, fps,
                               now=now, stale_after=stale_after,
                               stale_color=stale_color)

    def dispose(self) -> None:
        """Drop the reads and writes still out (each still runs to its end). Safe to call twice."""
        release_resources(self)

    def done(self, result: int) -> None:
        """Close the dialog, dropping what it still has out."""
        self.dispose()
        super().done(result)

    def _busy(self) -> bool:
        if self._read_task is None and self._write_task is None:
            return False
        QMessageBox.information(self, "WebRTC", _t("task_busy"))
        return True

    def _run_write(self, call: Callable[[], object],
                   on_result: Optional[Callable[[Any], object]] = None) -> None:
        """Pin, forget or export off the GUI thread; the table is repainted when it reports."""
        if not self._busy():
            self._start_write(call, on_result)

    def _start_write(self, call: Callable[[], object],
                     on_result: Optional[Callable[[Any], object]] = None) -> None:
        start_panel_call(self, "_write_task", call, on_result or self._on_written, self._on_io_failed)

    def _on_written(self, _outcome: object = None) -> None:
        self._refresh()

    def _on_io_failed(self, error: object) -> None:
        QMessageBox.warning(self, "WebRTC", str(error))
        self._refresh()

    def _populate_row(self, row: int, host_id: str, fps: Dict[str, Optional[str]], *,
                      now: datetime, stale_after: timedelta, stale_color: QColor) -> None:
        items = [
            QTableWidgetItem(host_id),
            QTableWidgetItem(_short_fp(fps.get("app_fp"))),
            QTableWidgetItem(_short_fp(fps.get("dtls_fp"))),
            QTableWidgetItem(_format_last_seen(fps.get("last_seen"))),
        ]
        if self._is_stale(fps.get("last_seen"), now=now,
                          stale_after=stale_after):
            tip = _t("rd_webrtc_kh_stale_tip")
            for it in items:
                it.setForeground(stale_color)
                it.setToolTip(tip)
        for col, item in enumerate(items):
            self._table.setItem(row, col, item)

    @staticmethod
    def _is_stale(last_seen: Optional[str], *, now: datetime, stale_after: timedelta) -> bool:
        if not last_seen:
            return False
        from datetime import datetime, timezone
        try:
            dt = datetime.fromisoformat(last_seen)
        except (TypeError, ValueError):
            return False
        if dt.tzinfo is None:
            # Against the aware "now" a naive time raised TypeError and
            # stopped the table half-filled.
            dt = dt.replace(tzinfo=timezone.utc)
        return now - dt > stale_after

    def _on_forget(self) -> None:
        rows = sorted(
            {i.row() for i in self._table.selectedIndexes()}, reverse=True,
        )
        host_ids = [item.text() for item in (self._table.item(row, 0) for row in rows) if item is not None]
        if host_ids:
            self._run_write(functools.partial(_forget_all, self._known, host_ids))

    def _on_add_manual(self) -> None:
        dialog = _ManualKnownHostDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        host_id, app_fp, dtls_fp = dialog.values()
        if host_id:
            self._run_write(functools.partial(_pin_all, self._known, [(host_id, app_fp, dtls_fp)]))

    def _on_copy_app(self) -> None:
        self._copy_selected_fingerprint("app_fp")

    def _on_copy_dtls(self) -> None:
        self._copy_selected_fingerprint("dtls_fp")

    def _copy_selected_fingerprint(self, key: str) -> None:
        from PySide6.QtWidgets import QApplication as _QApp
        row = self._table.currentRow()
        if row < 0:
            return
        host_item = self._table.item(row, 0)
        if host_item is None:
            return
        entries = self._known.list_entries()
        fps = entries.get(host_item.text())
        if not fps:
            return
        value = fps.get(key) or ""
        clipboard = _QApp.clipboard()
        if clipboard is not None:
            clipboard.setText(value)

    def _on_export(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, _t("rd_webrtc_kh_export"), "known_hosts.json",
            "JSON (*.json);;All (*)",
        )
        if path:
            self._run_write(functools.partial(_write_json_file, path, self._known.list_entries()))

    def _on_import(self) -> None:
        if self._busy():
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, _t("rd_webrtc_kh_import"), "", "JSON (*.json);;All (*)",
        )
        if path:
            start_panel_call(self, "_read_task", functools.partial(_read_json_file, path),
                             self._on_import_read, self._on_io_failed)

    def _on_import_read(self, data: object) -> None:
        """GUI thread: ask about each host already pinned, then pin the rest off the GUI thread."""
        if not isinstance(data, dict):
            QMessageBox.warning(
                self, "WebRTC", _t("rd_webrtc_kh_import_bad"),
            )
            return
        existing = self._known.list_entries()
        pins: List[Tuple[str, object, object]] = []
        skipped = 0
        for host_id, value in data.items():
            outcome = self._import_one(host_id, value, existing)
            if isinstance(outcome, tuple):
                pins.append(outcome)
            elif outcome == "skipped":
                skipped += 1
        self._start_write(functools.partial(_pin_all, self._known, pins),
                          functools.partial(self._on_imported, skipped))

    def _on_imported(self, skipped: int, added: int) -> None:
        QMessageBox.information(
            self, "WebRTC",
            _t("rd_webrtc_kh_import_done").format(added=added, skipped=skipped),
        )
        self._refresh()

    def _import_one(self, host_id: object, value: object,
                    existing: Dict[str, Dict[str, Optional[str]]]) -> object:
        """Return the pin to make, ``"skipped"`` or ``"ignored"`` for one entry."""
        if not isinstance(host_id, str):
            return "ignored"
        app_fp, dtls_fp = self._extract_fingerprints(value)
        if app_fp is None and dtls_fp is None:
            return "ignored"
        if host_id in existing and not self._confirm_overwrite(host_id):
            return "skipped"
        return host_id, app_fp, dtls_fp

    @staticmethod
    def _extract_fingerprints(value: object) -> Tuple[object, object]:
        if isinstance(value, str):
            return value, None
        if isinstance(value, dict):
            return value.get("app_fp"), value.get("dtls_fp")
        return None, None

    def _confirm_overwrite(self, host_id: str) -> bool:
        result = QMessageBox.question(
            self, "WebRTC",
            _t("rd_webrtc_kh_import_overwrite").format(host=host_id),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return result == QMessageBox.StandardButton.Yes

    def _on_forget_stale(self) -> None:
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        # The rule the table greys a row by: a naive time was shown stale and never forgotten.
        stale_ids = [host_id for host_id, fps in self._known.list_entries().items()
                     if self._is_stale(fps.get("last_seen"), now=now, stale_after=timedelta(days=90))]
        if not stale_ids:
            QMessageBox.information(
                self, "WebRTC", _t("rd_webrtc_kh_no_stale"),
            )
            return
        result = QMessageBox.question(
            self, "WebRTC",
            _t("rd_webrtc_kh_forget_stale_confirm").format(n=len(stale_ids)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        self._run_write(functools.partial(_forget_all, self._known, stale_ids))

    def _on_clear_all(self) -> None:
        from PySide6.QtWidgets import QMessageBox as _QMB
        result = _QMB.question(
            self, "WebRTC", _t("rd_webrtc_kh_clear_confirm"),
            _QMB.StandardButton.Yes | _QMB.StandardButton.No,
        )
        if result != _QMB.StandardButton.Yes:
            return
        self._run_write(functools.partial(_forget_all, self._known, list(self._known.list_entries())))




def _read_json_file(path: str) -> object:
    """Worker thread: the JSON document at ``path`` (``ValueError`` when it is not UTF-8 JSON or nests too deep)."""
    import json
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except RecursionError as error:
        raise ValueError(f"{path}: nested too deeply") from error


def _pin_all(known: KnownHosts, pins: List[Tuple[str, object, object]]) -> int:
    """Worker thread: pin each ``(host_id, app_fp, dtls_fp)``; return how many hosts were pinned."""
    for host_id, app_fp, dtls_fp in pins:
        if isinstance(app_fp, str) and app_fp:
            known.remember(host_id, app_fp)
        if isinstance(dtls_fp, str) and dtls_fp:
            known.remember_dtls_fingerprint(host_id, dtls_fp)
    return len(pins)


def _forget_all(known: KnownHosts, host_ids: List[str]) -> None:
    """Worker thread: forget each host (each forget rewrites the file)."""
    for host_id in host_ids:
        known.forget(host_id)


class _ManualKnownHostDialog(QDialog):
    """Tiny form dialog for pinning a host fingerprint out-of-band."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_t("rd_webrtc_kh_add"))
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._host_edit = QLineEdit()
        self._host_edit.setPlaceholderText(_t("rd_webrtc_kh_add_host_ph"))
        self._app_edit = QLineEdit()
        self._app_edit.setPlaceholderText(_t("rd_webrtc_kh_add_app_ph"))
        self._dtls_edit = QLineEdit()
        self._dtls_edit.setPlaceholderText(_t("rd_webrtc_kh_add_dtls_ph"))
        form.addRow(_t("rd_webrtc_kh_col_host"), self._host_edit)
        form.addRow(_t("rd_webrtc_kh_col_app_fp"), self._app_edit)
        form.addRow(_t("rd_webrtc_kh_col_dtls_fp"), self._dtls_edit)
        layout.addLayout(form)
        button_row = QHBoxLayout()
        button_row.addStretch()
        ok = QPushButton(_t("rd_webrtc_kh_add"))
        ok.clicked.connect(self.accept)
        cancel = QPushButton(_t("rd_webrtc_kh_close"))
        cancel.clicked.connect(self.reject)
        button_row.addWidget(cancel)
        button_row.addWidget(ok)
        layout.addLayout(button_row)

    def values(self) -> Tuple[str, str, str]:
        return (
            self._host_edit.text().strip(),
            self._app_edit.text().strip(),
            self._dtls_edit.text().strip(),
        )
