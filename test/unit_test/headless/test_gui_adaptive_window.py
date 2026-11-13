"""The window rearranges its panes by width: docked when wide, drawers and a rail when narrow."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    widgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    return widgets.QApplication.instance() or widgets.QApplication([])


@pytest.fixture
def window_factory(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    from je_auto_control.gui import main_widget
    from je_auto_control.gui.main_window import AutoControlGUIUI

    monkeypatch.setattr(main_widget, "TAB_SPECS", tuple(
        spec for spec in main_widget.TAB_SPECS if spec.key in {"record", "variables", "auto_click"}
    ))
    settings = QSettings(str(tmp_path / "workspace.ini"), QSettings.Format.IniFormat)
    windows = []

    def build():
        window = AutoControlGUIUI(settings=settings)
        windows.append(window)
        window.resize(1280, 800)
        window.show()
        qapp.processEvents()
        return window

    yield build, settings
    for window in windows:
        window.close()
        window.deleteLater()


def _resize(qapp, window, width, height=700):
    window.resize(width, height)
    for _ in range(3):
        qapp.processEvents()


def test_a_wide_window_docks_both_panes(window_factory, qapp):
    from je_auto_control.gui.adaptive.breakpoints import WidthClass
    build, _settings = window_factory
    window = build()
    layout, shell = window._adaptive, window.auto_control_gui_widget
    assert layout.width_class is WidthClass.EXPANDED
    assert not layout.rail.isVisible()
    assert not window._navigation_dock.isHidden()
    assert not shell.details_overlay
    shell.set_details_visible(True)
    assert shell.details.parentWidget() is shell._splitter


def test_a_medium_window_opens_details_as_a_drawer(window_factory, qapp):
    build, _settings = window_factory
    window = build()
    shell = window.auto_control_gui_widget
    window._details_action.trigger()
    assert shell.details_visible()
    _resize(qapp, window, 1000)
    assert shell.details_overlay
    assert shell.details_visible(), "the details stay open when they move into the drawer"
    assert shell._details_drawer.content() is shell.details
    assert not window._navigation_dock.isHidden(), "the navigation stays docked at medium width"
    shell._details_drawer.close_drawer()      # what Escape and a click on the scrim do
    assert not shell.details_visible()
    assert not window._details_action.isChecked()
    window._details_action.trigger()
    assert shell._details_drawer.is_open
    _resize(qapp, window, 1400)
    assert not shell.details_overlay
    assert shell.details.parentWidget() is shell._splitter
    assert shell.details_visible(), "back in the column, still open"


def test_a_compact_window_swaps_the_docked_list_for_a_rail_and_a_drawer(window_factory, qapp):
    build, settings = window_factory
    window = build()
    layout, shell = window._adaptive, window.auto_control_gui_widget
    _resize(qapp, window, 600)
    assert layout.compact
    assert layout.rail.isVisible()
    assert window._navigation_dock.isHidden()
    assert layout.navigation_preferred, "hiding the dock for width is not the user's choice"
    assert not window._sidebar_action.isChecked()
    window._sidebar_action.trigger()          # Ctrl+B
    assert layout.drawer.is_open
    assert window._sidebar_action.isChecked()
    assert layout.panel.visible_keys() == window.navigation.visible_keys()
    layout.panel.feature_activated.emit("variables")
    assert shell.current_tab_key() == "variables"
    assert not layout.drawer.is_open, "choosing a feature closes the drawer"
    window.close()
    assert str(settings.value("workspace/navigation_visible")).lower() == "true"


def test_ctrl_k_opens_the_list_wherever_it_lives(window_factory, qapp):
    build, _settings = window_factory
    window = build()
    layout = window._adaptive
    window._sidebar_action.trigger()
    assert window._navigation_dock.isHidden() and not layout.navigation_preferred
    window._search_action.trigger()
    assert not window._navigation_dock.isHidden(), "a wide window shows the docked list again"
    assert layout.navigation_preferred
    _resize(qapp, window, 600)
    window._search_action.trigger()
    assert layout.drawer.is_open
    _resize(qapp, window, 1300)
    assert not layout.drawer.is_open, "widening the window closes the drawer"
    assert not window._navigation_dock.isHidden()


def test_a_hidden_preference_survives_a_compact_spell(window_factory, qapp):
    build, settings = window_factory
    window = build()
    window._sidebar_action.trigger()
    _resize(qapp, window, 600)
    window._sidebar_action.trigger()
    window._adaptive.drawer.close_drawer()
    _resize(qapp, window, 1300)
    assert window._navigation_dock.isHidden(), "the user hid it before the window narrowed"
    window.close()
    assert str(settings.value("workspace/navigation_visible")).lower() == "false"


def test_resizing_near_a_boundary_does_not_flip_back_and_forth(window_factory, qapp):
    from je_auto_control.gui.adaptive.breakpoints import WidthClass
    build, _settings = window_factory
    window = build()
    seen = []
    window._adaptive.width_class_changed.connect(seen.append)
    for width in (1190, 1210, 1185, 1215, 1100):
        _resize(qapp, window, width)
    assert seen == [WidthClass.MEDIUM.value]


def test_the_rail_icons_follow_the_theme(window_factory, qapp):
    build, _settings = window_factory
    window = build()
    action = window._adaptive.menu_action
    before = action.icon().pixmap(20, 20).toImage()
    window.set_theme("light")
    after = action.icon().pixmap(20, 20).toImage()
    assert not action.icon().isNull()
    assert before != after
    assert action.toolTip()


def test_a_drawer_closes_on_a_click_beside_its_panel_only(qapp):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QLabel, QWidget
    from je_auto_control.gui.adaptive.overlay import DRAWER_WIDTH, OverlayDrawer
    host = QWidget()
    host.resize(800, 500)
    drawer = OverlayDrawer(host, Qt.Edge.RightEdge, "DetailsOverlay")
    content = QLabel("details")
    drawer.set_content(content)
    closed = []
    drawer.closed.connect(lambda: closed.append(True))
    drawer.open_drawer()
    assert drawer.panel.geometry().width() == DRAWER_WIDTH
    assert drawer.panel.geometry().right() == 799

    def click(x):
        point = QPointF(QPoint(x, 100))
        return QMouseEvent(QMouseEvent.Type.MouseButtonPress, point, point, Qt.MouseButton.LeftButton,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    drawer.mousePressEvent(click(700))
    assert drawer.is_open and not closed
    drawer.mousePressEvent(click(100))
    assert not drawer.is_open and closed == [True]
    drawer.close_drawer()
    assert closed == [True], "closing a closed drawer reports nothing"
    narrow = drawer.panel_rect(300, 200)
    assert narrow.width() == int(300 * 0.85) and narrow.right() == 299
    drawer.set_content(None)
    assert drawer.content() is None and content.parent() is None
    host.deleteLater()
    content.deleteLater()


def test_the_glyphs_draw_on_transparent_ground(qapp):
    from je_auto_control.gui.adaptive.glyphs import GLYPHS, glyph_pixmap
    for name in GLYPHS:
        image = glyph_pixmap(name, "#ff0000", 20, 2.0).toImage()
        assert image.width() == 40
        assert image.pixelColor(0, 0).alpha() == 0
        assert any(image.pixelColor(x, y).red() > 200 and image.pixelColor(x, y).alpha() > 200
                   for x in range(40) for y in range(40)), name
