"""Data Sources tab: preview rows loaded by the headless data-source layer.

Thin wrapper over :func:`je_auto_control.load_rows` — the widget only
builds a source spec dict from the form and renders the returned rows.
Reading a file or querying a database runs as a
:class:`~je_auto_control.gui._tab_task.TabTask`, one load at a time.
"""
import functools
import json
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from je_auto_control.gui._dispose import release_resources
from je_auto_control.gui._i18n_helpers import TranslatableMixin
from je_auto_control.gui._tab_task import TabTask
from je_auto_control.gui.adaptive.flow_layout import field_pair, flow_of
from je_auto_control.gui.adaptive.surfaces import Card, set_role
from je_auto_control.gui.language_wrapper.multi_language_wrapper import (
    language_wrapper,
)
from je_auto_control.utils.data_source import data_source_kinds, load_rows


def _t(key: str) -> str:
    return language_wrapper.translate(key, key)


class DataSourceTab(TranslatableMixin, QWidget):
    """Build a data-source spec, load rows, and show them in a table."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tr_init()
        self._kind = QComboBox()
        self._kind.addItems(data_source_kinds())
        self._kind.currentTextChanged.connect(self._sync_visibility)
        self._path = QLineEdit()
        self._query = QLineEdit()
        self._inline = QPlainTextEdit()
        self._inline.setPlaceholderText('[{"user": "alice"}, {"user": "bob"}]')
        self._limit = QSpinBox()
        self._limit.setRange(0, 100000)
        self._table = QTableWidget(0, 0)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._status = QLabel()
        self._status_text = self._keyed(self._status)
        self._loads = TabTask(self)         # reading the file or querying the database
        self._loads.result.connect(self._on_loaded)
        self._loads.error.connect(self._show_error)
        self._build_layout()
        self._sync_visibility(self._kind.currentText())

    def dispose(self) -> None:
        """Cancel a load still out; its rows are dropped. Safe to call twice."""
        release_resources(self)

    def _build_layout(self) -> None:
        # The load command runs from the Actions menu; the tab keeps the
        # source form (with its kind-synced browse button) and the table.
        root = QVBoxLayout(self)
        root.setSpacing(12)
        source = Card().add(flow_of(field_pair(self._tr(QLabel(), "ds_kind"), self._kind),
                                    field_pair(self._tr(QLabel(), "ds_limit"), self._limit)))

        # The rows of the other kinds hide; they go in as layouts, not
        # containers, so a hidden row leaves no gap behind.
        self._path_row = QHBoxLayout()
        self._path_label = self._tr(QLabel(), "ds_path")
        self._path_row.addWidget(self._path_label)
        self._path_row.addWidget(self._path, stretch=1)
        self._browse_btn = self._tr(QPushButton(), "ds_browse")
        self._browse_btn.clicked.connect(self._on_browse)
        self._path_row.addWidget(self._browse_btn)
        source.add(self._path_row)

        self._query_label = self._tr(QLabel(), "ds_query")
        self._inline_label = self._tr(QLabel(), "ds_inline")
        for widget in (self._query_label, self._query, self._inline_label, self._inline):
            source.add(widget)
        root.addWidget(source)

        root.addWidget(Card().add(self._table, stretch=1), stretch=1)
        self._status.setWordWrap(True)
        set_role(self._status, "hint")
        root.addWidget(self._status)

    def menu_actions(self) -> List[Tuple[str, Callable[[], None]]]:
        """Expose tab commands to the window-level Actions menu."""
        return [
            ("ds_load", self._on_load),
        ]

    def _sync_visibility(self, kind: str) -> None:
        is_file = kind in ("csv", "json", "sqlite", "excel")
        for widget in (self._path_label, self._path, self._browse_btn):
            widget.setVisible(is_file)
        self._query_label.setVisible(kind == "sqlite")
        self._query.setVisible(kind == "sqlite")
        self._inline_label.setVisible(kind == "inline")
        self._inline.setVisible(kind == "inline")

    def _on_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, _t("ds_browse"))
        if path:
            self._path.setText(path)

    def _build_source(self) -> Dict[str, Any]:
        kind = self._kind.currentText()
        if kind == "inline":
            return {"kind": "inline", "rows": json.loads(self._inline.toPlainText() or "[]")}
        source: Dict[str, Any] = {"kind": kind, "path": self._path.text().strip()}
        if kind == "sqlite":
            source["query"] = self._query.text().strip()
        return source

    def _on_load(self) -> None:
        try:
            source = self._build_source()
        except ValueError as error:         # the inline rows are not JSON
            self._show_error(error)
            return
        work = functools.partial(load_rows, source, limit=self._limit.value() or None)
        if not self._loads.start(work):
            self._status_text.show("task_busy")
            return
        self._status_text.show("task_running")

    def _show_error(self, error: object) -> None:
        self._status_text.show("ds_error", error=error)

    def _on_loaded(self, rows: List[Dict[str, Any]]) -> None:
        self._render_rows(rows)
        self._status_text.show("ds_row_count", n=len(rows))

    def _render_rows(self, rows: List[Dict[str, Any]]) -> None:
        columns: List[str] = []
        for row in rows:
            for key in row:
                if key not in columns:
                    columns.append(key)
        self._table.setColumnCount(len(columns))
        self._table.setHorizontalHeaderLabels(columns)
        self._table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, key in enumerate(columns):
                self._table.setItem(
                    r, c, QTableWidgetItem(str(row.get(key, ""))),
                )
