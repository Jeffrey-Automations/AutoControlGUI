"""Trust list, audit log and file push for the WebRTC host panel.

Every change to the trust list, and its export and import, writes or reads a
file: each runs off the GUI thread as the panel's ``_trust_task``, one at a
time, and the list is repainted once it has reported.

One interaction group of ``webrtc_panel._WebRTCHostPanel``, kept as a mixin so the panel class
still owns every widget and slot under its original name.
"""
from __future__ import annotations

from je_auto_control.gui.remote_desktop.webrtc_panel_state import _HostPanelPart

import functools
import os
from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QMessageBox,
)

from je_auto_control.gui.remote_desktop._helpers import (
    _read_import_entries, _t, _write_json_file,
)
from je_auto_control.gui.remote_desktop.webrtc_dialogs import (
    AuditLogDialog,
)
from je_auto_control.utils.logging.logging_instance import autocontrol_logger
from je_auto_control.gui.remote_desktop.webrtc_panel_common import (
    _JSON_FILE_FILTER,
    start_panel_call,
    start_panel_task,
)
from je_auto_control.gui.tab_task_controller import CancellationToken


class _HostTrustMixin(_HostPanelPart):
    """Methods of ``_WebRTCHostPanel``; the module docstring says which group."""

    def _on_view_audit(self) -> None:
        from je_auto_control.utils.remote_desktop.audit_log import (
            default_audit_log,
        )
        AuditLogDialog(default_audit_log(), parent=self).exec()

    def _on_push_file(self) -> None:
        if self._multi_host is None or self._multi_host.session_count() == 0:
            QMessageBox.information(
                self, "WebRTC", _t("rd_webrtc_no_viewers"),
            )
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, _t("rd_webrtc_push_file"), "",
        )
        if not path:
            return
        host = self._multi_host
        if host is None:            # stopped while the file dialog was open
            return
        # The whole file goes out to every viewer: off the GUI thread, one push at a time.
        if not start_panel_task(self, "_file_task", functools.partial(_broadcast_file, host, path),
                                functools.partial(self._push_done, path), self._push_failed):
            QMessageBox.information(self, "WebRTC", _t("rd_file_busy"))
            return
        self._status.show("rd_file_sending", name=os.path.basename(path))

    def _push_done(self, path: str, sent: object) -> None:
        self._status.show_plain("")
        QMessageBox.information(
            self, "WebRTC",
            _t("rd_webrtc_push_done").format(n=sent, name=path),
        )

    def _push_failed(self, error: object) -> None:
        self._status.show_plain("")
        QMessageBox.warning(self, "WebRTC", str(error))

    def _on_export_trust(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, _t("rd_webrtc_trust_export"), "trusted_viewers.json",
            _JSON_FILE_FILTER,
        )
        if not path:
            return
        entries = {"viewers": self._trust_list.list_entries()}
        self._run_trust_io(functools.partial(_write_json_file, path, entries), self._on_trust_changed)

    def _on_import_trust(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, _t("rd_webrtc_trust_import"), "", _JSON_FILE_FILTER,
        )
        if path:
            self._run_trust_io(functools.partial(_import_trusted_viewers, self._trust_list, path),
                               self._trust_imported)

    def _run_trust_io(self, call: Callable[[], object], on_result: Callable[[Any], object]) -> None:
        """Read or write the trust list (or its export) off the GUI thread, one call at a time."""
        if not start_panel_call(self, "_trust_task", call, on_result, self._trust_failed):
            QMessageBox.information(self, "WebRTC", _t("task_busy"))

    def _trust_imported(self, added: int) -> None:
        QMessageBox.information(
            self, "WebRTC",
            _t("rd_webrtc_trust_import_done").format(n=added),
        )
        self._refresh_trusted_list()

    def _trust_failed(self, error: object) -> None:
        QMessageBox.warning(self, "WebRTC", str(error))
        self._refresh_trusted_list()

    def _on_trust_changed(self, _outcome: object = None) -> None:
        self._refresh_trusted_list()

    def _refresh_trusted_list(self) -> None:
        self._trusted_list.populate(self._trust_list.list_entries())

    def _trust_session_viewer(self, sid: str) -> None:
        try:
            multi_host = self._require_multi_host()
            with multi_host._lock:
                host = multi_host._sessions.get(sid)
        except (RuntimeError, OSError, ValueError) as error:
            autocontrol_logger.warning("trust viewer: %r", error)
            return
        full_vid = host.pending_viewer_id if host is not None else None
        if full_vid:
            self._run_trust_io(functools.partial(self._trust_list.add, full_vid, label=f"sess {sid[:6]}"),
                               self._on_trust_changed)

    def _on_remove_trust(self, viewer_id: str) -> None:
        self._run_trust_io(functools.partial(self._trust_list.remove, viewer_id), self._on_trust_changed)

    def _on_remove_trust_button(self) -> None:
        item = self._trusted_list.currentItem()
        if item is None:
            return
        viewer_id = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(viewer_id, str):
            self._on_remove_trust(viewer_id)

    def _on_clear_trust(self) -> None:
        result = QMessageBox.question(
            self, "WebRTC", _t("rd_webrtc_clear_trust_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        self._run_trust_io(self._trust_list.clear, self._on_trust_changed)


def _import_trusted_viewers(trust_list: Any, path: str) -> int:
    """Worker thread: trust every viewer an exported file names; return how many were added."""
    added = 0
    for entry in _read_import_entries(path, "viewers"):
        vid, label = entry.get("viewer_id"), entry.get("label")
        if isinstance(vid, str) and vid:
            trust_list.add(vid, label=label if isinstance(label, str) else "")
            added += 1
    return added


def _broadcast_file(host: Any, path: str, _token: CancellationToken) -> int:
    """Worker thread: push ``path`` to every authenticated viewer; returns how many got it."""
    return host.broadcast_file(path)


__all__ = ["_HostTrustMixin"]
