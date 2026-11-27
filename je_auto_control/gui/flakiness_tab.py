"""Flaky Tests tab: rank intermittently-failing scripts from run history.

Thin wrapper over :func:`je_auto_control.analyze_flakiness` — the table
holds no business logic, it only renders the headless report. The report
queries the run-history store, so it is computed as a tab task, one at a time.
"""
import functools
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHeaderView, QLabel,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from je_auto_control.gui._dispose import release_resources
from je_auto_control.gui._i18n_helpers import KeyedText, TranslatableMixin
from je_auto_control.gui._tab_task import TabTask
from je_auto_control.gui.adaptive.flow_layout import field_pair, flow_of
from je_auto_control.gui.adaptive.surfaces import Card, set_role
from je_auto_control.gui.language_wrapper.multi_language_wrapper import (
    language_wrapper,
)
from je_auto_control.utils.flakiness import FlakinessReport, FlakyEntry, analyze_flakiness

_COLUMN_KEYS = (
    "flaky_col_key", "flaky_col_runs", "flaky_col_ok", "flaky_col_error",
    "flaky_col_flips", "flaky_col_flip_rate", "flaky_col_pass_rate",
    "flaky_col_last", "flaky_col_flaky",
)


def _t(key: str) -> str:
    return language_wrapper.translate(key, key)


class FlakinessTab(TranslatableMixin, QWidget):
    """Read-only flakiness leaderboard backed by the run-history store."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tr_init()
        self._table = QTableWidget(0, len(_COLUMN_KEYS))
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive,
        )
        self._limit = QSpinBox()
        self._limit.setRange(1, 100000)
        self._limit.setValue(500)
        self._min_runs = QSpinBox()
        self._min_runs.setRange(1, 1000)
        self._min_runs.setValue(2)
        self._group_by = QComboBox()
        self._group_by.addItems(["script_path", "source_id"])
        self._status = QLabel()
        self._status_text = KeyedText(self._status)
        self._reports = TabTask(self)       # the report queries the run-history store
        self._reports.result.connect(self._show_report)
        self._reports.error.connect(self._show_error)
        self._apply_headers()
        self._build_layout()
        self._refresh()

    def dispose(self) -> None:
        """Drop a report still being computed. Safe to call twice."""
        release_resources(self)

    def retranslate(self) -> None:
        TranslatableMixin.retranslate(self)
        self._apply_headers()
        self._status_text.retranslate()     # not a new query: one may still be running

    def _apply_headers(self) -> None:
        self._table.setHorizontalHeaderLabels([_t(k) for k in _COLUMN_KEYS])

    def _build_layout(self) -> None:
        # The refresh command runs from the Actions menu; the tab keeps
        # only the filter inputs, the table, and the status line.
        root = QVBoxLayout(self)
        root.setSpacing(12)
        filters = flow_of(*(field_pair(self._tr(QLabel(), key), field) for key, field in (
            ("flaky_limit", self._limit), ("flaky_min_runs", self._min_runs), ("flaky_group_by", self._group_by))))
        root.addWidget(Card().add(filters))
        root.addWidget(Card().add(self._table, stretch=1), stretch=1)
        self._status.setWordWrap(True)
        set_role(self._status, "hint")
        root.addWidget(self._status)

    def menu_actions(self) -> list[tuple[str, Callable[[], None]]]:
        """Expose tab commands to the window-level Actions menu."""
        return [
            ("flaky_refresh", self._refresh),
        ]

    def _refresh(self) -> None:
        work = functools.partial(analyze_flakiness, limit=self._limit.value(), min_runs=self._min_runs.value(),
                                 group_by=self._group_by.currentText())
        self._status_text.show("task_running" if self._reports.start(work) else "task_busy")

    def _show_error(self, error: object) -> None:
        self._status_text.show_plain(str(error))

    def _show_report(self, report: FlakinessReport) -> None:
        self._table.setRowCount(len(report.entries))
        for row, entry in enumerate(report.entries):
            self._set_row(row, entry)
        if report.total_groups:
            self._status_text.show("flaky_summary", flaky=report.flaky_count, total=report.total_groups)
        else:
            self._status_text.show("flaky_summary_empty")

    def _set_row(self, row: int, entry: FlakyEntry) -> None:
        values = (
            entry.key, str(entry.total_runs), str(entry.ok),
            str(entry.error), str(entry.flips), f"{entry.flip_rate:.0%}",
            f"{entry.pass_rate:.0%}", entry.last_status,
            "⚠" if entry.flaky else "",
        )
        for col, text in enumerate(values):
            item = QTableWidgetItem(text)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, col, item)
