"""A text a tab sets from its state follows a language switch (offscreen Qt; no real I/O).

Each case builds a tab in English, drives it into a state that sets a status
line, result or hint -- through a method that needs no device, network or
file -- switches to Japanese and calls ``retranslate``. The text must then
read as the catalogue key renders in Japanese, with the same data filled in,
and nothing may have run again to get there.
"""
import os
import types

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

from je_auto_control.gui._i18n_helpers import KeyedText, TranslatableMixin  # noqa: E402
from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture()
def english():
    previous = language_wrapper.language
    language_wrapper.reset_language("English")
    yield
    language_wrapper.reset_language(previous)


def _in_language(key, **fields):
    text = language_wrapper.translate(key, key)
    for name, value in fields.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def _switch_and_check(tab, read, key, prefix="", suffix="", **fields):
    """Switch to Japanese, re-translate ``tab`` and compare what ``read`` returns with ``key`` rendered there."""
    before = read(tab)
    assert before == prefix + _in_language(key, **fields) + suffix, before
    language_wrapper.reset_language("Japanese")
    expected = prefix + _in_language(key, **fields) + suffix
    assert expected != before, f"{key} reads the same in both languages: the case proves nothing"
    tab.retranslate()
    assert read(tab) == expected


def _dispose(qapp, tab):
    getattr(tab, "dispose", tab.close)()
    tab.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def _text(name):
    return lambda tab: getattr(tab, name).text()


def _plain(name):
    return lambda tab: getattr(tab, name).toPlainText()


# (module, class, how to drive it, how to read the text, key, fields)
_CASES = [
    ("a11y_audit_tab", "A11yAuditTab",
     lambda tab: tab._render({"issues": [], "error_count": 2, "warning_count": 5}),
     _text("_summary"), "audit_summary", {"errors": 2, "warnings": 5}),
    ("accessibility_tab", "AccessibilityTab", lambda tab: tab._click_selected(),
     _text("_status"), "a11y_no_selection", {}),
    ("admin_console_tab", "AdminConsoleTab", lambda tab: tab._show_broadcast([{"sent": True}, {"sent": False}]),
     _text("_broadcast_status"), "admin_broadcast_summary", {"sent": 1, "total": 2, "skipped": 1}),
    ("audit_log_tab", "AuditLogTab",
     lambda tab: tab._show_verified(types.SimpleNamespace(ok=False, broken_at_id=7, total_rows=9)),
     _text("_verify_status"), "audit_verify_broken", {"row_id": 7, "total": 9}),
    ("computer_use_tab", "ComputerUseTab", lambda tab: tab._on_worker_finished({"succeeded": True}),
     _text("_status"), "computer_use_success", {}),
    ("dag_tab", "DagTab", lambda tab: tab._parse_editor(), _text("_status_label"), "dag_empty", {}),
    ("data_source_tab", "DataSourceTab", lambda tab: tab._on_loaded([{"a": 1}, {"a": 2}]),
     _text("_status"), "ds_row_count", {"n": 2}),
    ("device_matrix_tab", "DeviceMatrixTab",
     lambda tab: tab._render({"results": [], "passed": 3, "failed": 1, "total": 4}),
     _text("_summary"), "dm_summary", {"passed": 3, "failed": 1, "total": 4}),
    ("flow_editor.tab", "FlowEditorTab", lambda tab: tab._on_save(), _text("_status"), "flow_empty", {}),
    ("llm_planner_tab", "LLMPlannerTab", lambda tab: tab._on_run(), _text("_status"), "llm_no_plan", {}),
    ("ocr_tab", "OCRReaderTab", lambda tab: tab._on_find_regex(), _text("_status"), "ocr_regex_required", {}),
    ("presence_tab", "PresenceTab", lambda tab: tab._selected_viewer_id(),
     _text("_status"), "presence_no_selection", {}),
    ("self_healing_tab", "SelfHealingTab", lambda tab: tab._collect_inputs(),
     _text("_status"), "self_heal_inputs_required", {}),
    ("test_suite_tab", "TestSuiteTab",
     lambda tab: tab._render_result(types.SimpleNamespace(cases=[], passed=4, failed=1, errored=0, skipped=2)),
     _text("_summary"), "suite_summary", {"passed": 4, "failed": 1, "errored": 0, "skipped": 2}),
    ("usb_browser_tab", "UsbBrowserTab", lambda tab: tab._apply_devices([{}, {}]),
     _text("_status_label"), "usb_browser_fetched", {"count": 2}),
    ("variables_tab", "VariablesTab", lambda tab: tab._on_set_one(), _text("_status"), "vars_name_required", {}),
    ("vlm_tab", "VLMTab", lambda tab: tab._show_located((3, 4)), _text("_last_result"), "vlm_result",
     {"x": 3, "y": 4}),
    ("vlm_tab", "VLMTab", lambda tab: tab._show_located((3, 4)), _text("_status"), "vlm_ok", {}),
    ("failed_stops_view", "FailedStopsView", lambda view: view.retry_all(),
     _text("_status"), "failed_stops_nothing", {}),
    ("agent_transfer_view", "AgentTransferView", lambda view: view.prepare_approval(),
     _text("_status"), "agent_transfer_review_required", {}),
]


@pytest.mark.parametrize("module, name, drive, read, key, fields", _CASES,
                         ids=[f"{case[1]}-{case[4]}" for case in _CASES])
