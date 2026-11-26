"""Run History tab: browse recorded runs, artifacts and explicit journal links.

The history is a SQLite store polled every two seconds, and the preview is a
screenshot decoded from disk: the query, the clear, the journal lookup and the
image decode all run as tab tasks, and the GUI thread only paints what they
return. A refresh asked for while a query is still out runs once it reports.
"""
import datetime as _dt
import functools
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices, QImage, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QHeaderView, QLabel,
    QMessageBox, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from je_auto_control.gui._authorize import authorized
from je_auto_control.gui._dispose import release_resources
from je_auto_control.gui._i18n_helpers import TranslatableMixin
from je_auto_control.gui._tab_task import TabTask
from je_auto_control.gui._qt_typed import kept_selection
from je_auto_control.gui.adaptive.flow_layout import field_pair, flow_of
from je_auto_control.gui.adaptive.responsive import ResponsiveSplitter
from je_auto_control.gui.adaptive.surfaces import Card, set_role
from je_auto_control.gui.language_wrapper.multi_language_wrapper import (
    language_wrapper,
)
from je_auto_control.gui.run_history_timeline import RunHistoryTimeline
from je_auto_control.gui.journal_browser import JournalBrowser
from je_auto_control.utils.exception.exceptions import AutoControlException
from je_auto_control.utils.rbac.policy import authorize_command
from je_auto_control.utils.run_history.history_store import (
    SOURCE_HOTKEY, SOURCE_MANUAL, SOURCE_REST, SOURCE_SCHEDULER,
    SOURCE_TRIGGER, STATUS_ERROR, STATUS_OK, STATUS_RUNNING, RunRecord,
    default_history_store,
)

_COLUMN_COUNT = 8
_REFRESH_INTERVAL_MS = 2000
#: The preview is decoded at most this size, so painting it again on a resize stays cheap.
_PREVIEW_BOUND = (1024, 768)
_SOURCES = (
    ("rh_source_all", None),
    ("rh_source_scheduler", SOURCE_SCHEDULER),
    ("rh_source_trigger", SOURCE_TRIGGER),
    ("rh_source_hotkey", SOURCE_HOTKEY),
    ("rh_source_manual", SOURCE_MANUAL),
    ("rh_source_rest", SOURCE_REST),
)
_STATUS_LABEL_KEYS = {
    STATUS_OK: "rh_status_ok",
    STATUS_ERROR: "rh_status_error",
    STATUS_RUNNING: "rh_status_running",
}


def _t(key: str) -> str:
    return language_wrapper.translate(key, key)


def _format_time(epoch: float) -> str:
    try:
        return _dt.datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, ValueError, OverflowError):
        return str(epoch)


def _format_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "-"
    if seconds < 1.0:
        return f"{int(seconds * 1000)} ms"
    return f"{seconds:.2f} s"


def _list_runs(source: Optional[str]) -> List[RunRecord]:
    """Worker thread: the newest 500 runs, of ``source`` only when one is given."""
    try:
        return default_history_store.list_runs(limit=500, source_type=source)
    except ValueError:
        return []


