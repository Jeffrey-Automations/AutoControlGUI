"""Containers that rearrange by width, and the pass that stops a page's controls from forcing it wide."""
from typing import Callable, Optional, Tuple

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QSize
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QBoxLayout, QComboBox, QFormLayout, QLabel, QLayout, QSizePolicy, QTabWidget, QWidget

#: Below this many logical pixels a :class:`ResponsiveBox` stacks its parts.
DEFAULT_STACK_BELOW = 720
#: Characters a combo box shows at its minimum; longer entries are elided, not sized for.
COMBO_MINIMUM_CHARACTERS = 14
_FITTED = "_adaptive_fitted"


class ResponsiveBox(QWidget):
    """Parts side by side when there is room, one above the other when there is not.

    ``stretches`` sets each part's share of the width when side by side; stacked,
    they share the height the same way.
    """

    def __init__(self, *parts: QWidget, stack_below: int = DEFAULT_STACK_BELOW,
                 stretches: Tuple[int, ...] = (), spacing: int = 12, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.stack_below = stack_below
        self.setProperty("role", "bare")
        self._layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(spacing)
        for index, part in enumerate(parts):
            stretch = stretches[index] if index < len(stretches) else 1
            self._layout.addWidget(part, stretch)

    @property
    def stacked(self) -> bool:
        """Whether the parts are currently one above the other."""
        return self._layout.direction() == QBoxLayout.Direction.TopToBottom

    def minimumSizeHint(self) -> QSize:  # noqa: N802  # reason: Qt override
        """Never ask for more width than the widest part needs on its own."""
        hint = super().minimumSizeHint()
        items = (self._layout.itemAt(index) for index in range(self._layout.count()))
        widest = max((item.minimumSize().width() for item in items if item is not None), default=0)
        hint.setWidth(widest)
        return hint

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802  # reason: Qt override
        """Switch between side by side and stacked as the width crosses ``stack_below``."""
        self.arrange(event.size().width())
        super().resizeEvent(event)

    def arrange(self, width: int) -> None:
        """Lay the parts out for ``width`` pixels."""
        direction = QBoxLayout.Direction.TopToBottom if width < self.stack_below \
            else QBoxLayout.Direction.LeftToRight
        if self._layout.direction() != direction:
            self._layout.setDirection(direction)


def _fit_combo(combo: QComboBox) -> None:
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(COMBO_MINIMUM_CHARACTERS)
    combo.setSizePolicy(QSizePolicy.Policy.Expanding, combo.sizePolicy().verticalPolicy())
    # The two setters above clear the cached size hint but not the cached
    # minimum size hint; only a style or font change does, so send one.
    QCoreApplication.sendEvent(combo, QEvent(QEvent.Type.StyleChange))


def _fit_layout(layout: Optional[QLayout]) -> None:
    if layout is None:
        return
    if isinstance(layout, QFormLayout):
        layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item is not None:
            _fit_layout(item.layout())


def fit_to_width(root: QWidget) -> int:
    """Let every control under ``root`` shrink with the window; return how many were adjusted.

    Combo boxes stop sizing themselves to their longest entry, form layouts
    move a label above its field when both do not fit, long labels wrap and
    nested tab widgets scroll their tab bar. Run once, after the page is
    built; a control already fitted is left alone, so calling it again is cheap.
    """
    adjusted = 0
    widgets = [root, *root.findChildren(QWidget)]
    for widget in widgets:
        if widget.property(_FITTED):
            continue
        widget.setProperty(_FITTED, True)
        _fit_layout(widget.layout())
        if isinstance(widget, QComboBox):
            _fit_combo(widget)
        elif isinstance(widget, QLabel) and not widget.wordWrap() and len(widget.text()) > 40:
            widget.setWordWrap(True)
        elif isinstance(widget, QTabWidget):
            widget.setUsesScrollButtons(True)
        else:
            continue
        adjusted += 1
    return adjusted


class WidthWatcher(QObject):
    """Call ``callback(width)`` whenever ``target`` is resized."""

    def __init__(self, target: QWidget, callback: Callable[[int], None]) -> None:
        super().__init__(target)
        self._callback = callback
        target.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802  # reason: Qt override
        """Report the new width of the watched widget."""
        if event.type() == QEvent.Type.Resize and isinstance(watched, QWidget):
            self._callback(watched.width())
        return False
