"""A drawer that slides a panel over part of a host widget, dimming the rest until it is dismissed."""
from typing import Optional

from PySide6.QtCore import QEvent, QObject, QRect, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QMouseEvent, QPainter, QPaintEvent, QShortcut
from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

#: Widest a drawer gets, and the share of the host it may cover when the host is narrower.
DRAWER_WIDTH = 320
DRAWER_SHARE = 0.85


class OverlayDrawer(QWidget):
    """Cover ``host`` with a dimming scrim and show one panel along its left or right edge.

    Escape or a click on the scrim closes it; :attr:`closed` then fires. The
    drawer keeps its geometry matched to the host's as the host is resized.
    """

    closed = Signal()

    def __init__(self, host: QWidget, side: Qt.Edge = Qt.Edge.LeftEdge, object_name: str = "") -> None:
        super().__init__(host)
        self._host = host
        self.side = side
        self.panel = QFrame(self)
        if object_name:
            self.panel.setObjectName(object_name)
        self.panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._content = QVBoxLayout(self.panel)
        self._content.setContentsMargins(0, 0, 0, 0)
        escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        escape.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        escape.activated.connect(self.close_drawer)
        host.installEventFilter(self)
        self.hide()

    @property
    def is_open(self) -> bool:
        """Whether the drawer is showing."""
        return not self.isHidden()

    def set_content(self, widget: Optional[QWidget]) -> None:
        """Make ``widget`` the panel's only content (``None`` empties it); the previous one is detached, not deleted."""
        while self._content.count():
            item = self._content.takeAt(0)
            previous = item.widget() if item is not None else None
            if previous is not None and previous is not widget:
                previous.setParent(None)
        if widget is not None:
            self._content.addWidget(widget)
            widget.show()

    def content(self) -> Optional[QWidget]:
        """The widget the panel holds, or ``None``."""
        item = self._content.itemAt(0)
        return item.widget() if item is not None else None

    def open_drawer(self) -> None:
        """Show the drawer above everything else in the host."""
        self._fit()
        self.show()
        self.raise_()

    def close_drawer(self) -> None:
        """Hide the drawer and report it."""
        if self.isHidden():
            return
        self.hide()
        self.closed.emit()

    def panel_rect(self, width: int, height: int) -> QRect:
        """Where the panel goes inside a host of ``width`` x ``height``."""
        panel_width = min(DRAWER_WIDTH, int(width * DRAWER_SHARE))
        left = 0 if self.side == Qt.Edge.LeftEdge else width - panel_width
        return QRect(left, 0, panel_width, height)

    def _fit(self) -> None:
        self.setGeometry(self._host.rect())
        self.panel.setGeometry(self.panel_rect(self._host.width(), self._host.height()))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802  # reason: Qt override
        """Follow the host's size while open."""
        if watched is self._host and event.type() == QEvent.Type.Resize and self.is_open:
            self._fit()
        return False

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802  # reason: Qt override
        """A click on the dimmed area outside the panel dismisses the drawer."""
        if not self.panel.geometry().contains(event.position().toPoint()):
            self.close_drawer()
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802  # reason: Qt override
        """Dim the host behind the panel."""
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), QColor(0, 0, 0, 96))
        finally:
            painter.end()
