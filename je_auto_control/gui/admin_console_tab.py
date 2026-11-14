"""Admin console tab: manage many remote AutoControl REST endpoints.

A broadcast runs as a :class:`~je_auto_control.gui._tab_task.TabTask`. Its
Stop skips the hosts not sent to yet and still shows every host's row, with
``sent`` saying whether the actions went there; closing the tab does the same
skipping and drops the rows.

The health poll and the thumbnail fetch are tasks too, with a deadline and
**Stop polling** in the Actions menu: stopping either, or closing the tab,
skips the hosts not reached yet and drops the answer.
"""
import functools
import json
import threading
from typing import Dict, List, Optional

from PySide6.QtCore import QSize, QTimer, Qt
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QSpinBox, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from je_auto_control.gui._dispose import release_resources
from je_auto_control.gui._i18n_helpers import TranslatableMixin
from je_auto_control.gui._tab_task import TabTask
from je_auto_control.gui.adaptive.flow_layout import field_pair, flow_of
from je_auto_control.gui.adaptive.responsive import ResponsiveBox
from je_auto_control.gui.adaptive.surfaces import Card, set_role
from je_auto_control.gui.language_wrapper.multi_language_wrapper import (
    language_wrapper,
)
from je_auto_control.gui.tab_task_controller import TaskTimeout
from je_auto_control.utils.admin.admin_client import (
    default_admin_console,
)
from je_auto_control.utils.logging.logging_instance import autocontrol_logger

#: How long one poll or thumbnail round may take before the tab gives up on it.
POLL_DEADLINE_S = 60.0


def _t(key: str) -> str:
    return language_wrapper.translate(key, key)


