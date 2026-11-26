"""Audit log tab: browse and verify the tamper-evident chain.

Reading, verifying (a hash over every row) and clearing the log are SQLite
work, so each runs as a :class:`~je_auto_control.gui._tab_task.TabTask`, one at
a time. Each first asks RBAC for ``AC_audit_log_list`` / ``_verify`` /
``_clear``, in the slot (the refusal is shown in the tab) and again on the
worker, as whoever started it.
"""
import functools
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from PySide6.QtWidgets import (
    QComboBox, QGroupBox, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from je_auto_control.gui._authorize import RefusalLabel
from je_auto_control.gui._dispose import release_resources
from je_auto_control.gui._i18n_helpers import TranslatableMixin
from je_auto_control.gui._tab_task import TabTask
from je_auto_control.gui.adaptive.flow_layout import field_pair, flow_of
from je_auto_control.gui.adaptive.surfaces import Card, set_role
from je_auto_control.gui.language_wrapper.multi_language_wrapper import (
    language_wrapper,
)
from je_auto_control.utils.rbac.policy import authorize_command
from je_auto_control.utils.remote_desktop.audit_log import default_audit_log


_ALL_SENTINEL = "(all)"
# Pinned at the top of the dropdown so operators can jump straight to
# them even on a fresh DB where they haven't been recorded yet.
_PINNED_PRESETS = (
    "rest_api",
    "usb_open_allowed",
    "usb_open_denied",
    "usb_open_rejected_max_claims",
    "usb_open_backend_error",
    "usb_close",
)


def build_event_type_choices(observed: Sequence[str]) -> List[str]:
    """Return the dropdown values: all-sentinel + pinned presets +
    any other event types observed in the log, deduped & ordered.
    """
    choices: List[str] = [_ALL_SENTINEL]
    seen = {_ALL_SENTINEL}
    for preset in _PINNED_PRESETS:
        if preset not in seen:
            choices.append(preset)
            seen.add(preset)
    for value in observed:
        if value and value not in seen:
            choices.append(value)
            seen.add(value)
    return choices


def _t(key: str) -> str:
    return language_wrapper.translate(key, key)


def _query_work(event_type: Optional[str], host_id: Optional[str],
                limit: int) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Worker thread: the dropdown's choices and the rows matching the filters."""
    authorize_command("AC_audit_log_list")
    log = default_audit_log()
    # Pull a wide window so the dropdown reflects everything the user
    # might want to filter on. Cheap — query() caps internally.
    choices = build_event_type_choices([row.get("event_type", "") for row in log.query(limit=5000)])
    if event_type not in choices:
        event_type = None       # the dropdown falls back to "(all)", and so does the query
    return choices, log.query(event_type=event_type, host_id=host_id, limit=limit)


def _verify_work() -> Any:
    """Worker thread: recompute the hash chain over every row."""
    authorize_command("AC_audit_log_verify")
    return default_audit_log().verify_chain()


def _clear_work() -> int:
    """Worker thread: delete every row; return how many there were."""
    authorize_command("AC_audit_log_clear")
    return int(default_audit_log().clear())


class AuditLogTab(TranslatableMixin, QWidget):
    """Browse the audit log + run chain integrity verification."""

    #: Checked against the active RBAC role when the page is shown.
    REQUIRED_COMMANDS = ("AC_audit_log_list", "AC_audit_log_verify", "AC_audit_log_clear")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tr_init()
        self._type_filter = QComboBox()
        self._type_filter.setEditable(True)
        self._type_filter.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._host_filter = QLineEdit()
        self._limit_input = QSpinBox()
        self._limit_input.setRange(1, 5000)
        self._limit_input.setValue(200)
        self._table = QTableWidget(0, 5)
        self._table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch,
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._verify_status = QLabel()
        self._refusal = RefusalLabel()
        self._runs = TabTask(self)          # one log query, verification or clear at a time
        self._runs.result.connect(self._on_result)
        self._runs.error.connect(self._on_failed)
        self._runs.finished.connect(self._on_finished)
        self._refresh_after = False
        self._build_layout()
        self._refresh()

    def dispose(self) -> None:
        """Cancel a query, verification or clear still out; its result is dropped. Safe to call twice."""
        release_resources(self)

    def _build_layout(self) -> None:
        # Refresh/verify/clear commands run from the Actions menu; the
        # tab keeps only the filter inputs, the table, and the status.
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.addWidget(self._build_filter_group())
        root.addWidget(Card().add(self._table, stretch=1), stretch=1)
        self._verify_status.setWordWrap(True)
        set_role(self._verify_status, "hint")
        root.addWidget(self._verify_status)
        root.addWidget(self._refusal)

    def retranslate(self) -> None:
        TranslatableMixin.retranslate(self)
        self._apply_table_headers()

    def menu_actions(self) -> List[Tuple[str, Callable[[], None]]]:
        """Expose tab commands to the window-level Actions menu."""
        return [
            ("audit_refresh", self._refresh),
            ("audit_verify", self._verify),
            ("audit_clear", self._clear),
        ]

    def _build_filter_group(self) -> QGroupBox:
        group = self._tr(QGroupBox(), "audit_filter_group")
        layout = QVBoxLayout(group)
        layout.addLayout(flow_of(*(field_pair(self._tr(QLabel(), key), field) for key, field in (
            ("audit_filter_type", self._type_filter), ("audit_filter_host", self._host_filter),
            ("audit_filter_limit", self._limit_input)))))
        return group

    def _start(self, command: str, tag: str, work: Callable[[], Any]) -> bool:
        if not self._refusal.allows(command):
            return False
        if not self._runs.start(work, tag=tag):
            self._verify_status.setText(_t("task_busy"))
            return False
        return True

    def _refresh(self) -> None:
        self._apply_table_headers()
        work = functools.partial(_query_work, self._current_event_type_filter(),
                                 self._host_filter.text().strip() or None, int(self._limit_input.value()))
        self._start("AC_audit_log_list", "refresh", work)

    def _on_result(self, outcome: Any) -> None:
        tag = self._runs.tag
        if tag == "refresh":
            self._show_rows(*outcome)
        elif tag == "verify":
            self._show_verified(outcome)
        else:
            self._verify_status.setText(_t("audit_clear_done").format(count=outcome))
            self._refresh_after = True

    def _on_failed(self, error: object) -> None:
        self._verify_status.setText(str(error))

    def _on_finished(self) -> None:
        if self._refresh_after:
            self._refresh_after = False
            self._refresh()

    def _show_rows(self, choices: List[str], rows: List[Dict[str, Any]]) -> None:
        self._sync_event_type_dropdown(choices)
        self._table.setRowCount(len(rows))
        for row_index, entry in enumerate(rows):
            for col_index, text in enumerate(_format_row(entry)):
                self._table.setItem(
                    row_index, col_index, QTableWidgetItem(text),
                )

    def _sync_event_type_dropdown(self, choices: List[str]) -> None:
        current = self._type_filter.currentText()
        self._type_filter.blockSignals(True)
        self._type_filter.clear()
        self._type_filter.addItems(choices)
        # Restore previous selection if still valid; otherwise default
        # to the all-sentinel.
        if current and current in choices:
            self._type_filter.setCurrentText(current)
        else:
            self._type_filter.setCurrentIndex(0)
        self._type_filter.blockSignals(False)

    def _current_event_type_filter(self) -> Optional[str]:
        text = self._type_filter.currentText().strip()
        if not text or text == _ALL_SENTINEL:
            return None
        return text

    def _verify(self) -> None:
        if self._start("AC_audit_log_verify", "verify", _verify_work):
            self._verify_status.setText(_t("task_running"))

    def _show_verified(self, result: Any) -> None:
        if result.ok:
            self._verify_status.setText(
                _t("audit_verify_ok").format(total=result.total_rows)
            )
        else:
            self._verify_status.setText(
                _t("audit_verify_broken").format(
                    row_id=result.broken_at_id, total=result.total_rows,
                )
            )

    def _clear(self) -> None:
        if not self._refusal.allows("AC_audit_log_clear"):
            return
        confirm = QMessageBox.question(
            self, _t("audit_clear"), _t("audit_clear_confirm"),
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self._start("AC_audit_log_clear", "clear", _clear_work)

    def _apply_table_headers(self) -> None:
        self._table.setHorizontalHeaderLabels([
            _t("audit_col_ts"), _t("audit_col_type"),
            _t("audit_col_host"), _t("audit_col_viewer"),
            _t("audit_col_detail"),
        ])


def _format_row(entry: Dict[str, Any]) -> List[str]:
    ts = entry.get("ts", "")
    try:
        ts = datetime.fromisoformat(ts).astimezone().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except (TypeError, ValueError):
        pass
    return [
        ts,
        entry.get("event_type", ""),
        (entry.get("host_id") or "")[:32],
        (entry.get("viewer_id") or "")[:32],
        entry.get("detail") or "",
    ]


__all__ = ["AuditLogTab"]
