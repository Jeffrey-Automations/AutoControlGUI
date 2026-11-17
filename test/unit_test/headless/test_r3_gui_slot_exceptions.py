"""Round-3 GUI audit regressions: Actions-menu slots must contain framework
exceptions instead of letting them escape into the Qt event loop.

* builder_tab / main_widget slots caught only builtin exception types while
  their callees raise ``AutoControl*Exception`` (finding 6);
* the auto-click ``_do_click`` slot skipped ``timer.stop()`` on a throwing
  backend, so the QTimer fired forever (finding 7);
* ``TestSuiteTab._on_load_file`` read a file with no error handling, so a
  non-UTF-8 file escaped the slot (finding 10).

Each slot is exercised on a lightweight stub ``self`` with the callee
monkeypatched to fail, so no full Qt widget tree is constructed. The slots that
execute a script run it off the GUI thread now; those three use a real (small)
widget and wait for the outcome to be delivered.
"""
import os
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from headless._qt_settle import settle  # noqa: E402
from je_auto_control.utils.exception.exceptions import (  # noqa: E402
    AutoControlExecuteActionException, AutoControlHTMLException,
    AutoControlMouseException,
)


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _raiser(exc):
    def _fn(*_args, **_kwargs):
        raise exc
    return _fn


# --- Finding 6: builder_tab._on_run ----------------------------------------

def test_builder_run_slot_surfaces_autocontrol_exception(monkeypatch):
    import je_auto_control.gui.script_builder.builder_tab as bt
    warned = {}
    monkeypatch.setattr(bt.QMessageBox, "warning",
                        lambda *a, **k: warned.setdefault("hit", True))
    monkeypatch.setattr(
        bt, "execute_action",
        _raiser(AutoControlExecuteActionException("unregistered command")),
    )

    _app()
    tab = bt.ScriptBuilderTab()
    tab._tree.add_step(bt.Step(command="AC_sleep", params={"seconds": 0}))
    tab._on_run()  # must not raise
    assert settle(tab._runs, "task")
    assert warned.get("hit")


# --- Finding 6: main_widget record / script slots --------------------------

def test_playback_record_slot_surfaces_autocontrol_exception(monkeypatch):
    import je_auto_control.gui._record_tab as rt
    warned = {}
    monkeypatch.setattr(rt.QMessageBox, "warning",
                        lambda *a, **k: warned.setdefault("hit", True))
    monkeypatch.setattr(
        rt, "execute_action",
        _raiser(AutoControlExecuteActionException("boom")),
    )
    from headless._tab_hosts import RecordHost
    _app()
    host = RecordHost([["AC_ok"]])
    host._playback_record()  # must not raise
    assert settle(host._playback_runs, "task")
    assert warned.get("hit")


def test_execute_script_slot_surfaces_autocontrol_exception(monkeypatch):
    import je_auto_control.gui._script_tab as st
    captured = {}
    monkeypatch.setattr(st, "read_executable_action_json", lambda _p: [["AC_ok"]])
    monkeypatch.setattr(
        st, "execute_action",
        _raiser(AutoControlExecuteActionException("boom")),
    )
    from headless._tab_hosts import ScriptHost
    _app()
    host = ScriptHost()
    host.script_path_input.setText("some.json")
    host._execute_script()  # must not raise
    assert settle(host._script_runs, "task")
    captured["t"] = host.script_result_text.toPlainText()
    assert captured.get("t", "").startswith("Error")


# --- Finding 6: report tab, zero records -----------------------------------

def test_report_gen_html_slot_surfaces_autocontrol_exception(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from je_auto_control.gui._report_tab import ReportTab
    from je_auto_control.utils.test_record.record_test_class import test_record_instance

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(test_record_instance, "test_record_list", [])
    tab = ReportTab()
    tab.report_name_input.setText("rpt")
    try:
        tab._gen_html()
        assert settle(tab._task, "task")
        assert tab.report_result_text.toPlainText().startswith("Error")
    finally:
        tab.deleteLater()
        app.processEvents()


def test_report_generate_html_report_really_raises_on_zero_records():
    # Guards the assumption behind the slot test above.
    from je_auto_control.utils.generate_report.generate_html_report import (
        generate_html_report,
    )
    from je_auto_control.utils.test_record.record_test_class import (
        test_record_instance,
    )
    test_record_instance.test_record_list.clear()
    with pytest.raises(AutoControlHTMLException):
        generate_html_report("unused")


# --- Finding 7: auto-click timer stops on a throwing backend ---------------

def test_do_click_stops_timer_on_backend_exception(monkeypatch):
    import je_auto_control.gui._auto_click_tab as ac
    monkeypatch.setattr(ac.QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(
        ac, "click_mouse",
        _raiser(AutoControlMouseException("no backend")),
    )
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    panel = ac.AutoClickTab()
    panel.timer.start(60000)
    panel._do_click()
    assert settle(panel._task, "task")
    assert not panel.timer.isActive()
    panel.deleteLater()
    app.processEvents()


# --- Finding 10: suite load-file tolerates a bad file ----------------------

def test_suite_load_file_handles_non_utf8(monkeypatch, tmp_path):
    import je_auto_control.gui.test_suite_tab as ts
    bad = tmp_path / "bad.json"
    bad.write_bytes(b"\xff\xfe\x00 not valid utf-8 \xff")
    monkeypatch.setattr(ts.QFileDialog, "getOpenFileName",
                        lambda *a, **k: (str(bad), ""))
    captured = {}
    stub = types.SimpleNamespace(
        _spec=types.SimpleNamespace(setPlainText=lambda _s: captured.__setitem__("spec", True)),
        _summary=types.SimpleNamespace(setText=lambda s: captured.__setitem__("summary", s)),
    )

    ts.TestSuiteTab._on_load_file(stub)  # must not raise UnicodeDecodeError
    assert "summary" in captured  # error surfaced on the summary label
    assert "spec" not in captured  # the unreadable content was not shown
