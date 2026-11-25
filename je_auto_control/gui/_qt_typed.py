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
* A table refilled while a row is selected keeps the row *number*, so the next
  command went to whichever record had moved there. :func:`kept_selection`
  keeps the record.
* ``Qt.convertFromPlainText`` turns text that looks like markup into markup
  that shows it. :func:`as_plain` does so only for text Qt would render.
"""
from contextlib import contextmanager
from typing import Iterator, Optional, Sequence, Tuple, cast

from PySide6.QtCore import QItemSelection, QItemSelectionModel, Qt
from PySide6.QtGui import QImage
from PySide6.QtGui import Qt as GuiQt
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


def as_plain(text: str) -> str:
    """``text`` for a widget that guesses its format: shown as typed, never rendered (no remote markup or images)."""
    if not GuiQt.mightBeRichText(text):
        return text
    return str(GuiQt.convertFromPlainText(text))


_RowKey = Tuple[object, ...]


def _row_key(table: QTableWidget, row: int, columns: Sequence[int]) -> Optional[_RowKey]:
    """What identifies ``row``'s record: its cells' user data, or their text; ``None`` without such a row."""
    parts: list[object] = []
    for column in columns:
        item = table.item(row, column)
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        parts.append(item.text() if data is None else data)
    return tuple(parts)


@contextmanager
def kept_selection(table: QTableWidget, *columns: int) -> Iterator[None]:
    """Keep the selected and current rows on their records while the body refills ``table``.

    ``columns`` hold what identifies a record (the first one by default). A
    record that is gone leaves nothing selected, rather than the row that
    moved into its place.
    """
    key_columns = columns or (0,)
    selected = {(_row_key(table, index.row(), key_columns), index.row(), index.column())
                for index in table.selectedIndexes()}
    row, column = table.currentRow(), table.currentColumn()
    current = _row_key(table, row, key_columns)
    yield
    rows = {_row_key(table, index, key_columns): index for index in range(table.rowCount())}
    records = {(current, row)} | {(key, old_row) for key, old_row, _column in selected}
    if any(rows.get(key, -1) != old_row for key, old_row in records):
        _select_cells(table, rows.get(current, -1), column,
                      [(rows[key], old_column) for key, _row, old_column in selected if key in rows])


def _select_cells(table: QTableWidget, current_row: int, current_column: int,
                 cells: Sequence[Tuple[int, int]]) -> None:
    """Make exactly ``cells`` selected and the current cell the given one (none for row -1)."""
    model, selection = table.model(), QItemSelection()
    for row, column in cells:
        index = model.index(row, column)
        selection.select(index, index)
    chosen = table.selectionModel()
    chosen.setCurrentIndex(model.index(current_row, current_column), QItemSelectionModel.SelectionFlag.NoUpdate)
    chosen.select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)


__all__ = ["as_plain", "as_widget", "decoded_image", "filled_item", "kept_selection"]
