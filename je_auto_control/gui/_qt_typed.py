"""Typed accessors for what Qt's own signatures cannot express.

They exist so the GUI type-checks against the real PySide6 types
(``test/verify/typing_contract_verify.py --extras``) without a cast at every
call site:

* A tab mixin is a ``QWidget`` only once it is mixed into its host, so
  ``QMessageBox.warning(self, ...)`` inside one is a type error although it is
  correct at run time. :func:`as_widget` says so in one place.
* ``QTableWidget.item()`` may answer ``None``, but a tab that fills every cell
  of a row itself knows the cell is there. :func:`filled_item` returns the
  item, and reports a cell that is missing as the bug it would be.
* ``QImage.fromData(data, "JPEG")`` is what the binding accepts, but its stub
  types the format as bytes, which the binding rejects with ``ValueError``.
  :func:`decoded_image` decodes through ``loadFromData``, whose stub and
  binding agree on a ``str`` format.
"""
from typing import cast

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QWidget

from je_auto_control.utils.exception.exceptions import AutoControlException


def as_widget(part: object) -> QWidget:
    """``part`` as the widget it is once mixed into its host (a dialog's parent, a task's owner)."""
    return cast(QWidget, part)


def filled_item(table: QTableWidget, row: int, column: int) -> QTableWidgetItem:
    """The item of a cell the caller filled itself; raise if the cell has none."""
    item = table.item(row, column)
    if item is None:
        raise AutoControlException(f"the table has no item at row {row}, column {column}")
    return item


def decoded_image(data: bytes, image_format: str) -> QImage:
    """``data`` decoded as ``image_format`` (``"PNG"``, ``"JPEG"``); a null image when it does not decode."""
    image = QImage()
    image.loadFromData(data, image_format)
    return image


__all__ = ["as_widget", "decoded_image", "filled_item"]
