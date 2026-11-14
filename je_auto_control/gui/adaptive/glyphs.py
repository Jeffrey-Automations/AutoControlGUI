"""Small line icons drawn in code, so the navigation rail ships no image files and follows the theme."""
from typing import Callable, Dict

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

_Painter = Callable[[QPainter, float], None]


def _menu(painter: QPainter, side: float) -> None:
    for fraction in (0.3, 0.5, 0.7):
        painter.drawLine(QPointF(side * 0.2, side * fraction), QPointF(side * 0.8, side * fraction))


def _search(painter: QPainter, side: float) -> None:
    painter.drawEllipse(QRectF(side * 0.2, side * 0.2, side * 0.42, side * 0.42))
    painter.drawLine(QPointF(side * 0.57, side * 0.57), QPointF(side * 0.8, side * 0.8))


def _details(painter: QPainter, side: float) -> None:
    painter.drawRoundedRect(QRectF(side * 0.18, side * 0.22, side * 0.64, side * 0.56), side * 0.06, side * 0.06)
    painter.drawLine(QPointF(side * 0.58, side * 0.22), QPointF(side * 0.58, side * 0.78))


def _chevron_down(painter: QPainter, side: float) -> None:
    painter.drawPolyline([QPointF(side * 0.25, side * 0.38), QPointF(side * 0.5, side * 0.63),
                          QPointF(side * 0.75, side * 0.38)])


def _chevron_up(painter: QPainter, side: float) -> None:
    painter.drawPolyline([QPointF(side * 0.25, side * 0.62), QPointF(side * 0.5, side * 0.37),
                          QPointF(side * 0.75, side * 0.62)])


GLYPHS: Dict[str, _Painter] = {
    "menu": _menu, "search": _search, "details": _details,
    "chevron_down": _chevron_down, "chevron_up": _chevron_up,
}


def glyph_pixmap(name: str, colour: str, side: int = 20, scale: float = 1.0) -> QPixmap:
    """The glyph ``name`` stroked in ``colour`` on a transparent ``side``-pixel square at ``scale``."""
    paint = GLYPHS[name]
    pixmap = QPixmap(round(side * scale), round(side * scale))
    pixmap.setDevicePixelRatio(scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    pen = QPen(QColor(colour), max(1.5, side / 12))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        paint(painter, float(side))
    finally:
        painter.end()
    return pixmap


def glyph_icon(name: str, colour: str, side: int = 20) -> QIcon:
    """An icon holding the glyph at 1x, 2x and 3x, which Qt picks by screen scale."""
    icon = QIcon()
    for scale in (1.0, 2.0, 3.0):
        icon.addPixmap(glyph_pixmap(name, colour, side, scale))
    return icon
