"""Translation-registry mixin shared by tabs that need live language switching.

Widgets register their (widget, translation-key, setter-name) triples via
``self._tr(widget, key, setter)`` during UI construction. Calling
``self.retranslate()`` re-pulls every key from the language wrapper and
re-applies it through the recorded setter. Destroyed widgets are skipped
silently so removing a row never breaks a later language switch.

A widget that registers *itself* (``self._tr(self, "title_key",
setter="setWindowTitle")``) is recorded as ``None``, not as a reference. Holding
it made the widget a reference cycle, so dropping one never freed it: it stayed
a live window until the cycle collector ran, and the collector destroyed the
C++ object wherever it happened to be — on Python 3.10/3.11 that can be in the
middle of a PySide call that is still walking a list of widgets.

A text that changes with the widget's state -- a status line, a quality hint --
is shown through a :class:`KeyedText`, which keeps the catalogue key and its
fields rather than the rendered string, so the owner's ``retranslate`` can show
it again in the new language. ``self._keyed(widget)`` makes one that
:meth:`TranslatableMixin.retranslate` re-renders itself; one made for the owner
(``self._keyed(self, "setWindowTitle")``) holds it weakly, for the same reason
as above.

A table or list cell whose text is a translated word keeps its key on the item
(:mod:`je_auto_control.gui._i18n_cells`); ``self._tr_cells(view)`` registers the
view so :meth:`TranslatableMixin.retranslate` renders those cells again.
"""
import weakref
from typing import Callable, List, Optional, Tuple, TypeVar

from PySide6.QtWidgets import (
    QAbstractButton, QGroupBox, QLabel, QLineEdit, QTabWidget, QWidget,
)

from je_auto_control.gui._i18n_cells import CellView, retranslate_cells
from je_auto_control.gui.language_wrapper.multi_language_wrapper import (
    language_wrapper,
)


#: ``_tr`` hands back the widget it was given, as the class it was given.
_W = TypeVar("_W", bound=QWidget)


def _default_setter(widget: QWidget) -> str:
    if isinstance(widget, QGroupBox):
        return "setTitle"
    if isinstance(widget, (QLabel, QAbstractButton)):
        return "setText"
    if isinstance(widget, QLineEdit):
        return "setPlaceholderText"
    return "setText"


class TranslatableMixin:
    """Provides ``_tr(...)`` / ``retranslate()`` for a widget-building class."""

    def _tr_init(self) -> None:
        self._tr_registry: List[Tuple[Optional[QWidget], str, str]] = []
        self._tr_tabs: List[Tuple[QTabWidget, int, str]] = []

    def _tr(self, widget: _W, key: str, setter: str = "") -> _W:
        """Set ``widget`` text from ``key`` now and on every retranslate."""
        if not hasattr(self, "_tr_registry"):
            self._tr_init()
        resolved = setter or _default_setter(widget)
        translated = language_wrapper.translate(key, key)
        getattr(widget, resolved)(translated)
        # None stands for ``self``: see the module docstring.
        self._tr_registry.append((None if widget is self else widget, key, resolved))
        return widget

    def _tr_tab(self, tab_widget: QTabWidget, index: int, key: str) -> None:
        """Register a tab title so it re-translates."""
        if not hasattr(self, "_tr_tabs"):
            self._tr_init()
        tab_widget.setTabText(index, language_wrapper.translate(key, key))
        self._tr_tabs.append((tab_widget, index, key))

    def _keyed(self, widget: QWidget, setter: str = "setText") -> "KeyedText":
        """A :class:`KeyedText` for ``widget`` that :meth:`retranslate` shows again in the new language."""
        text = KeyedText(widget, setter, weak=widget is self)
        if not hasattr(self, "_tr_keyed"):
            self._tr_keyed: List[KeyedText] = []
        self._tr_keyed.append(text)
        return text

    def _tr_cells(self, view: CellView) -> None:
        """Register ``view`` so :meth:`retranslate` renders its keyed cells again."""
        if not hasattr(self, "_tr_views"):
            self._tr_views: List[CellView] = []
        self._tr_views.append(view)

    def retranslate(self) -> None:
        """Re-apply every registered translation key and re-render every keyed text and cell."""
        for text in getattr(self, "_tr_keyed", []):
            text.retranslate()
        for view in getattr(self, "_tr_views", []):
            try:
                retranslate_cells(view)
            except RuntimeError:
                continue    # the view was destroyed
        for widget, key, setter in getattr(self, "_tr_registry", []):
            target = self if widget is None else widget
            try:
                getattr(target, setter)(language_wrapper.translate(key, key))
            except RuntimeError:
                # Widget destroyed; leave it for a future cleanup pass.
                continue
        for tab_widget, index, key in getattr(self, "_tr_tabs", []):
            try:
                tab_widget.setTabText(index, language_wrapper.translate(key, key))
            except RuntimeError:
                continue


class KeyedText:
    """One text of a widget (``setText`` by default), set from a catalogue key so a language switch re-reads it."""

    def __init__(self, widget: QWidget, setter: str = "setText", *, weak: bool = False) -> None:
        self._setter = setter
        self._widget: Callable[[], Optional[QWidget]] = weakref.ref(widget) if weak else (lambda: widget)
        self._render: Optional[Callable[[], str]] = None

    def _apply(self, text: str) -> None:
        widget = self._widget()
        if widget is None:
            raise RuntimeError("the widget is gone")
        getattr(widget, self._setter)(text)

    def show(self, key: str, **fields: object) -> None:
        """Show ``key`` with each ``{field}`` replaced, now and on every :meth:`retranslate`."""
        self.show_rendered(lambda: _fill(language_wrapper.translate(key, key), fields))

    def show_joined(self, key: str, detail: object, sep: str = ": ") -> None:
        """Show ``key`` translated, then ``sep`` and ``detail`` as it is: a label over data such as an error."""
        text = str(detail)
        self.show_rendered(lambda: language_wrapper.translate(key, key) + sep + text)

    def show_rendered(self, render: Callable[[], str]) -> None:
        """Show what ``render`` returns, calling it again on every :meth:`retranslate`."""
        self._render = render
        self._apply(render())

    def show_plain(self, text: str) -> None:
        """Show ``text`` as it is: data, or a text a later update replaces anyway."""
        self._render = None
        self._apply(text)

    def clear(self) -> None:
        """Show nothing and forget the key."""
        self.show_plain("")

    def forget(self) -> None:
        """Leave the widget as it is and stop re-rendering: something else (a picture, say) replaced the text."""
        self._render = None

    def retranslate(self) -> None:
        """Show the remembered key again in the active language."""
        if self._render is None:
            return
        try:
            self._apply(self._render())
        except RuntimeError:
            self._render = None     # the widget was destroyed


def _fill(template: str, fields: dict[str, object]) -> str:
    """Replace each ``{name}`` of ``template``; a translation that leaves one out is not an error."""
    for name, value in fields.items():
        template = template.replace("{" + name + "}", str(value))
    return template
