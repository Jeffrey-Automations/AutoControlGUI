"""Core-panel ownership with fake input, recording and script services only."""
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from headless._qt_settle import pump_until, settle
from je_auto_control.gui import _auto_click_tab as auto
from je_auto_control.gui import _record_tab as recording
from je_auto_control.gui import _script_tab as script
from je_auto_control.gui.tab_registry import TabEntry, TabRegistry
from je_auto_control.utils.input_macro.recorder_base import InputRecorder


@pytest.fixture(autouse=True)
def app(monkeypatch):
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    yield application
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("panel", [auto.AutoClickTab, recording.RecordTab, script.ScriptTab])
def test_close_rebuilds_core_panel_and_its_actions(panel):
    entry = TabEntry("core", "core", panel)
    registry = TabRegistry([entry])
    old = registry.open("core")
    assert old.menu_actions()
    registry.close("core")
    assert not entry.built
    new = registry.open("core")
    assert new is not old
    assert all(action.__self__ is new for _, action in new.menu_actions())
    registry.close("core")


def test_cancel_double_click_stops_second_input_and_does_not_queue_ticks(monkeypatch):
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def click(*args):
        calls.append(args)
        entered.set()
        try:
            assert release.wait(5)
        finally:
            exited.set()

    monkeypatch.setattr(auto, "click_mouse", click)
    panel = auto.AutoClickTab()
    panel.click_type_combo.setCurrentIndex(1)
    panel.cursor_x_input.setText("41")
    panel._do_click()
    try:
        assert entered.wait(5)
        panel.cursor_x_input.setText("99")
        for _ in range(5):
            panel._timer_tick()
        panel.dispose()
    finally:
        release.set()
    assert exited.wait(5)
    assert settle(panel._task, "task")
    assert len(calls) == 1
    assert calls[0][1] == 41
    assert not panel.timer.isActive()
    panel.deleteLater()


def test_record_close_keeps_service_and_reopen_reads_actual_state(monkeypatch):
    state = SimpleNamespace(is_recording=True)
    stopped = []
    monkeypatch.setattr(recording.auto_control_record, "recorder", state)
    monkeypatch.setattr(recording, "stop_record", lambda: stopped.append(True))
    first = recording.RecordTab()
    assert first._record_status_key == "record_recording"
    first.dispose()
    first.deleteLater()
    assert stopped == []
    second = recording.RecordTab()
    assert second._record_status_key == "record_recording"
    state.is_recording = False
    second.sync_with_engine()
    assert second._record_status_key == "record_idle"
    monkeypatch.setattr(recording.auto_control_record, "recorder", object())
    second.sync_with_engine()
    assert second._record_status_key == "record_unknown"
    second.deleteLater()


def test_late_record_load_cannot_update_reopened_panel(monkeypatch):
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()

    def read(_path):
        entered.set()
        try:
            assert release.wait(5)
            return [["AC_fake"]]
        finally:
            exited.set()

    monkeypatch.setattr(recording, "read_action_json", read)
    monkeypatch.setattr(recording.QFileDialog, "getOpenFileName", lambda *args: ("fake.json", ""))
    entry = TabEntry("record", "record", recording.RecordTab)
    registry = TabRegistry([entry])
    old = registry.open("record")
    old._load_record()
    try:
        assert entered.wait(5)
        registry.close("record")
        new = registry.open("record")
    finally:
        release.set()
    assert exited.wait(5)
    assert pump_until(lambda: not old._work.running)
    assert new.record_list_text.toPlainText() == ""
    assert new._record_data == []
    registry.close("record")


def test_recorder_status_reports_unknown_custom_hooks_without_starting():
    recorder = InputRecorder()
    assert recorder.is_recording is False
    recorder.hook = object()
    assert recorder.is_recording is None
    recorder.hook = SimpleNamespace(is_recording=True)
    assert recorder.is_recording is True
    recorder.hook.is_recording = False
    assert recorder.is_recording is False
