"""Report-generation panel with independently owned controls and actions."""
from functools import partial
from typing import Callable, Optional

from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QTextEdit, QVBoxLayout, QWidget,
)

from je_auto_control.gui._i18n_helpers import TranslatableMixin
from je_auto_control.gui._tab_task import TabTask
from je_auto_control.gui.adaptive.surfaces import Card, set_role
from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper
from je_auto_control.utils.generate_report.generate_html_report import generate_html_report
from je_auto_control.utils.generate_report.generate_json_report import generate_json_report
from je_auto_control.utils.generate_report.generate_xml_report import generate_xml_report
from je_auto_control.utils.test_record.record_test_class import test_record_instance


class ReportTab(TranslatableMixin, QWidget):
    """Own report inputs and reflect the process-wide recorder without owning it."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tr_init()
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Enable/disable recording and report generation run from the
        # Actions menu; the tab keeps only status, name input, and result.
        tr_group = self._tr(QGroupBox(), "test_record_status")
        tr_h = QHBoxLayout()
        self.tr_status_label = QLabel("OFF")
        tr_h.addWidget(self.tr_status_label)
        tr_group.setLayout(tr_h)
        layout.addWidget(tr_group)

        name_form = QFormLayout()
        self.report_name_input = QLineEdit("autocontrol_report")
        name_form.addRow(self._tr(QLabel(), "report_name"), self.report_name_input)
        layout.addWidget(Card().add(name_form))

        result_card = Card().add(set_role(self._tr(QLabel(), "report_result"), "sectionTitle"))
        self.report_result_text = QTextEdit()
        self.report_result_text.setReadOnly(True)
        layout.addWidget(result_card.add(self.report_result_text, stretch=1), stretch=1)
        self._task = TabTask(self)
        self._task.result.connect(self._on_report_result)
        self._task.error.connect(self._on_report_error)
        self.sync_with_engine()

    def menu_actions(self) -> list[tuple[str, Callable[[], object]]]:
        return [
            ("enable_test_record", self._enable_test_record),
            ("disable_test_record", self._disable_test_record),
            ("generate_html_report", self._gen_html),
            ("generate_json_report", self._gen_json),
            ("generate_xml_report", self._gen_xml),
        ]

    def sync_with_engine(self) -> None:
        self.tr_status_label.setText("ON" if test_record_instance.init_record else "OFF")

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802  # reason: Qt virtual method
        self.sync_with_engine()
        super().showEvent(event)

    def _set_test_record(self, enable: bool) -> None:
        test_record_instance.set_record_enable(enable)
        self.sync_with_engine()

    def _enable_test_record(self) -> None:
        self._set_test_record(True)

    def _disable_test_record(self) -> None:
        self._set_test_record(False)

    def _start_report(self, generator: Callable[[str], None], format_name: str) -> None:
        name = self.report_name_input.text() or "autocontrol_report"
        if self._task.start(partial(_write_report, generator, name, format_name)):
            self.report_result_text.setText(language_wrapper.translate("task_running", "task_running"))

    def _gen_html(self) -> None:
        self._start_report(generate_html_report, "HTML")

    def _gen_json(self) -> None:
        self._start_report(generate_json_report, "JSON")

    def _gen_xml(self) -> None:
        self._start_report(generate_xml_report, "XML")

    def _on_report_result(self, result: str) -> None:
        self.report_result_text.setText(result)

    def _on_report_error(self, error: object) -> None:
        self.report_result_text.setText(f"Error: {error}")

    def dispose(self) -> None:
        """Drop late results; an already-running report write may still finish."""
        self._task.stop()


def _write_report(generator: Callable[[str], None], name: str, format_name: str) -> str:
    generator(name)
    return f"{format_name} report generated: {name}"
