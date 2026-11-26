"""Texts the tabs used to write in English come from the catalogue (offscreen Qt; no real I/O).

A dialog title, a result line or a header that a tab wrote as an English
literal stayed English in every language. Each case drives a tab into the
state that shows one, through a method that needs no device, network or file,
and checks it reads as its key does -- after a switch to Japanese where the tab
keeps the text on screen, at the moment it is shown where it is a dialog. A
source scan keeps literal message-box titles from coming back.
"""
import os
import re
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper  # noqa: E402

_GUI = Path(__file__).resolve().parents[3] / "je_auto_control" / "gui"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def english():
    previous = language_wrapper.language
    language_wrapper.reset_language("English")
    yield
    language_wrapper.reset_language(previous)


def _word(key, **fields):
    text = language_wrapper.translate(key, key)
    for name, value in fields.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def _dispose(qapp, widget):
    getattr(widget, "dispose", widget.close)()
    widget.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def _switch(widget, read, expected):
    """``expected()`` renders in the active language: check, switch to Japanese, re-translate, check again."""
    before = read()
    assert before == expected(), before
    language_wrapper.reset_language("Japanese")
    assert expected() != before, "the text reads the same in both languages: the case proves nothing"
    widget.retranslate()
    assert read() == expected()


def test_the_plugin_results(qapp, english):
    from je_auto_control.gui.plugins_tab import PluginsTab
    tab = PluginsTab()
    try:
        tab._loading_path = "plugins"
        tab._on_loaded({})
        _switch(tab, tab._status.text, lambda: _word("pl_none_found", path="plugins"))
    finally:
        _dispose(qapp, tab)


def test_the_image_detection_results(qapp, english):
    from je_auto_control.gui._image_detect_tab import ImageDetectionTab
    tab = ImageDetectionTab()
    try:
        tab._on_task_result(("img_clicked", {"point": (3, 4)}))
        assert tab.detect_result_text.toPlainText() == "Clicked at: (3, 4)"
        _switch(tab, tab.detect_result_text.toPlainText, lambda: _word("img_clicked", point=(3, 4)))
        language_wrapper.reset_language("English")
        tab.img_path_input.setText("")
        tab._locate_image()
        assert tab.detect_result_text.toPlainText() == "Error: Template image path is empty"
        _switch(tab, tab.detect_result_text.toPlainText,
                lambda: _word("gui_error_title") + ": " + _word("img_path_empty"))
    finally:
        _dispose(qapp, tab)


def test_the_screenshot_saved_line():
    from je_auto_control.gui import _screenshot_tab
    previous = language_wrapper.language
    try:
        language_wrapper.reset_language("English")
        assert _screenshot_tab._saved_text("") == "Screenshot saved: (not saved)"
        language_wrapper.reset_language("Japanese")
        assert _screenshot_tab._saved_text("a.png") == _word("screenshot_saved", path="a.png")
    finally:
        language_wrapper.reset_language(previous)


def test_the_report_record_state_and_result(qapp, english):
    from je_auto_control.gui._report_tab import ReportTab
    tab = ReportTab()
    try:
        on = tab.tr_status_label.text() == "ON"
        _switch(tab, tab.tr_status_label.text, lambda: _word("report_record_on" if on else "report_record_off"))
        language_wrapper.reset_language("English")
        tab._on_report_result(("JSON", "out"))
        assert tab.report_result_text.toPlainText() == "JSON report generated: out"
        _switch(tab, tab.report_result_text.toPlainText, lambda: _word("report_generated", format="JSON", name="out"))
    finally:
        _dispose(qapp, tab)


def test_the_recording_editor_count(qapp, english):
    from je_auto_control.gui.recording_editor_tab import RecordingEditorTab
    tab = RecordingEditorTab()
    try:
        tab._actions = [["AC_click_mouse", {}], ["AC_type_keyboard", {}]]
        tab._refresh()
        assert tab._status.text() == "2 actions"
        _switch(tab, tab._status.text, lambda: _word("re_action_count", count=2))
    finally:
        _dispose(qapp, tab)


def test_the_contrast_verdict(qapp, english):
    from je_auto_control.gui.a11y_audit_tab import A11yAuditTab
    tab = A11yAuditTab()
    try:
        tab._fg.setText("0, 0, 0")
        tab._bg.setText("255, 255, 255")
        tab._on_contrast()
        assert tab._summary.text() == "contrast 21.00:1 — AA PASS"
        _switch(tab, tab._summary.text,
                lambda: _word("audit_contrast_result", ratio="21.00", verdict=_word("audit_contrast_pass")))
    finally:
        _dispose(qapp, tab)


def test_the_step_tree_header(qapp, english):
    from je_auto_control.gui.script_builder.step_list_view import StepTreeView
    tree = StepTreeView()
    try:
        _switch(tree, lambda: tree.headerItem().text(0), lambda: _word("sb_step_header"))
    finally:
        _dispose(qapp, tree)


def test_the_remote_desktop_placeholder(qapp, english):
    from je_auto_control.gui.main_widget import _RemoteDesktopUnavailable
    error = ImportError("No module named 'aiortc'")
    page = _RemoteDesktopUnavailable(error)
    try:
        label = page.findChild(QLabel)
        assert "pip install je_auto_control[webrtc]" in label.text()
        _switch(page, label.text, lambda: _word("rd_unavailable_detail", error=repr(error)))
        assert "pip install je_auto_control[webrtc]" in label.text(), "the command is not translated"
    finally:
        _dispose(qapp, page)


def test_a_message_box_reads_in_the_active_language(qapp, english, monkeypatch):
    from je_auto_control.gui import scheduler_tab
    shown = []
    monkeypatch.setattr(scheduler_tab.QMessageBox, "warning", lambda _parent, title, text: shown.append((title, text)))
    tab = scheduler_tab.SchedulerTab()
    try:
        language_wrapper.reset_language("Japanese")
        tab._on_add()
        assert shown == [(_word("gui_error_title"), _word("sch_script_required"))]
        assert shown[0][0] != "Error"
    finally:
        _dispose(qapp, tab)


def test_no_message_box_has_a_literal_english_title():
    title = re.compile(r"QMessageBox\.\w+\(\s*\w+,\s*[\"'](Error|Warning|Info|Information)[\"']")
    found = [f"{path.relative_to(_GUI)}:{number}" for path in _GUI.rglob("*.py")
             for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if title.search(line)]
    assert found == [], found