def test_a_state_text_follows_a_language_switch(qapp, english, module, name, drive, read, key, fields):
    import importlib
    build = getattr(importlib.import_module(f"je_auto_control.gui.{module}"), name)
    kwargs = {}
    if name == "FailedStopsView":
        from je_auto_control.gui._stop_custody import StopCustody
        kwargs["custody"] = StopCustody()
    tab = build(**kwargs)
    try:
        drive(tab)
        _switch_and_check(tab, read, key, **fields)
    finally:
        _dispose(qapp, tab)


def test_a_label_over_an_error_keeps_the_error(qapp, english):
    from je_auto_control.gui.assertions_tab import AssertionsTab
    tab = AssertionsTab()
    try:
        tab._show_error(ValueError("no such text"))
        _switch_and_check(tab, _text("_result"), "assert_failed", suffix=": no such text")
    finally:
        _dispose(qapp, tab)


def test_the_self_heal_hit_keeps_its_point_and_method(qapp, english):
    from je_auto_control.gui.self_healing_tab import SelfHealingTab
    tab = SelfHealingTab()
    try:
        tab._report_outcome(types.SimpleNamespace(found=True, coordinates=(10, 20), method="template"))
        _switch_and_check(tab, _text("_status"), "self_heal_hit", suffix=" (template)", x=10, y=20)
    finally:
        _dispose(qapp, tab)


def test_the_usb_acl_result_is_keyed_with_its_fields(qapp, english, tmp_path):
    from je_auto_control.gui.usb_passthrough_panel import UsbPassthroughPanel
    from je_auto_control.utils.usb.passthrough import UsbAcl
    panel = UsbPassthroughPanel(acl=UsbAcl(path=tmp_path / "acl.json"))
    try:
        panel._acl_outcome = ("usb_share_allowed", {"vid": "1050", "pid": "0407"}, False)
        panel._acl_done(1)
        _switch_and_check(panel, _text("_viewer_status"), "usb_share_allowed", vid="1050", pid="0407")
    finally:
        _dispose(qapp, panel)


def test_an_ocr_field_error_is_shown_from_its_key(qapp, english):
    from je_auto_control.gui.ocr_tab import OCRReaderTab
    tab = OCRReaderTab()
    try:
        tab._region.setText("not, a, region")
        tab._on_dump()
        assert tab._task is None, "a bad region must not start a read"
        _switch_and_check(tab, _text("_status"), "ocr_region_invalid")
    finally:
        _dispose(qapp, tab)


def test_the_script_and_report_results_follow_a_switch(qapp, english, monkeypatch):
    from je_auto_control.gui._report_tab import ReportTab
    from je_auto_control.gui._script_tab import ScriptTab
    script, report = ScriptTab(), ReportTab()
    try:
        monkeypatch.setattr(script._script_runs, "start_script", lambda *_args, **_kwargs: False)
        monkeypatch.setattr(report._task, "start", lambda *_args, **_kwargs: True)
        script._start_script_run(lambda: None)
        report._gen_json()
        _switch_and_check(script, _plain("script_result_text"), "task_busy")
        language_wrapper.reset_language("English")
        _switch_and_check(report, _plain("report_result_text"), "task_running")
    finally:
        _dispose(qapp, script)
        _dispose(qapp, report)


def test_the_run_history_count_is_re_rendered_without_a_new_query(qapp, english, monkeypatch):
    from je_auto_control.gui.run_history_tab import RunHistoryTab
    tab = RunHistoryTab()
    try:
        tab._queried_source = tab._filter.currentData()
        tab._show_runs([])
        queried = []
        monkeypatch.setattr(tab, "_refresh", lambda: queried.append(1))
        _switch_and_check(tab, _text("_count_label"), "rh_count_label", n=0)
        assert queried == [], "a language switch queried the history again"
    finally:
        _dispose(qapp, tab)


# --- the helper itself ---------------------------------------------------------------------


class _Owner(TranslatableMixin, QWidget):
    def __init__(self):
        super().__init__()
        self.label = QLabel(self)
        self.label_text = self._keyed(self.label)
        self.title = self._keyed(self, "setWindowTitle")


def test_keyed_texts_follow_the_owner_and_can_be_let_go(qapp, english):
    owner = _Owner()
    try:
        owner.label_text.show("task_running")
        owner.title.show_joined("task_busy", "detail", " - ")
        language_wrapper.reset_language("Japanese")
        owner.retranslate()
        assert owner.label.text() == _in_language("task_running")
        assert owner.windowTitle() == _in_language("task_busy") + " - detail"
        owner.label_text.forget()
        owner.label.setText("a picture took its place")
        owner.label_text.clear()
        owner.label.setText("data")
        language_wrapper.reset_language("English")
        owner.retranslate()
        assert owner.label.text() == "data"
    finally:
        _dispose(qapp, owner)


def test_a_keyed_title_does_not_keep_its_owner_alive(qapp, english):
    import gc
    import weakref
    owner = _Owner()
    owner.title.show("task_running")
    alive = weakref.ref(owner)
    owner.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    del owner
    gc.collect()
    assert alive() is None


def test_a_keyed_text_of_a_destroyed_widget_is_dropped(qapp, english):
    label = QLabel()
    text = KeyedText(label)
    text.show("task_running")
    label.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    text.retranslate()          # no error: the widget is gone, so is the key
