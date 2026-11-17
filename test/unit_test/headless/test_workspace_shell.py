"""The injected workspace registry and detail subscriptions preserve page ownership."""
import gc
import os
import weakref

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@pytest.fixture(scope='module')
def app():
    widgets = pytest.importorskip('PySide6.QtWidgets', exc_type=ImportError)
    return widgets.QApplication.instance() or widgets.QApplication([])


def flush(app):
    from PySide6.QtCore import QEvent
    app.processEvents()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


@pytest.fixture
def shell(app):
    from PySide6.QtWidgets import QWidget
    from je_auto_control.gui.tab_registry import TabEntry, TabRegistry
    from je_auto_control.gui.workspace import WorkspaceShell
    from je_auto_control.gui.workspace_details import ExecutionDetailsSource

    def page():
        widget = QWidget()
        ExecutionDetailsSource(widget)
        return widget

    registry = TabRegistry([TabEntry('one', 'one', page), TabEntry('two', 'two', page),
                            TabEntry('plain', 'plain', QWidget)])
    widget = WorkspaceShell(registry)
    yield widget
    widget.deleteLater()
    flush(app)


def source(shell):
    from je_auto_control.gui.workspace_details import ExecutionDetailsSource
    return shell.tabs.currentWidget().findChild(ExecutionDetailsSource)


def test_supplied_registry_is_authoritative_and_hidden_pages_stay_lazy(shell):
    from PySide6.QtWidgets import QWidget
    from je_auto_control.gui.tab_registry import TabEntry
    assert not any(entry.built for entry in shell.tab_registry.entries)
    shell.tab_registry.add(TabEntry('later', 'later', QWidget))
    assert [entry['key'] for entry in shell.list_registered_tabs()] == ['one', 'two', 'plain', 'later']
    shell.activate_tab('two')
    assert shell.tabs.currentWidget() is shell.tab_registry.open('two')
    assert [entry.key for entry in shell.tab_registry.entries if entry.built] == ['two']


def test_external_close_detaches_and_reopen_has_fresh_details(shell, app):
    from shiboken6 import isValid
    from je_auto_control.gui.workspace_details import ExecutionDetails
    shell.activate_tab('one')
    first = shell.tabs.currentWidget()
    source(shell).publish(ExecutionDetails('running', 'first operation', 1, 5))
    assert shell.details.snapshot.summary == 'first operation'
    shell.tab_registry.close('one')
    assert shell.tabs.count() == 0
    assert shell.details.snapshot is None
    flush(app)
    assert not isValid(first)
    shell.activate_tab('one')
    assert shell.tabs.currentWidget() is not first
    assert shell.details.snapshot.phase == 'idle'


def test_hide_preserves_page_but_disconnects_its_details(shell):
    from je_auto_control.gui.workspace_details import ExecutionDetails
    shell.activate_tab('one')
    page = shell.tabs.currentWidget()
    publisher = source(shell)
    shell.hide_tab('one')
    publisher.publish(ExecutionDetails('error', 'hidden result'))
    assert shell.details.snapshot is None
    shell.activate_tab('one')
    assert shell.tabs.currentWidget() is page
    assert shell.details.snapshot.summary == 'hidden result'


def test_queued_old_details_cannot_replace_selected_page(shell, app):
    from PySide6.QtCore import QObject, Qt
    from je_auto_control.gui.workspace_details import ExecutionDetails
    shell.activate_tab('one')
    old = source(shell)
    QObject.disconnect(shell._details_connection)
    shell._details_connection = old.changed.connect(shell._on_details_changed, Qt.ConnectionType.QueuedConnection)
    old.publish(ExecutionDetails('error', 'stale'))
    shell.activate_tab('two')
    source(shell).publish(ExecutionDetails('succeeded', 'current'))
    flush(app)
    assert shell.details.snapshot.summary == 'current'


def test_refused_close_preserves_details_and_constructor_callback(app):
    from PySide6.QtWidgets import QWidget
    from je_auto_control.gui.tab_registry import TabEntry, TabRegistry
    from je_auto_control.gui.workspace import WorkspaceShell
    from je_auto_control.gui.workspace_details import ExecutionDetailsSource

    class Unsaved(QWidget):
        def __init__(self):
            super().__init__()
            ExecutionDetailsSource(self)

        def closeEvent(self, event):
            event.ignore()

    closed = []
    registry = TabRegistry([TabEntry('one', 'one', Unsaved)], on_close=closed.append)
    widget = WorkspaceShell(registry)
    widget.activate_tab('one')
    snapshot = widget.details.snapshot
    registry.close('one')
    assert widget.tabs.count() == 1
    assert widget.details.snapshot is snapshot
    assert closed == []
    widget.deleteLater()
    flush(app)


def test_registry_does_not_retain_destroyed_shell(app):
    from PySide6.QtWidgets import QWidget
    from je_auto_control.gui.tab_registry import TabEntry, TabRegistry
    from je_auto_control.gui.workspace import WorkspaceShell
    registry = TabRegistry([TabEntry('one', 'one', QWidget)])
    widget = WorkspaceShell(registry)
    widget._add_tab('added', 'added', QWidget)
    widget.activate_tab('one')
    page = widget.tabs.currentWidget()
    reference = weakref.ref(widget)
    widget.deleteLater()
    flush(app)
    del widget
    gc.collect()
    assert reference() is None
    assert not registry._close_listeners
    assert not registry.entries[0].built
    replacement = WorkspaceShell(registry)
    replacement.activate_tab('one')
    assert replacement.tabs.currentWidget() is not page
    replacement.deleteLater()
    flush(app)


def test_old_deferred_destruction_cannot_forget_replacement(shell, app):
    shell.activate_tab('one')
    first = shell.tabs.currentWidget()
    shell.close_tab('one')
    shell.activate_tab('one')
    second = shell.tabs.currentWidget()
    assert second is not first
    flush(app)
    assert shell.tab_registry.open('one') is second


def test_accepted_close_notifies_existing_callback_before_releasing(app):
    from PySide6.QtWidgets import QWidget
    from je_auto_control.gui.tab_registry import TabEntry, TabRegistry
    from je_auto_control.gui.workspace import WorkspaceShell
    events = []

    class Page(QWidget):
        def dispose(self):
            events.append(('dispose', widget.tabs.count()))

    registry = TabRegistry([TabEntry('one', 'one', Page)], on_close=lambda page: events.append(('callback', page)))
    widget = WorkspaceShell(registry)
    widget.activate_tab('one')
    page = widget.tabs.currentWidget()
    registry.close('one')
    assert events == [('callback', page), ('dispose', 0)]
    widget.deleteLater()
    flush(app)


def test_unpublished_page_has_distinct_empty_state_and_plain_text(shell):
    from PySide6.QtCore import Qt
    from je_auto_control.gui.workspace_details import ExecutionDetails
    empty = shell.details.state.text()
    shell.activate_tab('plain')
    assert shell.details.state.text() != empty
    shell.activate_tab('one')
    source(shell).publish(ExecutionDetails('error', '<img src="file:///secret">'))
    assert shell.details.summary.textFormat() == Qt.TextFormat.PlainText
    assert shell.details.summary.text() == '<img src="file:///secret">'


def test_collapsed_details_do_not_expand_minimum_width(shell, app):
    shell.resize(640, 420)
    shell.show()
    shell.activate_tab('one')
    shell.set_details_visible(True)
    flush(app)
    assert not shell.details.isHidden()
    shell.set_details_visible(False)
    flush(app)
    assert shell.details.isHidden()
    assert shell.minimumSizeHint().width() <= 640
    assert shell.tabs.width() <= shell.width()
