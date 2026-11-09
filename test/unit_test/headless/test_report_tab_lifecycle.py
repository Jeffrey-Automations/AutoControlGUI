"""Report panels own their controls and release them on registry close."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402
from shiboken6 import isValid  # noqa: E402
from je_auto_control.gui import _report_tab  # noqa: E402
from je_auto_control.gui.tab_registry import TAB_SPECS, TabEntry, TabRegistry, lazy_factory  # noqa: E402
from je_auto_control.utils.test_record.record_test_class import TestRecord as Recorder  # noqa: E402


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def recorder(monkeypatch):
    record = Recorder(init_record=True)
    monkeypatch.setattr(_report_tab, "test_record_instance", record)
    return record


def _delete(app, widget):
    widget.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def test_report_registry_releases_and_rebuilds_local_state(app, recorder):
    spec = next(spec for spec in TAB_SPECS if spec.key == "report")
    owner = QWidget()
    entry = TabEntry(spec.key, spec.title_key, lazy_factory(spec.module, spec.class_name),
                     on_build=lambda page: page.setParent(owner))
    registry = TabRegistry([entry])
    assert not entry.built
    page = registry.open("report")
    page.report_name_input.setText("temporary-name")
    page.report_result_text.setText("old result")
    assert page.tr_status_label.text() == "ON"
    page.hide()
    assert registry.open("report") is page
    assert page.report_name_input.text() == "temporary-name"
    registry.close("report")
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    assert not entry.built
    assert not isValid(page)
    assert recorder.init_record
    replacement = registry.open("report")
    assert replacement is not page
    assert replacement.report_name_input.text() == "autocontrol_report"
    assert replacement.report_result_text.toPlainText() == ""
    assert replacement.tr_status_label.text() == "ON"
    assert not hasattr(owner, "report_name_input")
    replacement.retranslate()
    _delete(app, owner)


def test_report_refreshes_process_state_when_shown(app, recorder):
    page = _report_tab.ReportTab()
    try:
        assert page.tr_status_label.text() == "ON"
        page.show()
        page.hide()
        recorder.init_record = False
        page.show()
        assert page.tr_status_label.text() == "OFF"
    finally:
        _delete(app, page)


def test_record_actions_use_actual_recorder(app, recorder):
    page = _report_tab.ReportTab()
    try:
        actions = dict(page.menu_actions())
        assert list(actions) == ["enable_test_record", "disable_test_record", "generate_html_report",
                                 "generate_json_report", "generate_xml_report"]
        actions["disable_test_record"]()
        assert not recorder.init_record
        assert page.tr_status_label.text() == "OFF"
        actions["enable_test_record"]()
        assert recorder.init_record
        assert page.tr_status_label.text() == "ON"
    finally:
        _delete(app, page)


@pytest.mark.parametrize("format_name", ["html", "json", "xml"])
def test_report_actions_generate_named_outputs(app, recorder, monkeypatch, format_name):
    calls = []
    monkeypatch.setattr(_report_tab, "generate_" + format_name + "_report", calls.append)
    page = _report_tab.ReportTab()
    try:
        page.report_name_input.setText("chosen-name")
        dict(page.menu_actions())["generate_" + format_name + "_report"]()
        assert calls == ["chosen-name"]
        assert page.report_result_text.toPlainText() == format_name.upper() + " report generated: chosen-name"
    finally:
        _delete(app, page)
