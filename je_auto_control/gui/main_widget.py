"""Workspace widget: owns the tab bar and the registry of every tab it can open."""
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Signal, QObject
from PySide6.QtGui import QKeyEvent, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel,
)

from je_auto_control.gui._tab_task import stop_all_script_runs
from je_auto_control.gui._i18n_helpers import TranslatableMixin
from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper
from je_auto_control.gui.tab_registry import (
    TAB_SPECS, MenuActions, TabEntry, TabRegistry, WidgetFactory, lazy_factory,
)
from je_auto_control.gui.workspace import ScrollableTabs

# Kept under its old name: tests and embedders read ``_tab_entries`` rows as this.
_TabEntry = TabEntry


class _WorkerSignals(QObject):
    finished = Signal(str)
    error = Signal(str)


# =============================================================================
# Main Widget
# =============================================================================
class AutoControlGUIWidget(
    TranslatableMixin,
    QWidget,
):
    """Owns the QTabWidget and exposes show/hide/list APIs for the menu bar."""

    tabs_changed = Signal()
    current_tab_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tr_init()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self._tab_entries: List[TabEntry] = []
        self.tab_registry = TabRegistry(self._tab_entries, on_close=self._detach_closed_tab)

        self.tabs = ScrollableTabs()
        self.tabs.setTabsClosable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(True)
        # Without this the widest page's minimum size is the window's: the
        # Script Builder alone kept the window from going under ~860 px.
        self.tabs.setMinimumSize(360, 240)
        self.tabs.tabCloseRequested.connect(self._on_tab_close_requested)

        # The window opens on record / script_builder / remote_desktop. Every
        # other tab is registered but not built: its module is imported and
        # its widget constructed the first time it is opened, from the
        # navigation panel or the View menu.
        own_tabs = self._own_tab_builders()
        for spec in TAB_SPECS:
            builder, actions = own_tabs.get(spec.key, (None, ()))
            self._add_tab(spec.key, spec.title_key,
                          builder or lazy_factory(spec.module, spec.class_name),
                          category=spec.category, default_visible=spec.default_visible, actions=actions)
        layout.addWidget(self.tabs)

        self.setLayout(layout)

        self.tabs.currentChanged.connect(self._on_current_tab_changed)


    def _own_tab_builders(self) -> Dict[str, Any]:
        """Remote Desktop keeps its existing optional-dependency fallback."""
        return {"remote_desktop": (self._build_remote_desktop_tab, ())}

    @staticmethod
    def _build_remote_desktop_tab() -> QWidget:
        """Return the real remote-desktop tab, or a placeholder if the
        ``webrtc`` extra is not installed.

        Remote desktop relies on the optional ``webrtc`` extra (aiortc + PyAV);
        embedders such as PyBreeze install je_auto_control without it, so a
        failed import becomes a tab that says how to enable it.
        """
        try:
            from je_auto_control.gui.remote_desktop_tab import RemoteDesktopTab
        except ImportError as error:
            import_error: ImportError = error
        else:
            return RemoteDesktopTab()
        placeholder = QWidget()
        layout = QVBoxLayout(placeholder)
        message = QLabel(
            "Remote Desktop is unavailable: the optional 'webrtc' extra "
            "(aiortc + PyAV) is not installed.\n\n"
            "Install with:\n    pip install je_auto_control[webrtc]\n\n"
            f"Underlying error: {import_error!r}",
        )
        message.setWordWrap(True)
        message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(message)
        layout.addStretch()
        return placeholder

    # --- tab registry API ----------------------------------------------------

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
            entry = TabEntry(key=key, title_key=title_key, factory=widget,
                             category=category, default_visible=default_visible, actions=actions,
                             retain_on_close=key == "remote_desktop",
                             on_build=lambda page: AutoControlGUIWidget._adopt_hidden_tab(self, page))
        self._tab_entries.append(entry)
        if default_visible:
            self.tabs.addTab(entry.widget, language_wrapper.translate(title_key, title_key))
        elif isinstance(widget, QWidget):
            AutoControlGUIWidget._adopt_hidden_tab(self, entry.widget)

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
        return [entry for entry in self._tab_entries if self._is_built(entry)]

    def _is_open(self, entry: Any) -> bool:
        return self._is_built(entry) and self.tabs.indexOf(entry.widget) != -1

    def _on_current_tab_changed(self, _index: int) -> None:
        self.current_tab_changed.emit()

    def current_tab_menu_actions(self) -> list:
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

    def _find_entry(self, key: str):
        for entry in self._tab_entries:
            if entry.key == key:
                return entry
        return None

    def sync_engine_tabs(self) -> None:
        """Let every built tab that mirrors an engine re-read its state (after Tools > Start).

        A tab not built yet reads the engine when it is.
        """
        for entry in self._tab_entries:
            if not AutoControlGUIWidget._is_built(entry):
                continue
            sync = getattr(entry.widget, "sync_with_engine", None)
            if callable(sync):
                sync()

    def list_registered_tabs(self) -> list:
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
            for entry in self._tab_entries
        ]

    def current_tab_key(self) -> Optional[str]:
        """Key of the tab on screen, or ``None`` when every tab is closed."""
        widget = self.tabs.currentWidget()
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
        for candidate in self._tab_entries:
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
        if entry is None or not self._is_built(entry):
            return
        index = self.tabs.indexOf(entry.widget)
        if index != -1:
            self.tabs.removeTab(index)
            self.tabs_changed.emit()

    def _on_tab_close_requested(self, index: int) -> None:
        widget = self.tabs.widget(index)
        for entry in self._built_entries():
            if entry.widget is widget:
                self.close_tab(entry.key)
                return

    def close_tab(self, key: str) -> None:
        """Release a feature; keep Remote Desktop reusable.

        Unlike ``hide_tab``, closing a feature discards its local UI state and
        schedules cleanup of subscriptions and timers. Reopening rebuilds it.
        Remote Desktop retains live sessions until its lifecycle is migrated.
        """
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
        for entry in self._built_entries():
            index = self.tabs.indexOf(entry.widget)
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

    def open_script_file(self, path: str) -> None:
        """Load a JSON script into the Script Executor tab and focus it."""
        if self.activate_tab("script"):
            entry = self._find_entry("script")
            if entry is not None:
                entry.widget.load_script(path)

    # =========================================================================
    # Global keyboard shortcut: Ctrl+4 to stop
    # =========================================================================
    def _stop_auto_click(self) -> None:
        entry = self._find_entry("auto_click")
        if entry is not None and entry.built:
            entry.widget.dispose()
        stop_all_script_runs()

    def keyPressEvent(self, event: QKeyEvent):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_4:
            self._stop_auto_click()
        else:
            super().keyPressEvent(event)
