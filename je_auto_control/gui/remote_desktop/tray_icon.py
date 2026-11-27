"""System-tray icon for the WebRTC host.

Lets users keep the host process running in the background without a
visible window. Icon colour reflects host state (idle / running /
viewer-connected). Right-click menu exposes Open / Stop / Quit.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from je_auto_control.gui.remote_desktop._helpers import _t


def _build_icon(color_hex: str) -> QIcon:
    """Generate a simple coloured circle icon programmatically."""
    pix = QPixmap(64, 64)
    pix.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pix)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(color_hex))
        painter.setPen(QColor("#222"))
        painter.drawEllipse(8, 8, 48, 48)
    finally:
        painter.end()
    return QIcon(pix)


def _tray_tip(sessions: int) -> str:
    """The tray tooltip for ``sessions`` connected viewers, in the active language."""
    return _t("rd_webrtc_tray_running").format(n=sessions) if sessions else _t("rd_webrtc_tray_idle")


class HostTrayIcon(QObject):
    """Wraps QSystemTrayIcon with state-driven colour + menu."""

    open_requested = Signal()
    stop_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._tray = QSystemTrayIcon(_build_icon("#888"), parent)
        self._sessions = 0
        self._tray.setToolTip(_tray_tip(self._sessions))
        self._tray.activated.connect(self._on_activated)
        self._menu = QMenu()
        self._actions: list[tuple[QAction, str]] = []
        self._build_menu()
        self._tray.show()

    def _build_menu(self) -> None:
        for key, signal in (("rd_webrtc_tray_open", self.open_requested), ("rd_webrtc_tray_stop", self.stop_requested),
                            ("rd_webrtc_tray_quit", self.quit_requested)):
            if key == "rd_webrtc_tray_quit":
                self._menu.addSeparator()
            action = QAction(_t(key), self._menu)
            action.triggered.connect(signal.emit)
            self._menu.addAction(action)
            self._actions.append((action, key))
        self._tray.setContextMenu(self._menu)

    def retranslate(self) -> None:
        """Show the menu and the tooltip for the current session count in the active language."""
        for action, key in self._actions:
            action.setText(_t(key))
        self._tray.setToolTip(_tray_tip(self._sessions))

    def set_state(self, *, sessions: int) -> None:
        """Reflect host state via icon colour + tooltip."""
        if sessions == 0:
            color = "#888"
        elif sessions <= 3:
            color = "#3a9c3a"
        else:
            color = "#c97a00"
        self._sessions = sessions
        self._tray.setIcon(_build_icon(color))
        self._tray.setToolTip(_tray_tip(sessions))

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.open_requested.emit()

    def set_hosting(self, hosting: bool) -> None:
        """Keep the application running without a window while a host runs.

        Closing the last window quits the application again once the host
        stops. Installing the tray used to switch that off for good, so
        closing the main window left the process running with no host.
        """
        QApplication.setQuitOnLastWindowClosed(not hosting)

    def hide(self) -> None:
        self._tray.hide()


def install_host_tray(*, on_open: Callable[[], None], on_stop: Callable[[], None],
                      on_quit: Callable[[], None],
                      parent: Optional[QObject] = None) -> Optional[HostTrayIcon]:
    """Build a tray icon if the system supports it; return None otherwise."""
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return None
    tray = HostTrayIcon(parent=parent)
    tray.open_requested.connect(on_open)
    tray.stop_requested.connect(on_stop)
    tray.quit_requested.connect(on_quit)
    return tray


__all__ = ["HostTrayIcon", "install_host_tray"]
