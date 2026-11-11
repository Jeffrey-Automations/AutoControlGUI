"""Real Diagnostics actions publish execution details without native diagnostic work."""
import os
import threading
import time
import types

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@pytest.fixture(scope='module')
def app():
    widgets = pytest.importorskip('PySide6.QtWidgets', exc_type=ImportError)
    return widgets.QApplication.instance() or widgets.QApplication([])


def pump(app, predicate):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        threading.Event().wait(.001)
    assert predicate()


@pytest.fixture
def shell(app):
    from PySide6.QtCore import QEvent
    from je_auto_control.gui.diagnostics_tab import DiagnosticsTab
    from je_auto_control.gui.tab_registry import TabEntry, TabRegistry
    from je_auto_control.gui.workspace import WorkspaceShell
    widget = WorkspaceShell(TabRegistry([TabEntry('diag', 'tab_diagnostics', DiagnosticsTab)]))
    widget.activate_tab('diag')
    yield widget
    widget.close_tab('diag')
    widget.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


@pytest.mark.parametrize('outcome', ['succeeded', 'error', 'cancelled'])
def test_diagnostics_progress_and_terminal_states_come_from_real_actions(shell, app, monkeypatch, outcome):
    from je_auto_control.gui import diagnostics_tab
    from je_auto_control.utils.diagnostics.diagnostics import Check, DiagnosticsReport
    from je_auto_control.utils.exception.cancellation import current_cancellation_token
    started, release = threading.Event(), threading.Event()

    def run():
        token = current_cancellation_token()
        token.report(1, 3)
        started.set()
        release.wait(2)
        token.checkpoint()
        if outcome == 'error':
            raise RuntimeError('controlled failure')
        return DiagnosticsReport([Check('fake', True, 'info', 'done')])

    monkeypatch.setattr(diagnostics_tab, 'run_diagnostics', run)
    page = shell.tabs.currentWidget()
    actions = dict(page.menu_actions())
    assert shell.details.snapshot.phase == 'idle'
    actions['diag_run']()
    try:
        assert started.wait(1)
        pump(app, lambda: shell.details.snapshot.completed == 1)
        assert shell.details.snapshot.phase == 'running'
        assert shell.details.snapshot.total == 3
        if outcome == 'cancelled':
            actions['diag_stop']()
            assert shell.details.snapshot.phase == 'stopping'
    finally:
        release.set()
    pump(app, lambda: page._active_task is None)
    assert shell.details.snapshot.phase == outcome
    if outcome == 'error':
        assert 'controlled failure' in shell.details.snapshot.summary


def test_view_toggle_survives_language_rebuild_and_refreshes_all_languages(app, monkeypatch, tmp_path):
    from PySide6.QtCore import QEvent, QSettings
    from je_auto_control.gui import main_widget, main_window, workspace_details
    from je_auto_control.gui.language_wrapper.multi_language_wrapper import LanguageWrapper
    from je_auto_control.gui.workspace_details import ExecutionDetails
    language = LanguageWrapper()
    monkeypatch.setattr(main_window, 'language_wrapper', language)
    monkeypatch.setattr(workspace_details, 'language_wrapper', language)
    monkeypatch.setattr(main_window, 'sys', types.SimpleNamespace(platform='test'))
    monkeypatch.setattr(main_widget, 'TAB_SPECS', ())
    settings = QSettings(str(tmp_path / 'workspace.ini'), QSettings.Format.IniFormat)
    window = main_window.AutoControlGUIUI(settings=settings)
    try:
        shell = window.auto_control_gui_widget
        action = window._details_action
        assert action.shortcut().toString() == 'Ctrl+Shift+D'
        assert shell.details.isHidden()
        action.trigger()
        assert not shell.details.isHidden()
        shell.details.display(ExecutionDetails('running', 'values stay intact', 2, 5), selected=True)
        initial_actions = len(window.actions())
        labels = set()
        for name in language.available_languages:
            language.reset_language(name)
            labels.add(action.text())
            assert action.isChecked()
            assert window._details_action is action
            assert len(window.actions()) == initial_actions
            assert shell.details.summary.text() == 'values stay intact'
        assert len(labels) == 4
        shell.set_details_visible(False)
        assert not action.isChecked()
        window._apply_font_pt(20)
        window.resize(640, 420)
        assert shell.minimumSizeHint().width() <= 640
    finally:
        window.close()
        window.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
