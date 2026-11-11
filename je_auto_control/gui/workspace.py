"""Registry-owned tab workspace with scrollable pages and passive execution details."""
import weakref
from typing import Any, Callable, List, Optional

from PySide6.QtCore import QPointF, Qt, QObject, QMetaObject, Signal, Slot
from PySide6.QtGui import QPaintEvent, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QScrollArea, QTabBar, QTabWidget, QWidget, QSplitter, QVBoxLayout

from je_auto_control.gui._i18n_helpers import TranslatableMixin
from je_auto_control.gui.tab_registry import MenuActions, TabEntry, TabRegistry, WidgetFactory
from je_auto_control.gui.workspace_details import ExecutionDetails, ExecutionDetailsPane, ExecutionDetailsSource

from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper


class _CloseButton(QAbstractButton):
    """Paint a palette-aware vector cross without loading an image asset."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedSize(20, 20)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.retranslate()

    def retranslate(self) -> None:
        """Refresh the accessible label and tooltip in the active language."""
        self.setAccessibleName(language_wrapper.translate("close_tab", "Close tab"))
        self.setToolTip(self.accessibleName())

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802  # reason: Qt override
        """Draw the close cross and keyboard focus indicator."""
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            colour = self.palette().highlight().color() if self.underMouse() else self.palette().text().color()
            painter.setPen(QPen(colour, 1.6))
            painter.drawLine(QPointF(6, 6), QPointF(14, 14))
            painter.drawLine(QPointF(14, 6), QPointF(6, 14))
            if self.hasFocus():
                painter.drawRoundedRect(2, 2, 16, 16, 3, 3)
        finally:
            painter.end()


class ScrollableTabs(QTabWidget):
    """Wrap pages in scroll areas while returning original pages to callers.

    ``widget``, ``currentWidget``, ``indexOf`` and ``setCurrentWidget`` retain
    the original page identity used by embedders and the tab registry.
    Removing a page keeps it owned by this widget for subsequent reopening.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTabsClosable(True)

    def scroll_area(self, index: int) -> QScrollArea | None:
        """Return the scroll container for a page, or None for an invalid index."""
        container = super().widget(index)
        return container if isinstance(container, QScrollArea) else None

    def widget(self, index: int) -> QWidget | None:
        """Return the original page at index."""
        container = self.scroll_area(index)
        return container.widget() if container is not None else None

    def currentWidget(self) -> QWidget | None:  # type: ignore[override]  # noqa: N802  # reason: Qt override; None with no page open
        """Return the original active page."""
        return self.widget(self.currentIndex())

    def indexOf(self, widget: QWidget) -> int:  # noqa: N802  # reason: Qt override
        """Find an original page without exposing its scroll container."""
        return next((index for index in range(self.count()) if self.widget(index) is widget), -1)

    def setCurrentWidget(self, widget: QWidget) -> None:  # noqa: N802  # reason: Qt override
        """Select an original page when it belongs to this tab widget."""
        index = self.indexOf(widget)
        if index >= 0:
            self.setCurrentIndex(index)

    def addTab(self, widget: QWidget, *args: Any) -> int:  # noqa: N802  # reason: Qt overloads
        """Append a page, accepting Qt's title and optional icon arguments."""
        return self.insertTab(self.count(), widget, *args)

    def insertTab(self, index: int, widget: QWidget, *args: Any) -> int:  # noqa: N802  # reason: Qt overloads
        """Insert a scrollable page and a vector close button."""
        container = QScrollArea(self)
        container.setWidgetResizable(True)
        container.setFrameShape(QScrollArea.Shape.NoFrame)
        container.setWidget(widget)
        result = super().insertTab(index, container, *args)
        self._install_close_button(result, widget)
        return result

    def _install_close_button(self, index: int, widget: QWidget) -> None:
        tab_bar = self.tabBar()
        for side in (QTabBar.ButtonPosition.LeftSide, QTabBar.ButtonPosition.RightSide):
            old_button = tab_bar.tabButton(index, side)
            if old_button is not None:
                tab_bar.setTabButton(index, side, None)
                old_button.deleteLater()
        button = _CloseButton(tab_bar)
        button.clicked.connect(lambda: self.tabCloseRequested.emit(self.indexOf(widget)))
        tab_bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, button)

    def replace_page(self, old: QWidget, new: QWidget) -> bool:
        """Put ``new`` in ``old``'s place, keeping the tab's index, title and selection.

        ``old`` is detached but not deleted. ``False`` when ``old`` is not a page here.
        """
        index = self.indexOf(old)
        container = self.scroll_area(index) if index >= 0 else None
        if container is None:
            return False
        detached = container.takeWidget()
        if detached is not None:
            detached.setParent(None)
        container.setWidget(new)
        self._install_close_button(index, new)
        return True

    def removeTab(self, index: int) -> None:  # noqa: N802  # reason: Qt override
        """Remove the scroll container while retaining ownership of its page."""
        container = self.scroll_area(index)
        if container is None:
            return
        page = container.takeWidget()
        if page is not None:
            page.setParent(self)
            page.hide()
        super().removeTab(index)
        container.setParent(None)
        container.deleteLater()

    def clear(self) -> None:
        """Remove every tab while keeping its original page alive."""
        while self.count():
            self.removeTab(self.count() - 1)

    def retranslate(self) -> None:
        """Refresh the labels of the visible close buttons."""
        for index in range(self.count()):
            button = self.tabBar().tabButton(index, QTabBar.ButtonPosition.RightSide)
            if isinstance(button, _CloseButton):
                button.retranslate()


