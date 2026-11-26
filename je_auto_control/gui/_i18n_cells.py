"""Table and list cells whose text comes from the catalogue, shown again in the new language on a switch.

A cell that holds data (an id, a path, a count) is set as usual. A cell whose
text is a translated word -- a status, a yes/no, a kind -- is set through
:func:`keyed_cell` or :func:`set_keyed`, which keep the catalogue key and its
fields on the item itself. :func:`retranslate_cells` then renders every such
cell of a table or list again from what the item holds: the rows, their order,
the selection and the sort stay as they are, and nothing is listed or queried
again. ``TranslatableMixin._tr_cells(view)`` registers a view so the owner's
``retranslate`` does this itself.
"""
from typing import Callable, Dict, List, Optional, Tuple, Union

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem

from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper

Cell = Union[QTableWidgetItem, QListWidgetItem]
CellView = Union[QTableWidget, QListWidget]

#: The item data role that holds a cell's renderers; far above the roles tabs use for their own data.
CELL_TEXTS_ROLE = int(Qt.ItemDataRole.UserRole) + 0x7A1


class _CellTexts:
    """The renderers of one cell, by the role each one sets (display text, tooltip), with what each showed last."""

    __slots__ = ("renders",)

    def __init__(self) -> None:
        self.renders: Dict[int, Tuple[Callable[[], str], str]] = {}

    def render(self, item: Cell, role: int) -> None:
        """Show ``role`` again, unless something set it since: a text written over the key is left alone."""
        render, shown = self.renders[role]
        if item.data(role) != shown:
            del self.renders[role]
            return
        text = render()
        self.renders[role] = (render, text)
        item.setData(role, text)


def render_key(key: str, **fields: object) -> Callable[[], str]:
    """A renderer that reads ``key`` in the active language and fills each ``{field}``."""
    def render() -> str:
        text = language_wrapper.translate(key, key)
        for name, value in fields.items():
            text = text.replace("{" + name + "}", str(value))
        return text
    return render


def set_rendered(item: Cell, render: Callable[[], str],
                 role: Qt.ItemDataRole = Qt.ItemDataRole.DisplayRole) -> Cell:
    """Set ``role`` of ``item`` to what ``render`` returns, now and on every :func:`retranslate_cells`."""
    texts = item.data(CELL_TEXTS_ROLE)
    if not isinstance(texts, _CellTexts):
        texts = _CellTexts()
    text = render()
    texts.renders[int(role)] = (render, text)
    item.setData(CELL_TEXTS_ROLE, texts)
    item.setData(role, text)
    return item


def set_keyed(item: Cell, key: str, role: Qt.ItemDataRole = Qt.ItemDataRole.DisplayRole,
              **fields: object) -> Cell:
    """Set ``role`` of ``item`` from ``key`` with its ``{field}`` values, now and on every re-render."""
    return set_rendered(item, render_key(key, **fields), role)


def keyed_cell(key: str, **fields: object) -> QTableWidgetItem:
    """A table item showing ``key`` with its ``{field}`` values, which :func:`retranslate_cells` re-renders."""
    item = QTableWidgetItem()
    set_rendered(item, render_key(key, **fields))
    return item


def _items(view: CellView) -> List[Optional[Cell]]:
    if isinstance(view, QListWidget):
        return [view.item(row) for row in range(view.count())]
    return [view.item(row, column) for row in range(view.rowCount()) for column in range(view.columnCount())]


def retranslate_cells(view: CellView) -> int:
    """Render every keyed cell of ``view`` again in the active language; return how many were rendered.

    The items are collected before any is changed, so a sorted table moving a
    row while it re-sorts neither skips nor repeats one, and ``itemChanged``
    stays quiet: no handler of the owner takes a language switch for an edit.
    """
    rendered = 0
    blocked = view.blockSignals(True)
    try:
        for item in _items(view):
            texts = None if item is None else item.data(CELL_TEXTS_ROLE)
            if item is None or not isinstance(texts, _CellTexts):
                continue
            for role in list(texts.renders):
                texts.render(item, role)
            rendered += 1
    finally:
        view.blockSignals(blocked)
    return rendered


__all__ = ["CELL_TEXTS_ROLE", "keyed_cell", "render_key", "retranslate_cells", "set_keyed", "set_rendered"]
