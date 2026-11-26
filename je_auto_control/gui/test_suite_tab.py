"""Test Suites tab: run a QA suite spec and manage flaky quarantine.

Thin wrapper over :func:`je_auto_control.run_suite`, the JUnit/Allure
report writers, and the quarantine store. Holds no business logic. A suite
runs off the GUI thread as a stoppable executor run, one at a time. Loading a
spec and writing a report are a tab task of their own, and so is every
quarantine change (a locked JSON file, read back after each change).
"""
import functools
import json
from typing import Any, Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QLabel, QListWidget,
    QPlainTextEdit, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from je_auto_control.gui._dispose import release_resources
from je_auto_control.gui._i18n_helpers import TranslatableMixin
from je_auto_control.gui._tab_task import TabTask, was_stopped
from je_auto_control.gui.adaptive.responsive import ResponsiveBox
from je_auto_control.gui.adaptive.surfaces import Card, set_role
from je_auto_control.gui.language_wrapper.multi_language_wrapper import (
    language_wrapper,
)
import je_auto_control as ac
from je_auto_control.utils.quarantine import (
    auto_quarantine_from_flakiness, default_quarantine_store,
)
from je_auto_control.utils.test_suite import TestSuiteResult

_COLS = ("suite_col_case", "suite_col_status", "suite_col_time",
         "suite_col_message")


def _t(key: str) -> str:
    return language_wrapper.translate(key, key)


def _run_suite(spec: Any) -> Any:
    """Worker thread: run one suite spec."""
    return ac.run_suite(spec)


def _read_spec(path: str) -> str:
    """Worker thread: the text of a suite spec file (``ValueError`` when it is not UTF-8)."""
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _change_quarantine(change: Optional[Callable[[], Any]]) -> list:
    """Worker thread: make ``change`` to the quarantine store (when given), then list it."""
    if change is not None:
        change()
    return list(default_quarantine_store().list())


def _release(name: str) -> None:
    """Worker thread: take one case out of quarantine."""
    default_quarantine_store().remove(name)


def _clear_quarantine() -> None:
    """Worker thread: empty the quarantine."""
    default_quarantine_store().clear()


