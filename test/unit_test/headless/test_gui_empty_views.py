"""An empty table, list or tree on a page says so, and stops saying so when rows arrive.

Pages showed a blank grid (often with headers only) until a command filled
it, with nothing to tell an empty result from one still to come.
"""
import os

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QStringListModel, Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QComboBox, QListView, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from je_auto_control.gui.adaptive.empty_views import NO_EMPTY_STATE, show_empty_states  # noqa: E402
from je_auto_control.gui.adaptive.surfaces import EmptyState  # noqa: E402
from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper  # noqa: E402

_APP = QApplication.instance() or QApplication([])


@pytest.fixture
def page():
    widget = QWidget()
    widget.resize(600, 400)
    yield widget
    widget.deleteLater()


def _state(view):
    found = view.viewport().findChild(EmptyState, "EmptyViewState")
    assert found is not None, "the view has no empty state"
    return found


def test_an_empty_table_shows_the_message_until_a_row_arrives(page):
    table = QTableWidget(0, 3)
    QVBoxLayout(page).addWidget(table)
    assert show_empty_states(page) == 1
    page.show()
    _APP.processEvents()
    state = _state(table)
    assert state.isVisible()
    assert state.message.text() == language_wrapper.translate("empty_view", "empty_view")
    table.setRowCount(1)
    table.setItem(0, 0, QTableWidgetItem("x"))
    assert not state.isVisible()
    table.setRowCount(0)
    assert state.isVisible()


def test_the_overlay_lets_clicks_through_and_stays_inside_the_view(page):
    table = QTableWidget(0, 2)
    QVBoxLayout(page).addWidget(table)
    show_empty_states(page)
    page.show()
    _APP.processEvents()
    state = _state(table)
    assert state.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    viewport = table.viewport().rect()
    assert viewport.contains(state.geometry())


def test_a_replaced_model_is_followed(page):
    view = QListView()
    QVBoxLayout(page).addWidget(view)
    show_empty_states(page)
    page.show()
    _APP.processEvents()
    assert _state(view).isVisible()                 # no model at all
    view.setModel(QStringListModel(["one"], view))
    view.viewport().repaint()
    _APP.processEvents()
    assert not _state(view).isVisible()


def test_headers_combo_lists_and_opted_out_views_are_left_alone(page):
    layout = QVBoxLayout(page)
    table = QTableWidget(0, 1)
    combo = QComboBox()
    quiet = QTableWidget(0, 1)
    quiet.setProperty(NO_EMPTY_STATE, True)
    for widget in (table, combo, quiet):
        layout.addWidget(widget)
    assert show_empty_states(page) == 1             # the table only: not its headers, the combo's list, or quiet
    assert show_empty_states(page) == 0             # a second pass adds nothing
    assert quiet.viewport().findChild(EmptyState) is None


def test_the_workspace_gives_its_pages_empty_states():
    from je_auto_control.gui.tab_registry import TabEntry, TabRegistry
    from je_auto_control.gui.workspace import WorkspaceShell

    def build():
        widget = QWidget()
        QVBoxLayout(widget).addWidget(QTableWidget(0, 2))
        return widget

    shell = WorkspaceShell(TabRegistry([TabEntry("hosts", "hosts", build)]))
    try:
        shell.activate_tab("hosts")
        table = shell.tabs.currentWidget().findChild(QTableWidget)
        assert table.viewport().findChild(EmptyState, "EmptyViewState") is not None
    finally:
        shell.deleteLater()
