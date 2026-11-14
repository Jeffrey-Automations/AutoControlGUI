"""Cards, page headers and empty states: the shared surfaces every page is built from.

They carry a ``role`` property the theme's style sheet targets
(``QFrame[role="card"]``, ``QLabel[role="pageTitle"]`` ...), so the look lives
in :mod:`je_auto_control.gui.theme` and a page only says what each part is.
"""
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QBoxLayout, QFrame, QLabel, QLayout, QVBoxLayout, QWidget

from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper

#: Property naming what a widget is to the style sheet.
ROLE = "role"
_HEADER_NAME = "AdaptivePageHeader"


def set_role(widget: QWidget, role: str) -> QWidget:
    """Tag ``widget`` for the style sheet and re-polish it so the change shows."""
    widget.setProperty(ROLE, role)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    return widget


def optional_text(key: str) -> str:
    """``key`` in the active language, or ``""`` when no language defines it."""
    if not key:
        return ""
    text = language_wrapper.translate(key, "")
    return "" if text == key else text


def _label(role: str, wrap: bool = True) -> QLabel:
    label = QLabel()
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(wrap)
    set_role(label, role)
    return label


class Card(QFrame):
    """A raised panel with an optional title, holding one group of related controls."""

    def __init__(self, title_key: str = "", parent: Optional[QWidget] = None, *,
                 title_default: str = "") -> None:
        super().__init__(parent)
        set_role(self, "card")
        self._title_key, self._title_default = title_key, title_default
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(16, 14, 16, 16)
        self._outer.setSpacing(10)
        self.title = _label("sectionTitle")
        self.title.setVisible(bool(title_key))
        self._outer.addWidget(self.title)
        self.retranslate()

    @property
    def body(self) -> QVBoxLayout:
        """The layout the card's controls go into."""
        return self._outer

    def add(self, item: "QWidget | QLayout", stretch: int = 0) -> "Card":
        """Append a widget or a layout to the card; returns the card for chaining."""
        if isinstance(item, QLayout):
            self._outer.addLayout(item, stretch)
        else:
            self._outer.addWidget(item, stretch)
        return self

    def retranslate(self) -> None:
        """Re-read the title in the active language."""
        if self._title_key:
            self.title.setText(language_wrapper.translate(self._title_key, self._title_default or self._title_key))


class PageHeader(QWidget):
    """Page title and a one-line description of what the page is for."""

    def __init__(self, title_key: str, subtitle_key: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName(_HEADER_NAME)
        self._title_key, self._subtitle_key = title_key, subtitle_key
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(2)
        self.title = _label("pageTitle")
        self.subtitle = _label("pageSubtitle")
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        self.retranslate()

    def retranslate(self) -> None:
        """Re-read both lines in the active language; a subtitle with no text is hidden."""
        translate = language_wrapper.translate
        self.title.setText(translate(self._title_key, self._title_key))
        subtitle = optional_text(self._subtitle_key)
        self.subtitle.setText(subtitle)
        self.subtitle.setVisible(bool(subtitle))


class EmptyState(QWidget):
    """Centred message shown in place of an empty list or table."""

    def __init__(self, message_key: str, hint_key: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._message_key, self._hint_key = message_key, hint_key
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(4)
        self.message = _label("emptyMessage")
        self.hint = _label("hint")
        for label in (self.message, self.hint):
            label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            layout.addWidget(label)
        self.retranslate()

    def retranslate(self) -> None:
        """Re-read the message and hint in the active language."""
        translate = language_wrapper.translate
        self.message.setText(translate(self._message_key, self._message_key))
        hint = optional_text(self._hint_key)
        self.hint.setText(hint)
        self.hint.setVisible(bool(hint))


def page_header(page: QWidget) -> Optional[PageHeader]:
    """The header :func:`add_page_header` gave ``page``, or ``None``."""
    found = page.findChild(PageHeader, _HEADER_NAME, Qt.FindChildOption.FindDirectChildrenOnly)
    return found if isinstance(found, PageHeader) else None


def add_page_header(page: QWidget, title_key: str, subtitle_key: str = "") -> Optional[PageHeader]:
    """Put a :class:`PageHeader` at the top of ``page``; ``None`` when its layout cannot take one.

    Only a page laid out by a box layout gets a header (anything else would have
    to be re-laid out, which is the page's own business). Calling it again
    returns the header already there.
    """
    existing = page_header(page)
    if existing is not None:
        return existing
    layout = page.layout()
    if not isinstance(layout, QBoxLayout) or layout.direction() != QBoxLayout.Direction.TopToBottom:
        return None
    header = PageHeader(title_key, subtitle_key, page)
    layout.insertWidget(0, header)
    return header


def retranslate_surfaces(root: QWidget) -> None:
    """Re-read every card title, page header and empty state under ``root`` in the active language."""
    for header in root.findChildren(PageHeader):
        header.retranslate()
    for card in root.findChildren(Card):
        card.retranslate()
    for empty in root.findChildren(EmptyState):
        empty.retranslate()
