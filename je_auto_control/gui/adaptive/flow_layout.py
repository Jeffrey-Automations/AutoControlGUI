"""A layout that places items left to right and wraps them onto the next line when the row is full."""
from typing import List, Optional

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLayout, QLayoutItem, QWidget


class FlowLayout(QLayout):
    """Rows of widgets that wrap instead of forcing the page wider.

    The minimum width is the widest single item, so a row of fields and
    buttons never makes its page scroll sideways; it gets taller instead.
    """

    def __init__(self, parent: Optional[QWidget] = None, spacing: int = 8) -> None:
        super().__init__(parent)
        self._items: List[QLayoutItem] = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802  # reason: Qt override
        """Append an item (called by ``addWidget``)."""
        self._items.append(item)

    def count(self) -> int:
        """Number of items held."""
        return len(self._items)

    def itemAt(self, index: int) -> Optional[QLayoutItem]:  # noqa: N802  # reason: Qt override
        """The item at ``index``, or ``None`` past the end."""
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> Optional[QLayoutItem]:  # noqa: N802  # reason: Qt override
        """Remove and return the item at ``index``."""
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802  # reason: Qt override
        """A flow grows in neither direction by itself."""
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802  # reason: Qt override
        """Its height depends on the width it is given."""
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802  # reason: Qt override
        """Height needed to lay every item out within ``width``."""
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802  # reason: Qt override
        """Place the items inside ``rect``."""
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802  # reason: Qt override
        """Everything on one line."""
        width = sum(item.sizeHint().width() for item in self._visible())
        width += self.spacing() * max(0, len(self._visible()) - 1)
        height = max((item.sizeHint().height() for item in self._visible()), default=0)
        return QSize(width, height).grownBy(self.contentsMargins())

    def minimumSize(self) -> QSize:  # noqa: N802  # reason: Qt override
        """The largest single item: the layout never needs more width than that."""
        size = QSize()
        for item in self._visible():
            size = size.expandedTo(item.minimumSize())
        return size.grownBy(self.contentsMargins())

    def _visible(self) -> List[QLayoutItem]:
        return [item for item in self._items if (widget := item.widget()) is None or not widget.isHidden()]

    def _arrange(self, rect: QRect, *, apply: bool) -> int:
        margins: QMargins = self.contentsMargins()
        area = rect.marginsRemoved(margins)
        x, y, line_height = area.x(), area.y(), 0
        spacing = self.spacing()
        for item in self._visible():
            hint = item.sizeHint()
            width = min(hint.width(), max(item.minimumSize().width(), area.width()))
            if x > area.x() and x + width > area.right() + 1:
                x, y, line_height = area.x(), y + line_height + spacing, 0
            if apply:
                height = item.heightForWidth(width) if item.hasHeightForWidth() else hint.height()
                item.setGeometry(QRect(QPoint(x, y), QSize(width, height)))
            line_height = max(line_height, item.heightForWidth(width) if item.hasHeightForWidth() else hint.height())
            x += width + spacing
        return y + line_height - rect.y() + margins.bottom()


def field_pair(label: QWidget, field: QWidget, spacing: int = 6) -> QWidget:
    """A label and its field kept together on one line, so a flow row wraps between pairs, not inside one."""
    pair = QWidget()
    layout = QHBoxLayout(pair)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    layout.addWidget(label)
    layout.addWidget(field, 1)
    return pair


def flow_of(*widgets: QWidget, spacing: int = 12) -> FlowLayout:
    """A :class:`FlowLayout` holding ``widgets`` in order."""
    flow = FlowLayout(spacing=spacing)
    for widget in widgets:
        flow.addWidget(widget)
    return flow
