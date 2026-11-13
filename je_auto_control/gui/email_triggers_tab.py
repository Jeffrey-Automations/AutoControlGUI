"""Email Triggers tab: bind IMAP mailboxes to action scripts."""
from typing import Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFileDialog, QGroupBox,
    QHeaderView, QLabel, QLineEdit, QMessageBox,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from je_auto_control.gui._dispose import release_resources
from je_auto_control.gui._i18n_helpers import TranslatableMixin
from je_auto_control.gui._slow_op import SlowOp
from je_auto_control.gui.adaptive.flow_layout import field_pair, flow_of
from je_auto_control.gui.adaptive.surfaces import Card, set_role
from je_auto_control.gui._worker_thread import CallWorker, WorkerHandle, start_worker
from je_auto_control.gui.language_wrapper.multi_language_wrapper import (
    language_wrapper,
)
from je_auto_control.utils.triggers.email_trigger import (
    default_email_trigger_watcher,
)


_REFRESH_MS = 1500


def _t(key: str) -> str:
    return language_wrapper.translate(key, key)


class EmailTriggersTab(TranslatableMixin, QWidget):
    """GUI front-end for :data:`default_email_trigger_watcher`."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tr_init()
        self._poll_thread: Optional[WorkerHandle] = None
        self._host_input = QLineEdit()
        self._host_input.setPlaceholderText("imap.example.com")
        self._port_input = QSpinBox()
        self._port_input.setRange(0, 65535)
        self._port_input.setValue(993)
        self._user_input = QLineEdit()
        self._user_input.setPlaceholderText("user@example.com")
        self._password_input = QLineEdit()
        self._password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._tr(self._password_input, "eml_password_placeholder", "setPlaceholderText")
        self._mailbox_input = QLineEdit("INBOX")
        self._search_input = QLineEdit("UNSEEN")
        self._poll_input = QSpinBox()
        self._poll_input.setRange(5, 86_400)
        self._poll_input.setValue(60)
        self._script_input = QLineEdit()
        self._ssl_check = self._tr(QCheckBox(), "eml_ssl")
        self._ssl_check.setChecked(True)
        self._mark_seen_check = self._tr(QCheckBox(), "eml_mark_seen")
        self._mark_seen_check.setChecked(True)
        self._status_label = QLabel()
        self._watcher_op = SlowOp(self)
        self._table = QTableWidget(0, 7)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive,
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        self._apply_table_headers()
        self._build_layout()
        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._refresh()

    def dispose(self) -> None:
        """Release what the tab holds beyond its widgets: its refresh timer (the watcher itself keeps running).

        Called by ``close_tab(key, release=True)`` before the widget is deleted; safe to call twice.
        """
        release_resources(self)

    def retranslate(self) -> None:
        TranslatableMixin.retranslate(self)
        self._apply_table_headers()
        self._refresh()

    def _apply_table_headers(self) -> None:
        self._table.setHorizontalHeaderLabels([
            _t("eml_col_id"), _t("eml_col_host"), _t("eml_col_user"),
            _t("eml_col_mailbox"), _t("eml_col_script"),
            _t("eml_col_fired"), _t("eml_col_error"),
        ])

    def _build_layout(self) -> None:
        # Start/stop/poll/browse/register/remove commands run from the
        # Actions menu; the tab keeps only the inputs, the table, and the
        # status line.
        root = QVBoxLayout(self)
        root.setSpacing(12)

        engine_box = self._tr(QGroupBox(), "eml_engine_group")
        engine_layout = QVBoxLayout(engine_box)
        self._status_label.setWordWrap(True)
        set_role(self._status_label, "hint")
        engine_layout.addWidget(self._status_label)
        root.addWidget(engine_box)

        add_box = self._tr(QGroupBox(), "eml_add_group")
        add_layout = QVBoxLayout(add_box)
        rows = (
            (self._pair("eml_host_label", self._host_input, 280),
             self._pair("eml_port_label", self._port_input), self._ssl_check),
            (self._pair("eml_user_label", self._user_input, 280),
             self._pair("eml_password_label", self._password_input, 280)),
            (self._pair("eml_mailbox_label", self._mailbox_input),
             self._pair("eml_search_label", self._search_input)),
            (self._pair("eml_poll_label", self._poll_input), self._mark_seen_check),
        )
        for row in rows:
            add_layout.addLayout(flow_of(*row))
        add_layout.addWidget(self._pair("eml_script_label", self._script_input))
        root.addWidget(add_box)

        root.addWidget(Card().add(self._table, stretch=1), stretch=1)

    def _pair(self, label_key: str, field: QWidget, min_width: int = 0) -> QWidget:
        """``field`` with its translated label kept beside it, at least ``min_width`` pixels wide."""
        pair = field_pair(self._tr(QLabel(), label_key), field)
        pair.setMinimumWidth(min_width)
        return pair

    def menu_actions(self) -> list:
        """Expose tab commands to the window-level Actions menu."""
        return [
            ("eml_start", self._on_start),
            ("eml_stop", self._on_stop),
            ("eml_poll_now", self._on_poll_now),
            ("eml_browse", self._on_browse),
            ("eml_register", self._on_register),
            ("eml_remove", self._on_remove),
        ]

    def _on_start(self) -> None:
        if self._watcher_op.busy:       # still stopping: starting now would race the join
            return
        default_email_trigger_watcher.start()
        self._refresh()

    def _on_stop(self) -> None:
        # stop() joins the poll thread for up to 5 s (an IMAP round in
        # flight), which used to hold the GUI thread; a second Stop is ignored.
        if self._watcher_op.run(default_email_trigger_watcher.stop, on_done=self._on_watcher_stopped,
                                on_error=self._on_watcher_stopped):
            self._refresh()

    def _on_watcher_stopped(self, _outcome: object = None) -> None:
        self._refresh()

    def _on_poll_now(self) -> None:
        # Off the GUI thread: an IMAP server that never greets froze the
        # window for the full 30 s socket timeout.
        if self._poll_thread is not None:
            return
        self._poll_thread = start_worker(
            self, CallWorker(default_email_trigger_watcher.poll_once),
            on_done=self._on_polled, on_fail=self._on_poll_failed,
            on_thread_done=self._on_poll_thread_done)

    def _on_polled(self, fired: int) -> None:
        # Per-trigger errors too: a timeout was reported as "Fired 0".
        errors = [f"{trigger.trigger_id}: {trigger.last_error}"
                  for trigger in default_email_trigger_watcher.list_triggers()
                  if getattr(trigger, "last_error", None)]
        text = _t("eml_poll_done").replace("{n}", str(fired))
        QMessageBox.information(self, _t("eml_poll_now"), "\n".join([text, *errors]))
        self._refresh()

    def _on_poll_failed(self, message: str) -> None:
        QMessageBox.warning(self, _t("eml_poll_now"), message)

    def _on_poll_thread_done(self) -> None:
        self._poll_thread = None

    def _on_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, _t("eml_browse"), "", "JSON (*.json)",
        )
        if path:
            self._script_input.setText(path)

    def _on_register(self) -> None:
        host = self._host_input.text().strip()
        user = self._user_input.text().strip()
        password = self._password_input.text()
        script = self._script_input.text().strip()
        if not host or not user or not password or not script:
            QMessageBox.warning(self, _t("eml_register"),
                                _t("eml_required_fields"))
            return
        try:
            default_email_trigger_watcher.add(
                host=host, username=user, password=password,
                script_path=script,
                port=int(self._port_input.value()),
                use_ssl=self._ssl_check.isChecked(),
                mailbox=self._mailbox_input.text().strip() or "INBOX",
                search_criteria=self._search_input.text().strip() or "UNSEEN",
                mark_seen=self._mark_seen_check.isChecked(),
                poll_seconds=float(self._poll_input.value()),
            )
        except ValueError as error:
            QMessageBox.warning(self, _t("eml_register"), str(error))
            return
        self._password_input.clear()
        self._refresh()

    def _on_remove(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        item = self._table.item(row, 0)
        if item is None:
            return
        default_email_trigger_watcher.remove(item.text())
        self._refresh()

    def _refresh(self) -> None:
        if self._watcher_op.busy:
            self._status_label.setText(_t("gui_op_stopping"))
        else:
            running = default_email_trigger_watcher.is_running
            self._status_label.setText(_t("eml_running") if running else _t("eml_stopped"))
        rows = default_email_trigger_watcher.list_triggers()
        self._table.setRowCount(len(rows))
        for row, trigger in enumerate(rows):
            values = (
                trigger.trigger_id,
                f"{trigger.host}:{trigger.port}",
                trigger.username,
                trigger.mailbox,
                trigger.script_path,
                str(trigger.fired),
                trigger.last_error or "",
            )
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row, col, item)