class AdminConsoleTab(TranslatableMixin, QWidget):
    """Thin Qt surface over :class:`AdminConsoleClient`."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tr_init()
        self._client = default_admin_console()
        self._label_input = QLineEdit()
        self._url_input = QLineEdit()
        # Placeholder text only — the operator types the real URL.
        # Default scheme is http to match the bundled local server;
        # production deployments should put TLS in front via a reverse
        # proxy and the operator can paste an https://… URL here.
        self._url_input.setPlaceholderText("http://host:9939")  # NOSONAR python:S5332
        self._token_input = QLineEdit()
        self._token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._table = QTableWidget(0, 5)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents,
        )
        self._actions_input = QTextEdit()
        self._actions_input.setPlaceholderText('[["AC_get_mouse_position"]]')
        self._broadcast_output = QTextEdit()
        self._broadcast_output.setReadOnly(True)
        # Closing the tab, Stop polling or the deadline skip the hosts not reached yet.
        self._polls = TabTask(self)
        self._polls.result.connect(self._apply_poll_result)
        self._polls.error.connect(self._apply_poll_failure)
        self._broadcast_status = QLabel()
        self._broadcast_status.setWordWrap(True)
        set_role(self._broadcast_status, "hint")
        self._broadcasts = TabTask(self)       # one broadcast at a time
        self._broadcasts.result.connect(self._show_broadcast)
        self._broadcasts.error.connect(self._show_broadcast_error)
        self._broadcast_stop: Optional[threading.Event] = None
        # Phase 6.5: live-thumbnail grid + auto-poll timer.
        self._thumbnails = QListWidget()
        self._thumbnails.setViewMode(QListWidget.ViewMode.IconMode)
        self._thumbnails.setIconSize(QSize(200, 150))
        self._thumbnails.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._thumbnails.setMovement(QListWidget.Movement.Static)
        self._thumbnails.setSpacing(10)
        self._thumb_interval = QSpinBox()
        self._thumb_interval.setRange(0, 600)
        self._thumb_interval.setValue(10)
        self._thumb_interval.setSuffix(" s")
        self._thumb_interval.valueChanged.connect(self._on_thumb_interval_changed)
        self._thumb_timer = QTimer(self)
        self._thumb_timer.timeout.connect(self._refresh_thumbnails)
        self._thumbs = TabTask(self, details=False)     # a timer tick, not a run to report
        self._thumbs.result.connect(self._apply_thumbnails)
        self._thumbs.error.connect(self._on_thumbnails_failed)
        self._build_layout()
        self._refresh_table()
        self._apply_thumb_interval()

    def _build_layout(self) -> None:
        # Add/remove/refresh/thumbnail/broadcast commands run from the
        # Actions menu; the tab keeps only the inputs, tables, and output.
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.addWidget(self._build_add_group())
        # Hosts and their thumbnails in one column, the broadcast beside them:
        # side by side the page stays one screen tall; stacked it keeps the old order.
        hosts = QWidget()
        hosts.setProperty("role", "bare")
        column = QVBoxLayout(hosts)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(12)
        column.addWidget(Card().add(self._table, stretch=1), stretch=1)
        column.addWidget(self._build_thumbnails_group(), stretch=1)
        root.addWidget(ResponsiveBox(hosts, self._build_broadcast_group(), stretches=(3, 2)), stretch=1)

    def dispose(self) -> None:
        """Release what the tab holds beyond its widgets: its thumbnail timer, the polls still out and a broadcast.

        A broadcast skips the hosts it has not sent to yet; one already being sent to finishes.

        Called by ``close_tab(key, release=True)`` before the widget is deleted; safe to call twice.
        """
        release_resources(self)

    def menu_actions(self) -> list:
        """Expose tab commands to the window-level Actions menu."""
        return [
            ("admin_add", self._on_add),
            ("admin_remove", self._on_remove),
            ("admin_refresh", self._on_refresh),
            ("admin_poll_stop", self._on_poll_stop),
            ("admin_thumb_refresh_now", self._refresh_thumbnails),
            ("admin_broadcast_run", self._on_broadcast),
            ("admin_broadcast_stop", self._on_broadcast_stop),
        ]

    def _build_thumbnails_group(self) -> QGroupBox:
        group = self._tr(QGroupBox(), "admin_thumb_group")
        layout = QVBoxLayout(group)
        controls = QHBoxLayout()
        controls.addWidget(self._tr(QLabel(), "admin_thumb_interval"))
        controls.addWidget(self._thumb_interval)
        controls.addStretch(1)
        layout.addLayout(controls)
        layout.addWidget(self._thumbnails, stretch=1)
        return group

    def _build_add_group(self) -> QGroupBox:
        group = self._tr(QGroupBox(), "admin_add_group")
        layout = QVBoxLayout(group)
        layout.addLayout(flow_of(*(field_pair(self._tr(QLabel(), key), field) for key, field in (
            ("admin_label", self._label_input), ("admin_url", self._url_input),
            ("admin_token", self._token_input)))))
        return group

    def _build_broadcast_group(self) -> QGroupBox:
        group = self._tr(QGroupBox(), "admin_broadcast_group")
        form = QVBoxLayout(group)
        form.addWidget(self._tr(QLabel(), "admin_actions_label"))
        form.addWidget(self._actions_input)
        form.addWidget(self._tr(QLabel(), "admin_results_label"))
        form.addWidget(self._broadcast_output, stretch=1)
        form.addWidget(self._broadcast_status)
        return group

    def _on_add(self) -> None:
        label = self._label_input.text().strip()
        url = self._url_input.text().strip()
        token = self._token_input.text().strip()
        try:
            self._client.add_host(label=label, base_url=url, token=token)
        except ValueError as error:
            QMessageBox.warning(self, _t("admin_add"), str(error))
            return
        self._label_input.clear()
        self._url_input.clear()
        self._token_input.clear()
        self._refresh_table()

    def _on_remove(self) -> None:
        labels = self._selected_labels()
        if not labels:
            return
        for label in labels:
            self._client.remove_host(label)
        self._refresh_table()

    def _on_refresh(self) -> None:
        self._polls.start(self._client.poll_all, timeout_s=POLL_DEADLINE_S)

    def _on_poll_stop(self) -> None:
        """Cancel the poll and the thumbnail fetch still out; the hosts not reached yet are skipped."""
        self._polls.stop()
        self._thumbs.stop()

    def _on_broadcast(self) -> None:
        text = self._actions_input.toPlainText().strip()
        if not text:
            return
        try:
            actions = json.loads(text)
        except ValueError as error:
            QMessageBox.warning(self, _t("admin_broadcast_run"), str(error))
            return
        # Each host stops at its first failing action and its row says so.
        # Off the GUI thread: every host is an HTTP round trip.
        stop = threading.Event()
        work = functools.partial(self._client.broadcast_execute, actions=actions,
                                 raise_on_error=True, stop_event=stop)
        if not self._broadcasts.start(work):
            self._broadcast_status.setText(_t("task_busy"))
            return
        self._broadcast_stop = stop
        self._broadcast_status.setText(_t("admin_broadcast_running"))

    def _on_broadcast_stop(self) -> None:
        """Skip the hosts not sent to yet; the rows of every host still arrive."""
        if self._broadcast_stop is None or not self._broadcasts.running:
            return
        self._broadcast_stop.set()
        self._broadcast_status.setText(_t("admin_broadcast_stopping"))

    def _show_broadcast(self, results) -> None:
        self._broadcast_stop = None
        self._broadcast_output.setPlainText(
            json.dumps(results, indent=2, ensure_ascii=False, default=str),
        )
        sent = sum(1 for row in results if row.get("sent"))
        self._broadcast_status.setText(_t("admin_broadcast_summary").format(
            sent=sent, total=len(results), skipped=len(results) - sent))

    def _show_broadcast_error(self, error: object) -> None:
        self._broadcast_stop = None
        self._broadcast_output.setPlainText(str(error))
        self._broadcast_status.setText("")

    def _apply_poll_result(self, statuses: list) -> None:
        self._refresh_table(statuses=statuses)

    def _apply_poll_failure(self, error: object) -> None:
        message = _t("task_timed_out") if isinstance(error, TaskTimeout) else str(error)
        QMessageBox.warning(self, _t("admin_refresh"), message)

    # --- live thumbnails (Phase 6.5 GUI) -------------------------------

    def _on_thumb_interval_changed(self, _value: int) -> None:
        self._apply_thumb_interval()

    def _apply_thumb_interval(self) -> None:
        seconds = self._thumb_interval.value()
        if seconds <= 0:
            self._thumb_timer.stop()
            return
        self._thumb_timer.start(seconds * 1000)

    def _refresh_thumbnails(self) -> None:
        # A tick while the previous fetch is still out is skipped.
        self._thumbs.start(self._client.fetch_thumbnails, timeout_s=POLL_DEADLINE_S)

    def _on_thumbnails_failed(self, error: object) -> None:
        # A failed round shows every host as a placeholder, as an empty answer does.
        autocontrol_logger.info("admin: thumbnail round failed: %r", error)
        self._apply_thumbnails({})

    def _apply_thumbnails(self, png_by_label: Dict[str, Optional[bytes]]) -> None:
        """Paint every host as one tile; placeholder when fetch failed."""
        self._thumbnails.clear()
        for label, png in png_by_label.items():
            item = QListWidgetItem(label)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            icon = self._icon_for(png)
            if icon is not None:
                item.setIcon(icon)
            self._thumbnails.addItem(item)

    @staticmethod
    def _icon_for(png: Optional[bytes]) -> Optional[QIcon]:
        if not png:
            return None
        image = QImage.fromData(png, "PNG")  # type: ignore[arg-type]  # reason: the stub says bytes; PySide6 raises ValueError for bytes
        if image.isNull():
            return None
        scaled = image.scaled(
            200, 150, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        return QIcon(QPixmap.fromImage(scaled))

    def _selected_labels(self) -> List[str]:
        rows = sorted({i.row() for i in self._table.selectedIndexes()})
        out: List[str] = []
        for row in rows:
            item = self._table.item(row, 0)
            if item is not None:
                out.append(item.text())
        return out

    def _refresh_table(self, statuses: Optional[list] = None) -> None:
        hosts = self._client.list_hosts()
        status_by_label = {s.label: s for s in (statuses or [])}
        self._table.setRowCount(len(hosts))
        self._table.setHorizontalHeaderLabels([
            _t("admin_col_label"), _t("admin_col_url"),
            _t("admin_col_health"), _t("admin_col_latency"),
            _t("admin_col_jobs"),
        ])
        for row, host in enumerate(hosts):
            self._table.setItem(row, 0, QTableWidgetItem(host.label))
            self._table.setItem(row, 1, QTableWidgetItem(host.base_url))
            status = status_by_label.get(host.label)
            if status is None:
                health_text = "?"
            elif status.healthy:
                health_text = _t("admin_health_ok")
            else:
                health_text = _t("admin_health_down")
            latency_text = "-" if status is None else f"{status.latency_ms:.0f} ms"
            jobs_text = "-" if status is None or status.job_count is None \
                else str(status.job_count)
            self._table.setItem(row, 2, QTableWidgetItem(health_text))
            self._table.setItem(row, 3, QTableWidgetItem(latency_text))
            self._table.setItem(row, 4, QTableWidgetItem(jobs_text))


__all__ = ["AdminConsoleTab"]