class TestSuiteTab(TranslatableMixin, QWidget):
    """Run suites, render scored cases, and manage the quarantine list."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tr_init()
        self._spec = QPlainTextEdit()
        self._spec.setPlaceholderText(
            '{"name": "Demo", "cases": [{"name": "c1", "actions": []}]}',
        )
        self._table = QTableWidget(0, len(_COLS))
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._summary = QLabel()
        self._quarantine = QListWidget()
        self._last_result: Optional[Any] = None
        self._runs = TabTask(self)
        self._runs.result.connect(self._show_run_result)
        self._runs.error.connect(self._show_run_error)
        self._files = TabTask(self)         # loading a spec, writing a report
        self._files.result.connect(self._on_file_done)
        self._files.error.connect(self._show_run_error)
        self._store = TabTask(self, details=False)      # the quarantine store: change, then list
        self._store.result.connect(self._show_quarantine)
        self._store.error.connect(self._show_run_error)
        self._apply_headers()
        self._build_layout()
        self._refresh_quarantine()

    def retranslate(self) -> None:
        TranslatableMixin.retranslate(self)
        self._apply_headers()

    def _apply_headers(self) -> None:
        self._table.setHorizontalHeaderLabels([_t(k) for k in _COLS])

    def _build_layout(self) -> None:
        # Load/run/export and quarantine commands run from the Actions
        # menu; the tab keeps only the spec editor, tables, and summary.
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.addWidget(Card("suite_spec_label").add(self._spec, stretch=1), stretch=1)
        self._summary.setWordWrap(True)
        set_role(self._summary, "hint")
        results = Card().add(self._table, stretch=1).add(self._summary)
        quarantine = Card("suite_q_label").add(self._quarantine, stretch=1)
        root.addWidget(ResponsiveBox(results, quarantine, stretches=(2, 1)), stretch=2)

    def dispose(self) -> None:
        """Release what the tab holds beyond its widgets: the command still running in the background.

        A script run is stopped; other work cannot be interrupted, so it runs to its end and its
        result is dropped. Called by ``close_tab(key, release=True)``; safe to call twice.
        """
        release_resources(self)

    def menu_actions(self) -> list[tuple[str, Callable[[], None]]]:
        """Expose tab commands to the window-level Actions menu."""
        return [
            ("suite_load_file", self._on_load_file),
            ("suite_run", self._on_run),
            ("task_stop", self._on_stop),
            ("suite_junit", self._on_junit),
            ("suite_allure", self._on_allure),
            ("suite_q_auto", self._on_auto_quarantine),
            ("suite_q_remove", self._on_release_selected),
            ("suite_q_clear", self._on_clear_quarantine),
        ]

    def _parse_spec(self) -> Any:
        return json.loads(self._spec.toPlainText() or "{}")

    def _on_load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, _t("suite_load_file"))
        if path:
            # A non-UTF-8 or unreadable file is shown as an error once the read reports.
            self._start_file(functools.partial(_read_spec, path), "load")

    def _start_file(self, work: Callable[[], Any], tag: str) -> None:
        if not self._files.start(work, tag=tag):
            self._summary.setText(_t("task_busy"))
            return
        self._summary.setText(_t("task_running"))

    def _on_file_done(self, result: Any) -> None:
        if self._files.tag == "load":
            self._spec.setPlainText(result)
            self._summary.setText("")
        elif self._last_result is not None:
            self._render_result(self._last_result)      # the summary again, in place of "running"

    def _on_run(self) -> None:
        try:
            spec = self._parse_spec()
        except (ValueError, TypeError) as err:
            self._summary.setText(_t("suite_error").replace("{error}", str(err)))
            return
        if not self._runs.start_script(functools.partial(_run_suite, spec)):
            self._summary.setText(_t("task_busy"))
            return
        self._summary.setText(_t("task_running"))

    def _on_stop(self) -> None:
        if self._runs.stop():
            self._summary.setText(_t("task_stopping"))

    def _show_run_result(self, result: Any) -> None:
        self._last_result = result
        self._render_result(result)

    def _show_run_error(self, error: object) -> None:
        if was_stopped(error):
            self._summary.setText(_t("task_stopped"))
            return
        self._summary.setText(_t("suite_error").replace("{error}", str(error)))

    def _render_result(self, result: TestSuiteResult) -> None:
        self._table.setRowCount(len(result.cases))
        for row, case in enumerate(result.cases):
            values = (case.name, case.status, f"{case.duration_s:.3f}s",
                      case.message)
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row, col, item)
        self._summary.setText(
            _t("suite_summary")
            .replace("{passed}", str(result.passed))
            .replace("{failed}", str(result.failed))
            .replace("{errored}", str(result.errored))
            .replace("{skipped}", str(result.skipped)),
        )

    def _on_junit(self) -> None:
        if self._last_result is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, _t("suite_junit"),
                                              "junit.xml")
        if path:
            self._export(functools.partial(ac.write_junit_xml, self._last_result, path))

    def _on_allure(self) -> None:
        if self._last_result is None:
            return
        directory = QFileDialog.getExistingDirectory(self, _t("suite_allure"))
        if directory:
            self._export(functools.partial(ac.write_allure_results, self._last_result, directory))

    def _export(self, write: Callable[[], Any]) -> None:
        """Write one report off the GUI thread; a target that cannot be written is shown in the summary."""
        self._start_file(write, "export")

    def _refresh_quarantine(self, change: Optional[Callable[[], Any]] = None) -> None:
        """Make ``change`` to the quarantine (when given) and list it again, off the GUI thread."""
        if not self._store.start(functools.partial(_change_quarantine, change)):
            self._summary.setText(_t("task_busy"))

    def _show_quarantine(self, entries: list) -> None:
        self._quarantine.clear()
        for entry in entries:
            label = entry.name
            if entry.reason:
                label += f"  ({entry.reason})"
            self._quarantine.addItem(label)

    def _on_auto_quarantine(self) -> None:
        self._refresh_quarantine(auto_quarantine_from_flakiness)

    def _on_release_selected(self) -> None:
        item = self._quarantine.currentItem()
        if item is not None:
            self._refresh_quarantine(functools.partial(_release, item.text().split("  (")[0]))

    def _on_clear_quarantine(self) -> None:
        self._refresh_quarantine(_clear_quarantine)
