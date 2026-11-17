"""A layout that places items left to right and wraps them onto the next line when the row is full."""
from typing import List, Optional, Tuple

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
        #: Height the rows took at the width last laid out; the minimum height until the width changes.
        self._wrapped_height = 0
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
        """``False`` on purpose, although the height does depend on the width.

        A page whose layout reports height-for-width is sized by
        ``QScrollArea`` from every item's *preferred* height, so a page with a
        flow row and a table scrolled even in a window it fitted. The wrapped
        height is reported as the minimum height instead (see :meth:`setGeometry`).
        """
        return False

    def heightForWidth(self, width: int) -> int:  # noqa: N802  # reason: Qt override
        """Height needed to lay every item out within ``width``."""
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802  # reason: Qt override
        """Place the items inside ``rect``; ask for a re-layout if the rows now need another height."""
        super().setGeometry(rect)
        height = self._arrange(rect, apply=True)
        if height != self._wrapped_height:
            self._wrapped_height = height
            # Posts a layout request: the parent reads the new minimum height on
            # the next pass, at the same width, so this settles after one round.
            self.invalidate()

    def sizeHint(self) -> QSize:  # noqa: N802  # reason: Qt override
        """Everything on one line, but never shorter than the rows took at the last width laid out."""
        width = sum(item.sizeHint().width() for item in self._visible())
        width += self.spacing() * max(0, len(self._visible()) - 1)
        height = max((item.sizeHint().height() for item in self._visible()), default=0)
        hint = QSize(width, height).grownBy(self.contentsMargins())
        return QSize(hint.width(), max(hint.height(), self._wrapped_height))

    def minimumSize(self) -> QSize:  # noqa: N802  # reason: Qt override
        """The largest single item's width, and the height the rows took at the last width laid out."""
        size = QSize()
        for item in self._visible():
            size = size.expandedTo(item.minimumSize())
        size = size.grownBy(self.contentsMargins())
        return QSize(size.width(), max(size.height(), self._wrapped_height))

    def _visible(self) -> List[QLayoutItem]:
        return [item for item in self._items if (widget := item.widget()) is None or not widget.isHidden()]

    def _lines(self, area: QRect) -> List[List[Tuple[QLayoutItem, int, int]]]:
        """Items grouped into lines that fit ``area``'s width, each with its width and height."""
        lines: List[List[Tuple[QLayoutItem, int, int]]] = [[]]
        x, spacing = area.x(), self.spacing()
        for item in self._visible():
            hint = item.sizeHint()
            width = min(hint.width(), max(item.minimumSize().width(), area.width()))
            if lines[-1] and x + width > area.right() + 1:
                lines.append([])
                x = area.x()
            height = item.heightForWidth(width) if item.hasHeightForWidth() else hint.height()
            lines[-1].append((item, width, height))
            x += width + spacing
        return lines

    def _share_spare_width(self, line: List[Tuple[QLayoutItem, int, int]],
                           available: int) -> List[Tuple[QLayoutItem, int, int]]:
        """Widen the items on ``line`` that can grow sideways (line edits, fitted combos) to fill it."""
        used = sum(width for _item, width, _height in line) + self.spacing() * max(0, len(line) - 1)
        growers = [index for index, (item, _w, _h) in enumerate(line)
                   if item.expandingDirections() & Qt.Orientation.Horizontal]
        spare = available - used
        widened = list(line)
        # An item capped by its maximum width hands what it cannot take to the others.
        while spare > 0 and growers:
            spare, still_growing = _grow_once(widened, growers, spare)
            if still_growing == growers:
                break
            growers = still_growing
        return widened

    def _arrange(self, rect: QRect, *, apply: bool) -> int:
        """Lay the items out in ``rect`` (when ``apply``), each centred on its line; return the height used."""
        margins: QMargins = self.contentsMargins()
        area = rect.marginsRemoved(margins)
        y, spacing = area.y(), self.spacing()
        for line in self._lines(area):
            line_height = max((height for _item, _width, height in line), default=0)
            x = area.x()
            for item, width, height in self._share_spare_width(line, area.width()):
                if apply:
                    item.setGeometry(QRect(QPoint(x, y + (line_height - height) // 2), QSize(width, height)))
                x += width + spacing
            y += line_height + spacing
        return max(0, y - spacing) - rect.y() + margins.bottom()


def _grow_once(line: List[Tuple[QLayoutItem, int, int]], growers: List[int], spare: int) -> Tuple[int, List[int]]:
    """Share ``spare`` pixels among ``growers`` once, in place; return what is left and who can still grow."""
    share, remainder = divmod(spare, len(growers))
    still_growing = []
    for position, index in enumerate(growers):
        item, width, height = line[index]
        limit = item.maximumSize().width()
        new_width = min(width + share + (1 if position < remainder else 0), limit)
        spare -= new_width - width
        if new_width > width:
            line[index] = (item, new_width, item.heightForWidth(new_width) if item.hasHeightForWidth() else height)
        if new_width < limit:
            still_growing.append(index)
    return spare, still_growing


def field_pair(label: QWidget, field: QWidget, spacing: int = 6) -> QWidget:
    """A label and its field kept together on one line, so a flow row wraps between pairs, not inside one."""
    pair = QWidget()
    pair.setProperty("role", "bare")
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
