"""Configured application workspace preserving the embedded-widget entry point."""
from typing import Any, Dict

from PySide6.QtCore import Signal, QObject
from PySide6.QtGui import QKeyEvent, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from je_auto_control.gui._tab_task import stop_all_script_runs
from je_auto_control.gui.tab_registry import TAB_SPECS, TabEntry, TabRegistry, lazy_factory
from je_auto_control.gui.workspace import WorkspaceShell

_TabEntry = TabEntry


class _WorkerSignals(QObject):
    finished = Signal(str)
    error = Signal(str)


class AutoControlGUIWidget(WorkspaceShell):
    """Configure the standard feature registry while preserving embedding APIs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        self._tab_entries: list[TabEntry] = []
        super().__init__(TabRegistry(self._tab_entries), parent)
        own_tabs = self._own_tab_builders()
        for spec in TAB_SPECS:
            builder, actions = own_tabs.get(spec.key, (None, ()))
            self._add_tab(spec.key, spec.title_key,
                          builder or lazy_factory(spec.module, spec.class_name),
                          category=spec.category, default_visible=spec.default_visible, actions=actions)

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
