"""Fusion with check boxes and radio buttons drawn from the palette's accent.

Fusion outlines both indicators with a shade of the window colour, which on the
dark theme all but disappears (an unchecked radio button showed no ring at all).
Styling ``::indicator`` in the style sheet would fix the outline but drop the
check mark, which a style sheet can only draw from an image file. This proxy
paints both in code instead, from the widget's palette, so they follow the theme.
"""
from typing import Any, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QProxyStyle, QStyle, QStyleOption, QWidget

_INDICATORS = (QStyle.PrimitiveElement.PE_IndicatorCheckBox, QStyle.PrimitiveElement.PE_IndicatorRadioButton)


def _state(option: QStyleOption) -> Tuple[bool, bool, bool, bool]:
    flags = option.state
    checked = bool(flags & QStyle.StateFlag.State_On)
    partial = bool(flags & QStyle.StateFlag.State_NoChange)
    enabled = bool(flags & QStyle.StateFlag.State_Enabled)
    hovered = bool(flags & QStyle.StateFlag.State_MouseOver)
    return checked, partial, enabled, hovered


def _colours(option: QStyleOption, checked: bool, enabled: bool, hovered: bool) -> Tuple[QColor, QColor, QColor]:
    palette = option.palette
    accent = palette.highlight().color()
    base = palette.base().color()
    outline = palette.placeholderText().color()
    if hovered and enabled:
        outline = accent
    if not enabled:
        accent = QColor(outline)
        accent.setAlpha(140)
    return (accent if checked else outline), (accent if checked else base), palette.highlightedText().color()


def _square(rect: QRectF) -> QRectF:
    side = min(rect.width(), rect.height()) - 2
    return QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side)


def paint_indicator(painter: QPainter, option: QStyleOption, radio: bool) -> None:
    """Draw one check box or radio indicator into ``option.rect``."""
    checked, partial, enabled, hovered = _state(option)
    border, fill, mark = _colours(option, checked or partial, enabled, hovered)
    box = _square(QRectF(option.rect))
    painter.save()
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(border, 1.5))
        if radio:
            painter.setBrush(option.palette.base().color())
            painter.drawEllipse(box)
            if checked:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(fill)
                inner = box.width() * 0.25
                painter.drawEllipse(box.adjusted(inner, inner, -inner, -inner))
            return
        painter.setBrush(fill)
        painter.drawRoundedRect(box, 3, 3)
        pen = QPen(mark, max(1.6, box.width() / 8))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        left, top, side = box.left(), box.top(), box.width()
        if partial:
            painter.drawLine(QPointF(left + side * 0.28, top + side / 2), QPointF(left + side * 0.72, top + side / 2))
        elif checked:
            path = QPainterPath(QPointF(left + side * 0.24, top + side * 0.52))
            path.lineTo(QPointF(left + side * 0.43, top + side * 0.70))
            path.lineTo(QPointF(left + side * 0.76, top + side * 0.32))
            painter.drawPath(path)
    finally:
        painter.restore()


class AdaptiveStyle(QProxyStyle):
    """Fusion, with theme-coloured vector check boxes and radio buttons."""

    def __init__(self, base: str = "Fusion") -> None:
        super().__init__(base)

    def drawPrimitive(self, element: QStyle.PrimitiveElement, option: QStyleOption,  # noqa: N802  # reason: Qt override
                      painter: QPainter, widget: Optional[QWidget] = None) -> None:
        """Paint the two indicators here; leave every other element to Fusion."""
        if element in _INDICATORS:
            paint_indicator(painter, option, element == QStyle.PrimitiveElement.PE_IndicatorRadioButton)
            return
        super().drawPrimitive(element, option, painter, widget)

    def pixelMetric(self, metric: QStyle.PixelMetric, option: Any = None,  # noqa: N802  # reason: Qt override
                    widget: Optional[QWidget] = None) -> int:
        """Slightly larger indicators than Fusion's 13 px, easier to hit and to see."""
        if metric in (QStyle.PixelMetric.PM_IndicatorWidth, QStyle.PixelMetric.PM_IndicatorHeight,
                      QStyle.PixelMetric.PM_ExclusiveIndicatorWidth, QStyle.PixelMetric.PM_ExclusiveIndicatorHeight):
            return 16
        return super().pixelMetric(metric, option, widget)