class _UnbuiltPage(QWidget):
    """Stands in the tab bar for a start-up tab that has not been built yet."""

    def __init__(self, key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tab_key = key


class WorkspaceShell(TranslatableMixin, QWidget):
    """Present one supplied tab registry and the active page's execution details.

    Of the tabs registered as open at start-up, only the first is built then;
    each of the others shows an empty stand-in until it is selected or its
    widget is asked for, and is built in that tab's place at that moment.
    Remote Desktop alone took about 0.9 s of the start-up.
    """

    tabs_changed = Signal()
    current_tab_changed = Signal()
    details_visibility_changed = Signal(bool)

    def __init__(self, registry: TabRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tr_init()
        self.tab_registry = registry
        self._unbuilt: dict[str, _UnbuiltPage] = {}
        self.tabs = ScrollableTabs()
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setMinimumSize(360, 240)
        self.tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        self.details = ExecutionDetailsPane()
        self._details_source: weakref.ReferenceType[ExecutionDetailsSource] | None = None
        self._details_connection: QMetaObject.Connection | None = None
        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._splitter.addWidget(self.tabs)
        self._splitter.addWidget(self.details)
        self._splitter.setCollapsible(0, False)
        self._splitter.setStretchFactor(0, 1)
        self.details.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._splitter)
        owner = weakref.ref(self)

        def closed(page: QWidget) -> None:
            shell = owner()
            if shell is not None:
                shell._detach_closed_tab(page)
        self.destroyed.connect(registry.subscribe_close(closed))
        self.tabs.currentChanged.connect(self._on_current_tab_changed)
        for entry in registry.entries:
            if entry.default_visible:
                self.show_tab(entry.key)
        self._bind_details()

    def set_details_visible(self, visible: bool) -> None:
        """Expand or collapse execution details without starting any work."""
        self.details.setVisible(visible)
        if visible:
            self._splitter.setSizes([max(360, self.width() - 260), 260])
        self.details_visibility_changed.emit(visible)

    def _bind_details(self) -> None:
        if self._details_connection is not None:
            QObject.disconnect(self._details_connection)
            self._details_connection = None
        self._details_source = None
        page = self.tabs.currentWidget()
        source = None if page is None else page.findChild(
            ExecutionDetailsSource, options=Qt.FindChildOption.FindDirectChildrenOnly,
        )
        if source is None:
            self.details.display(None, selected=page is not None)
        else:
            self._details_source = weakref.ref(source)
            self._details_connection = source.changed.connect(self._on_details_changed)
            self.details.display(source.snapshot, selected=True)

    @Slot(object)
    def _on_details_changed(self, snapshot: ExecutionDetails) -> None:
        source = None if self._details_source is None else self._details_source()
        if source is not None and self.sender() is source:
            self.details.display(snapshot, selected=True)

    def _add_tab(
            self, key: str, title_key: str, widget: QWidget | WidgetFactory,
            category: str = "core", default_visible: bool = False,
            actions: MenuActions = (),
    ) -> None:
        """Register a tab from a widget, or from a factory called on first open."""
        if isinstance(widget, QWidget):
            built = widget
            entry = TabEntry(key=key, title_key=title_key, factory=lambda: built,
                             category=category, default_visible=default_visible, actions=actions,
                             retain_on_close=True)
        else:
            owner = weakref.ref(self)

            def adopt(page: QWidget) -> None:
                shell = owner()
                if shell is not None:
                    shell._adopt_built_page(key, page)
            entry = TabEntry(key=key, title_key=title_key, factory=widget,
                             category=category, default_visible=default_visible, actions=actions,
                             retain_on_close=False,
                             on_build=adopt)
        self.tab_registry.add(entry)
        title = language_wrapper.translate(title_key, title_key)
        if default_visible and not isinstance(widget, QWidget) and self.tabs.count() > 0:
            self._unbuilt[key] = page = _UnbuiltPage(key)
            self.tabs.addTab(page, title)
        elif default_visible:
            self.tabs.addTab(entry.widget, title)
        elif isinstance(widget, QWidget):
            WorkspaceShell._adopt_hidden_tab(self, entry.widget)

    def _adopt_built_page(self, key: str, page: QWidget) -> None:
        """Seat a newly built page in its stand-in's tab, or keep it hidden and owned."""
        stand_in = self._unbuilt.pop(key, None)
        if stand_in is not None and self.tabs.replace_page(stand_in, page):
            stand_in.deleteLater()
            return
        self._adopt_hidden_tab(page)

    def _drop_unbuilt(self, key: str) -> bool:
        """Close a start-up tab that was never built; ``False`` when ``key`` has none."""
        stand_in = self._unbuilt.pop(key, None)
        if stand_in is None:
            return False
        index = self.tabs.indexOf(stand_in)
        if index != -1:
            self.tabs.removeTab(index)
        stand_in.deleteLater()
        self.tabs_changed.emit()
        return True

    def _adopt_hidden_tab(self, widget: QWidget) -> None:
        # Owned from the start: an unparented hidden tab outlived this
        # widget, and one a registry held a listener of (Presence) kept
        # its timer running after every window that built it was gone.
        if self.tabs.indexOf(widget) == -1:
            widget.setParent(self)
            widget.hide()

    @staticmethod
    def _is_built(entry: Any) -> bool:
        return bool(getattr(entry, "built", True))

    def _built_entries(self) -> List[Any]:
        return [entry for entry in self.tab_registry.entries if self._is_built(entry)]

    def _is_open(self, entry: Any) -> bool:
        if entry.key in self._unbuilt:
            return True
        return self._is_built(entry) and self.tabs.indexOf(entry.widget) != -1

    def _on_current_tab_changed(self, _index: int) -> None:
        page = self.tabs.currentWidget()
        if isinstance(page, _UnbuiltPage):
            self.tab_registry.open(page.tab_key)   # builds it into the stand-in's place
        self._bind_details()
        self.current_tab_changed.emit()

    def current_tab_menu_actions(self) -> list[tuple[str, Callable[[], Any]]]:
        """Return ``[(label_key, callable), ...]`` for the active tab.

        Core tabs declare their actions at registration time; feature tabs
        may instead expose a ``menu_actions()`` method returning the same
        shape. The menu bar renders these under the Actions menu so tabs
        stay button-free.
        """
        widget = self.tabs.currentWidget()
        if widget is None:
            return []
        for entry in self._built_entries():
            if entry.widget is widget:
                if entry.actions:
                    return list(entry.actions)
                provider = getattr(widget, "menu_actions", None)
                if callable(provider):
                    return list(provider())
                return []
        return []

    def _find_entry(self, key: str) -> TabEntry | None:
        for entry in self.tab_registry.entries:
            if entry.key == key:
                return entry
        return None

    def sync_engine_tabs(self) -> None:
        """Let every built tab that mirrors an engine re-read its state (after Tools > Start).

        A tab not built yet reads the engine when it is.
        """
        for entry in self.tab_registry.entries:
            if not WorkspaceShell._is_built(entry):
                continue
            sync = getattr(entry.widget, "sync_with_engine", None)
            if callable(sync):
                sync()

    def list_registered_tabs(self) -> list[dict[str, Any]]:
        """Return metadata for the View → Tabs menu and the navigation panel.

        Reading it builds nothing: a tab never opened is listed as not visible.
        """
        return [
            {
                "key": entry.key,
                "title": language_wrapper.translate(entry.title_key, entry.title_key),
                "visible": self._is_open(entry),
                "category": entry.category,
            }
            for entry in self.tab_registry.entries
        ]

    def current_tab_key(self) -> Optional[str]:
        """Key of the tab on screen, or ``None`` when every tab is closed."""
        widget = self.tabs.currentWidget()
        if isinstance(widget, _UnbuiltPage):
            return widget.tab_key
        for entry in self._built_entries():
            if entry.widget is widget:
                return str(entry.key)
        return None

    def show_tab(self, key: str) -> None:
        """Open the tab ``key`` (building it if this is its first time) and select it."""
        entry = self._find_entry(key)
        if entry is None or self._is_open(entry):
            return
        target_index = 0
        for candidate in self.tab_registry.entries:
            if candidate.key == key:
                break
            if self._is_open(candidate):
                target_index += 1
        title = language_wrapper.translate(entry.title_key, entry.title_key)
        page = self.tab_registry.open(key)
        self.tabs.insertTab(target_index, page, title)
        self.tabs.setCurrentWidget(page)
        self.tabs_changed.emit()

    def activate_tab(self, key: str) -> bool:
        """Bring the tab ``key`` to the front, opening it first if needed."""
        entry = self._find_entry(key)
        if entry is None:
            return False
        if self._is_open(entry):
            self.tabs.setCurrentWidget(entry.widget)
        else:
            self.show_tab(key)
        return True

    def hide_tab(self, key: str) -> None:
        """Close the tab ``key``; its widget is kept for the next time it is opened."""
        entry = self._find_entry(key)
        if entry is None or self._drop_unbuilt(key) or not self._is_built(entry):
            return
        index = self.tabs.indexOf(entry.widget)
        if index != -1:
            self.tabs.removeTab(index)
            self.tabs_changed.emit()

    def _on_tab_close_requested(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if isinstance(widget, _UnbuiltPage):
            self._drop_unbuilt(widget.tab_key)
            return
        for entry in self._built_entries():
            if entry.widget is widget:
                self.close_tab(entry.key)
                return

    def close_tab(self, key: str) -> None:
        """Release a feature and its page-owned resources.

        Unlike ``hide_tab``, closing a feature discards its local UI state and
        schedules cleanup of subscriptions and timers. Reopening rebuilds it.
        Remote Desktop keeps registry-owned sessions while retiring its view callbacks.
        A start-up tab that was never built just leaves the tab bar.
        """
        if not self._drop_unbuilt(key):
            self.tab_registry.close(key)

    def _detach_closed_tab(self, page: QWidget) -> None:
        """Remove a closed page before its deferred Qt destruction."""
        index = self.tabs.indexOf(page)
        if index != -1:
            self.tabs.removeTab(index)
        self.tabs_changed.emit()

    def _translate(self, key: str) -> str:
        return language_wrapper.translate(key, key)

    def retranslate(self) -> None:
        """Relabel tab titles and propagate into every child tab."""
        self.tabs.retranslate()
        self.details.retranslate()
        for entry in self.tab_registry.entries:
            stand_in = self._unbuilt.get(entry.key)
            if stand_in is None and not self._is_built(entry):
                continue
            index = self.tabs.indexOf(stand_in if stand_in is not None else entry.widget)
            if index != -1:
                self.tabs.setTabText(
                    index, language_wrapper.translate(entry.title_key, entry.title_key),
                )
        TranslatableMixin.retranslate(self)
        # Child class tabs get their own retranslate if they implement one.
        for entry in self._built_entries():
            callback = getattr(entry.widget, "retranslate", None)
            if callable(callback) and entry.widget is not self:
                try:
                    callback()
                except (RuntimeError, AttributeError):
                    continue
