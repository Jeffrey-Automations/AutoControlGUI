"""Diagnostics' view of background stops that failed: what is held, and a retry from the Actions menu.

The rows come from :func:`~je_auto_control.gui._stop_custody.stop_custody`'s
snapshot, which runs nothing and waits on no native lock, so reading it on the
GUI thread is safe. *Retry failed stops* runs every held stop again on a worker,
each under the authority it was queued with; *Forget selected failed stop* lets
go of one without running it.
"""
from __future__ import annotations

import datetime
from typing import Callable, Optional

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from je_auto_control.gui._stop_custody import StopCustody, stop_custody
from je_auto_control.gui._tab_task import TabTask
from je_auto_control.gui.adaptive.surfaces import set_role
from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper

_COLUMNS = ("failed_stops_col_what", "failed_stops_col_error", "failed_stops_col_attempts", "failed_stops_col_at")


def _t(key: str) -> str:
    return language_wrapper.translate(key, key)


class _Relay(QObject):
    """Carries the custody's change notice, made on any thread, to the GUI thread."""

    changed = Signal()


class FailedStopsView(QWidget):
    """The held failed stops, as a table; its commands go to the owning tab's Actions menu."""

    def __init__(self, parent: Optional[QWidget] = None, custody: Optional[StopCustody] = None) -> None:
        super().__init__(parent)
        self._custody = custody if custody is not None else stop_custody()
        self._title = QLabel()
        set_role(self._title, "sectionTitle")
        self._hint = QLabel()
        self._hint.setWordWrap(True)
        set_role(self._hint, "hint")
        self._status = QLabel()
        self._status.setWordWrap(True)
        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for widget in (self._title, self._hint, self._table, self._status):
            layout.addWidget(widget)
        # Retries run every held stop again: off the GUI thread, one round at a time.
        self._retries = TabTask(self, details=False)
        self._retries.result.connect(self._show_retried)
        self._retries.error.connect(self._show_retry_error)
        self._relay = _Relay(self)
        self._relay.changed.connect(self.refresh, Qt.ConnectionType.QueuedConnection)
        remove = self._custody.add_listener(self._relay.changed.emit)
        self.destroyed.connect(lambda *_: remove())    # holds only the removal, never this view
        self.retranslate()

    def menu_actions(self) -> list[tuple[str, Callable[[], None]]]:
        """Retry or forget held stops through the owning tab's Actions menu."""
        return [("failed_stops_retry", self.retry_all), ("failed_stops_forget", self.forget_selected)]

    def retranslate(self) -> None:
        """Re-read the texts and headers in the active language."""
        self._title.setText(_t("failed_stops_title"))
        self._hint.setText(_t("failed_stops_hint"))
        self._table.setHorizontalHeaderLabels([_t(key) for key in _COLUMNS])
        self.refresh()

    def refresh(self) -> None:
        """Show what the custody holds now."""
        rows = self._custody.snapshot()
        self._table.setRowCount(len(rows))
        for row, held in enumerate(rows):
            stamp = datetime.datetime.fromtimestamp(held.failed_at).strftime("%H:%M:%S")
            error = f"{held.error} ({held.detail})" if held.detail else held.error
            for column, text in enumerate((held.label, error, str(held.attempts), stamp)):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, held.stop_id)
                self._table.setItem(row, column, item)

    def retry_all(self) -> None:
        """Run every held stop again on a worker; a second click while one round runs is refused."""
        if not self._custody.snapshot():
            self._status.setText(_t("failed_stops_nothing"))
            return
        if self._retries.start(self._custody.retry_all):
            self._status.setText(_t("failed_stops_retrying"))
        else:
            self._status.setText(_t("task_busy"))

    def forget_selected(self) -> None:
        """Let go of the selected held stop without running it."""
        item = self._table.item(self._table.currentRow(), 0) if self._table.currentRow() >= 0 else None
        stop_id = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if isinstance(stop_id, int) and self._custody.forget(stop_id):
            self._status.setText(_t("failed_stops_forgotten"))
        else:
            self._status.setText(_t("failed_stops_select_first"))

    def _show_retried(self, outcome: object) -> None:
        released, failing = outcome if isinstance(outcome, tuple) else (0, 0)
        self._status.setText(_t("failed_stops_result").format(released=released, failing=failing))
        self.refresh()

    def _show_retry_error(self, error: object) -> None:
        self._status.setText(f"{type(error).__name__}: {error}")
        self.refresh()


__all__ = ["FailedStopsView"]