def _decode_preview(path: str) -> Tuple[str, QImage]:
    """Worker thread: the screenshot at ``path``, bounded to ``_PREVIEW_BOUND`` (null when it does not decode)."""
    image = QImage(path)
    if not image.isNull() and (image.width() > _PREVIEW_BOUND[0] or image.height() > _PREVIEW_BOUND[1]):
        image = image.scaled(*_PREVIEW_BOUND, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
    return path, image


class RunHistoryTab(TranslatableMixin, QWidget):
    """Timeline and read-only journal inspection for recorded execution owners."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tr_init()
        self._records: List[RunRecord] = []
        self._filter = QComboBox()
        self._populate_filter()
        self._filter.currentIndexChanged.connect(self._refresh)
        self._table = QTableWidget(0, _COLUMN_COUNT)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._apply_table_headers()
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        self._count_label = QLabel()
        self._count_text = self._keyed(self._count_label)
        self._timeline = RunHistoryTimeline()
        self._timeline.run_clicked.connect(self._on_timeline_clicked)
        self._thumb_label = QLabel()
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_label.setMinimumSize(220, 160)
        self._thumb_label.setFrameShape(QFrame.Shape.StyledPanel)
        self._thumb_label.setScaledContents(False)
        self._thumb_caption = QLabel()
        self._thumb_caption.setWordWrap(True)
        self._thumb_caption.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._thumb_caption.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_INTERVAL_MS)
        self._timer.timeout.connect(self._refresh)
        self._auto_refresh = True
        self._queries = TabTask(self, details=False)       # the history query (also on every timer tick)
        self._queries.result.connect(self._show_runs)
        self._queries.finished.connect(self._query_settled)
        self._requery = False
        self._queried_source: Optional[str] = None         # the filter the query still out was made for
        self._edits = TabTask(self)                        # clear, journal lookup
        self._edits.result.connect(self._on_edit_done)
        self._edits.error.connect(self._on_edit_failed)
        self._images = TabTask(self, details=False)        # decoding the selected run's screenshot
        self._images.result.connect(self._on_preview_decoded)
        self._preview_path: Optional[str] = None           # the path _preview_image holds
        self._preview_image: Optional[QImage] = None
        self._journal = JournalBrowser(self)
        self._build_layout()
        self._refresh()
        self._timer.start()

    def retranslate(self) -> None:
        TranslatableMixin.retranslate(self)
        self._apply_table_headers()
        self._repopulate_filter_labels()
        self._render_runs()             # the rows already listed, in the new language: no new query
        self._refresh_preview()
        self._journal.retranslate()
    def dispose(self) -> None:
        """Stop the refresh timer, the queries and any journal read; the registry calls it before deleting the tab."""
        self._journal.cancel()
        release_resources(self)

    # pylint: disable-next=invalid-name  # reason: Qt override
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802  # reason: Qt override
        """Stop journal reads immediately when the history page closes."""
        self.dispose()
        super().closeEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._refresh_preview()

    def _populate_filter(self) -> None:
        self._filter.blockSignals(True)
        for label_key, source_value in _SOURCES:
            self._filter.addItem(_t(label_key), source_value)
        self._filter.blockSignals(False)

    def _repopulate_filter_labels(self) -> None:
        self._filter.blockSignals(True)
        current = self._filter.currentIndex()
        for row, (label_key, _source) in enumerate(_SOURCES):
            self._filter.setItemText(row, _t(label_key))
        self._filter.setCurrentIndex(max(0, current))
        self._filter.blockSignals(False)

    def _apply_table_headers(self) -> None:
        self._table.setHorizontalHeaderLabels([
            _t("rh_col_id"), _t("rh_col_source"), _t("rh_col_target"),
            _t("rh_col_script"), _t("rh_col_started"),
            _t("rh_col_duration"), _t("rh_col_status"),
            _t("rh_col_artifact"),
        ])

    def _build_layout(self) -> None:
        # Refresh/clear/open-artifact commands run from the Actions menu;
        # the tab keeps only the filter, timeline, table, and preview.
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.addWidget(Card().add(flow_of(field_pair(self._tr(QLabel(), "rh_filter_label"), self._filter))))

        timeline_label = set_role(self._tr(QLabel(), "rh_timeline_heading"), "sectionTitle")
        root.addWidget(Card().add(timeline_label).add(self._timeline))

        preview = Card().add(set_role(self._tr(QLabel(), "rh_preview_heading"), "sectionTitle"))
        preview.add(self._thumb_label, stretch=1).add(self._thumb_caption)
        # Stacked under a narrow window the table would otherwise shrink to its header.
        self._table.setMinimumHeight(200)
        runs = ResponsiveSplitter(Card().add(self._table, stretch=1), preview, stretches=(3, 1))
        # The journal browser is shared with Self-Healing; tag it so it shows the card behind it.
        self._journal.setProperty("role", "bare")
        sections = QSplitter(Qt.Orientation.Vertical)
        sections.addWidget(runs)
        sections.addWidget(Card().add(self._journal, stretch=1))
        sections.setStretchFactor(0, 1)
        sections.setStretchFactor(1, 1)
        root.addWidget(sections, stretch=1)

        self._table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._count_label.setWordWrap(True)
        set_role(self._count_label, "hint")
        root.addWidget(self._count_label)

    def menu_actions(self) -> List[Tuple[str, Callable[[], None]]]:
        """Expose tab commands to the window-level Actions menu."""
        return [
            ("rh_refresh", self._refresh),
            ("rh_clear", self._on_clear),
            ("rh_open_artifact", self._open_selected_artifact),
            ("journal_selected_run", self._selected_journals),
        ] + self._journal.menu_actions()

    def _selected_journals(self) -> None:
        try:
            authorize_command("AC_journal_read")
        except AutoControlException as error:
            self._journal.report_error(str(error))
            return
        record = self._selected_record()
        if record is None:
            self._journal.set_links([])
            return
        work = functools.partial(authorized, "AC_journal_read", default_history_store.journals_for_run, record.id)
        if not self._edits.start(work, tag="journals"):
            self._journal.report_error(_t("task_busy"))

    def _on_clear(self) -> None:
        reply = QMessageBox.question(
            self, _t("rh_clear"), _t("rh_confirm_clear"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes and not self._edits.start(default_history_store.clear,
                                                                              tag="clear"):
            self._count_text.show("task_busy")

    def _on_edit_done(self, result: object) -> None:
        if self._edits.tag == "journals":
            self._journal.set_links(result)  # type: ignore[arg-type]  # reason: journals_for_run returns the links
        else:
            self._refresh()

    def _on_edit_failed(self, error: object) -> None:
        if self._edits.tag == "journals":
            self._journal.report_error(str(error))
        else:
            QMessageBox.warning(self, _t("rh_clear"), str(error))

    def _refresh(self) -> None:
        """Query the history off the GUI thread; asked again while one is out, it runs once that reports."""
        source = self._filter.currentData()
        if self._queries.start(functools.partial(_list_runs, source)):
            self._queried_source = source
        else:
            self._requery = True

    def _query_settled(self) -> None:
        if self._requery:
            self._requery = False
            self._refresh()

    def _show_runs(self, runs: List[RunRecord]) -> None:
        if self._queried_source != self._filter.currentData():
            return                  # the filter changed meanwhile: the next query answers for it
        self._records = runs
        self._render_runs()
        self._timeline.set_records(runs)
        self._refresh_preview()

    def _render_runs(self) -> None:
        with kept_selection(self._table):       # newest first: each new run moves every row down
            self._table.setRowCount(len(self._records))
            for row, record in enumerate(self._records):
                self._set_row(row, record)
        self._count_text.show("rh_count_label", n=len(self._records))

    def _set_row(self, row: int, record: RunRecord) -> None:
        status_key = _STATUS_LABEL_KEYS.get(record.status, record.status)
        status_text = _t(status_key) if record.error_text is None \
            else f"{_t(status_key)}: {record.error_text}"
        artifact_text = record.artifact_path or "-"
        values = (
            str(record.id),
            record.source_type,
            record.source_id,
            record.script_path,
            _format_time(record.started_at),
            _format_duration(record.duration_seconds),
            status_text,
            artifact_text,
        )
        for col, text in enumerate(values):
            item = QTableWidgetItem(text)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, col, item)

    def _selected_record(self) -> Optional[RunRecord]:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._records):
            return None
        return self._records[row]

    def _on_selection_changed(self) -> None:
        record = self._selected_record()
        self._timeline.set_highlighted(record.id if record is not None else None)
        self._refresh_preview()

    def _on_timeline_clicked(self, run_id: int) -> None:
        for row, record in enumerate(self._records):
            if record.id == run_id:
                self._table.selectRow(row)
                return

    def _refresh_preview(self) -> None:
        record = self._selected_record()
        if record is None:
            self._thumb_label.clear()
            self._thumb_label.setText(_t("rh_preview_empty"))
            self._thumb_caption.setText("")
            return
        self._paint_preview(record.artifact_path)
        caption = (
            f"#{record.id} • {record.source_type}/{record.source_id}\n"
            f"{record.script_path}\n"
            f"{_format_time(record.started_at)} • "
            f"{_format_duration(record.duration_seconds)}"
        )
        if record.error_text:
            caption += f"\n{record.error_text}"
        self._thumb_caption.setText(caption)

    def _paint_preview(self, path: Optional[str]) -> None:
        """Paint the screenshot at ``path``: from the decoded copy, or once a worker has decoded it."""
        if not path:
            self._thumb_label.clear()
            self._thumb_label.setText(_t("rh_preview_no_artifact"))
            return
        if path != self._preview_path:
            self._images.start(functools.partial(_decode_preview, path))    # one out at a time
            return
        if self._preview_image is None or self._preview_image.isNull():
            self._thumb_label.clear()
            self._thumb_label.setText(_t("rh_artifact_missing"))
            return
        self._thumb_label.setPixmap(QPixmap.fromImage(self._preview_image.scaled(
            self._thumb_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )))

    def _on_preview_decoded(self, decoded: Tuple[str, QImage]) -> None:
        self._preview_path, self._preview_image = decoded
        record = self._selected_record()
        if record is not None:
            self._paint_preview(record.artifact_path)

    def _selected_artifact_path(self) -> Optional[str]:
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, _COLUMN_COUNT - 1)
        if item is None:
            return None
        text = item.text()
        if not text or text == "-":
            return None
        return text

    def _open_selected_artifact(self) -> None:
        path = self._selected_artifact_path()
        if path is None:
            QMessageBox.information(
                self, _t("rh_open_artifact"), _t("rh_no_artifact"),
            )
            return
        self._open_path(path)

    def _on_cell_double_clicked(self, row: int, column: int) -> None:
        if column != _COLUMN_COUNT - 1:
            return
        item = self._table.item(row, column)
        if item is None:
            return
        text = item.text()
        if text and text != "-":
            self._open_path(text)

    def _open_path(self, path: str) -> None:
        resolved = Path(path)
        if not resolved.exists():
            QMessageBox.warning(
                self, _t("rh_open_artifact"), _t("rh_artifact_missing"),
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(resolved)))
