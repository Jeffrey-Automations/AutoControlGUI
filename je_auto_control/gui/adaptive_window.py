"""Rearrange the main window's navigation and details panes as the window's width class changes.

Expanded windows dock both panes beside the tabs. Medium ones keep the
navigation docked but open the details as a drawer. Compact ones replace the
docked navigation with a narrow rail of icons; its menu button and ``Ctrl+K``
open the navigation as a drawer over the tabs. Whether the user wants the
docked navigation is remembered separately from whether the width allows it,
so a narrow spell never overwrites the saved preference.
"""
from typing import Callable, Optional

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QDockWidget, QMainWindow, QSizePolicy, QToolBar, QWidget

from je_auto_control.gui.adaptive.breakpoints import WidthClass, classify
from je_auto_control.gui.adaptive.glyphs import glyph_icon
from je_auto_control.gui.adaptive.overlay import OverlayDrawer
from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper
from je_auto_control.gui.navigation import NavigationPanel
from je_auto_control.gui.workspace import WorkspaceShell


def _t(key: str, default: str) -> str:
    return language_wrapper.translate(key, default)


class AdaptiveWindowLayout(QObject):
    """Owns the navigation rail and drawer and decides where each pane goes for the window's width."""

    #: Emitted with the new :class:`WidthClass` value whenever the window crosses a breakpoint.
    width_class_changed = Signal(str)
    #: Emitted whenever the navigation appears or disappears, docked or in its drawer.
    navigation_shown_changed = Signal(bool)

    def __init__(self, window: QMainWindow, dock: QDockWidget, workspace: WorkspaceShell,
                 make_panel: Callable[[], NavigationPanel], *, navigation_preferred: bool) -> None:
        super().__init__(window)
        self._window, self._dock, self._workspace = window, dock, workspace
        self.navigation_preferred = navigation_preferred
        self.width_class: Optional[WidthClass] = None
        self.rail = self._build_rail(window)
        self.panel = make_panel()
        self.drawer = OverlayDrawer(workspace, Qt.Edge.LeftEdge, "NavigationOverlay")
        self.drawer.set_content(self.panel)
        self.drawer.closed.connect(self._report_navigation)
        self.panel.feature_activated.connect(self._on_feature_chosen)
        dock.visibilityChanged.connect(self._on_dock_visibility)
        window.installEventFilter(self)
        self.update(window.width())

    # --- the rail ---------------------------------------------------------------

    def _build_rail(self, window: QMainWindow) -> QToolBar:
        rail = QToolBar(window)
        rail.setObjectName("NavigationRail")
        rail.setMovable(False)
        rail.setFloatable(False)
        rail.setOrientation(Qt.Orientation.Vertical)
        rail.setIconSize(QSize(20, 20))
        rail.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        rail.toggleViewAction().setVisible(False)
        self.menu_action = QAction(rail)
        self.menu_action.triggered.connect(self.toggle_navigation)
        self.search_action = QAction(rail)
        self.search_action.triggered.connect(self.reveal_search)
        self.details_action = QAction(rail)
        # Bound methods rather than lambdas over ``self``: a closure freed while Qt
        # tears the window down at exit can drop a last reference shiboken then
        # double-deletes (see ScrollableTabs._install_close_button).
        self.details_action.triggered.connect(self._toggle_details)
        rail.addAction(self.menu_action)
        rail.addAction(self.search_action)
        spacer = QWidget(rail)
        spacer.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        rail.addWidget(spacer)
        rail.addAction(self.details_action)
        window.addToolBar(Qt.ToolBarArea.LeftToolBarArea, rail)
        rail.hide()
        self.retranslate()
        return rail

    def set_glyph_colour(self, colour: str) -> None:
        """Redraw the rail's icons in ``colour`` (called when the theme changes)."""
        for action, name in ((self.menu_action, "menu"), (self.search_action, "search"),
                             (self.details_action, "details")):
            action.setIcon(glyph_icon(name, colour))

    def retranslate(self) -> None:
        """Re-read the rail's tooltips and the drawer panel's texts in the active language."""
        for action, key, default in (
                (self.menu_action, "menu_view_sidebar", "Navigation Panel"),
                (self.search_action, "menu_view_search", "Search Features..."),
                (self.details_action, "workspace_details_title", "Execution details")):
            text = _t(key, default)
            action.setText(text)
            action.setToolTip(text)
        panel = getattr(self, "panel", None)
        if panel is not None:
            panel.retranslate()

    # --- width classes ------------------------------------------------------------

    @property
    def compact(self) -> bool:
        """Whether the window is in its one-pane arrangement."""
        return self.width_class is WidthClass.COMPACT

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802  # reason: Qt override
        """Re-classify the window on every resize."""
        if watched is self._window and event.type() == QEvent.Type.Resize:
            self.update(self._window.width())
        return False

    def update(self, width: int) -> None:
        """Rearrange the panes if ``width`` puts the window in a different class."""
        new = classify(max(0, width), self.width_class)
        if new is self.width_class:
            return
        self.width_class = new
        compact = new is WidthClass.COMPACT
        self.rail.setVisible(compact)
        self._dock.setVisible(self.navigation_preferred and not compact)
        if not compact:
            self.drawer.hide()
        self._workspace.set_details_overlay(new is not WidthClass.EXPANDED)
        self.width_class_changed.emit(new.value)
        self._report_navigation()

    # --- navigation ----------------------------------------------------------------

    def navigation_shown(self) -> bool:
        """Whether the feature list is on screen, docked or in its drawer."""
        return self.drawer.is_open if self.compact else not self._dock.isHidden()

    def set_navigation_preferred(self, visible: bool) -> None:
        """Record whether the docked navigation is wanted; show or hide it if the width allows docking."""
        self.navigation_preferred = visible
        if not self.compact:
            self._dock.setVisible(visible)
        self._report_navigation()

    def toggle_navigation(self) -> None:
        """``Ctrl+B``: open or close the drawer when compact, otherwise show or hide the docked panel."""
        if self.compact:
            if self.drawer.is_open:
                self.drawer.close_drawer()
            else:
                self.drawer.open_drawer()
                self.panel.tree.setFocus()
                self._report_navigation()
            return
        self.set_navigation_preferred(self._dock.isHidden())

    def reveal_search(self) -> NavigationPanel:
        """Show the feature list wherever it lives at this width and return the panel whose search to focus."""
        if self.compact:
            self.drawer.open_drawer()
            self.panel.focus_search()
            self._report_navigation()
            return self.panel
        self.set_navigation_preferred(True)
        docked = self._dock.widget()
        if isinstance(docked, NavigationPanel):
            docked.focus_search()
            return docked
        return self.panel

    def _toggle_details(self) -> None:
        self._workspace.set_details_visible(not self._workspace.details_visible())

    def _on_dock_visibility(self, _visible: bool) -> None:
        self._report_navigation()

    def _on_feature_chosen(self, _key: str) -> None:
        self.drawer.close_drawer()

    def _report_navigation(self) -> None:
        self.navigation_shown_changed.emit(self.navigation_shown())
