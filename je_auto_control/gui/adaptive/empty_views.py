"""Empty tables, lists and trees say so instead of showing a blank grid.

:func:`show_empty_states` puts an :class:`~je_auto_control.gui.adaptive.surfaces.EmptyState`
over every item view on a page while the view's model has no rows, and hides
it as soon as a row arrives. The workspace runs it once on each page it opens,
after :func:`~je_auto_control.gui.adaptive.responsive.fit_to_width`. The
overlay lets the mouse through, follows the view's size, and notices a model
being replaced as well as rows being added, removed or reset.
"""
from typing import Optional

from PySide6.QtCore import QAbstractItemModel, QEvent, QObject, Qt
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QHeaderView, QWidget

from je_auto_control.gui.adaptive.surfaces import EmptyState

#: Dynamic property set on a view that already has an overlay, or that must not get one.
NO_EMPTY_STATE = "_jeNoEmptyState"

_MODEL_SIGNALS = ("rowsInserted", "rowsRemoved", "modelReset", "layoutChanged")


class _EmptyOverlay(QObject):
    """Shows ``state`` over ``view``'s viewport while the model is empty."""

    def __init__(self, view: QAbstractItemView, message_key: str, hint_key: str) -> None:
        super().__init__(view)
        self._view = view
        self._model: Optional[QAbstractItemModel] = None
        self.state = EmptyState(message_key, hint_key, view.viewport())
        self.state.setObjectName("EmptyViewState")
        self.state.hint.setWordWrap(True)
        self.state.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        view.viewport().installEventFilter(self)
        self.refresh()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802  # reason: Qt override
        """Re-place the overlay when the viewport resizes; notice a replaced model when it paints."""
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.Paint):
            if event.type() != QEvent.Type.Paint or self._view.model() is not self._model:
                self.refresh()
        return False

    def refresh(self) -> None:
        """Watch the view's current model and show the overlay only while it has no rows."""
        model = self._view.model()
        if model is not self._model:
            self._rewire(model)
        empty = model is None or model.rowCount() == 0
        if empty:
            viewport = self._view.viewport()
            height = min(self.state.sizeHint().height(), viewport.height())
            self.state.setGeometry(0, max(0, (viewport.height() - height) // 2), viewport.width(), height)
        if self.state.isVisibleTo(self._view.viewport()) != empty:
            self.state.setVisible(empty)

    def _model_changed(self, *_args: object) -> None:
        self.refresh()

    def _rewire(self, model: Optional[QAbstractItemModel]) -> None:
        if self._model is not None:
            for name in _MODEL_SIGNALS:
                try:
                    getattr(self._model, name).disconnect(self._model_changed)
                except (RuntimeError, TypeError):  # reason: the old model is gone or was never connected
                    pass
        self._model = model
        if model is not None:
            for name in _MODEL_SIGNALS:
                getattr(model, name).connect(self._model_changed)


def _inside_combo(view: QWidget, root: QWidget) -> bool:
    parent = view.parentWidget()
    while parent is not None and parent is not root:
        if isinstance(parent, QComboBox):
            return True
        parent = parent.parentWidget()
    return False


def show_empty_states(root: QWidget, message_key: str = "empty_view", hint_key: str = "empty_view_hint") -> int:
    """Give every item view under ``root`` an empty state; return how many were given one.

    Header views and the drop-down lists of combo boxes are left alone, as is
    a view whose :data:`NO_EMPTY_STATE` property is set. Calling it again only
    reaches views added since.
    """
    added = 0
    for view in root.findChildren(QAbstractItemView):
        if isinstance(view, QHeaderView) or view.property(NO_EMPTY_STATE) or _inside_combo(view, root):
            continue
        view.setProperty(NO_EMPTY_STATE, True)
        _EmptyOverlay(view, message_key, hint_key)
        added += 1
    return added


__all__ = ["NO_EMPTY_STATE", "show_empty_states"]
