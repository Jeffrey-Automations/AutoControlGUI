"""A banner at the top of a page: the last run's error, or what the active role cannot run.

The workspace puts one :class:`PageBanner` under each page's header. It stays
hidden until there is something to say:

* **Error** -- a background run on the page failed (published by the page's
  tab tasks); the next run clears it.
* **Permission** -- the active RBAC role cannot run a command the page's
  panels declare in ``REQUIRED_COMMANDS``, checked when the page is shown,
  or a run was refused by the RBAC layer.

The banner has a *Dismiss* link rather than a button: a page's commands live
in the Actions menu, and its views hold no buttons of their own.
"""
from typing import Iterable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QBoxLayout, QFrame, QHBoxLayout, QLabel, QScrollArea, QStackedWidget, QTabWidget, QWidget

from je_auto_control.gui.adaptive.surfaces import page_header
from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper
from je_auto_control.utils.rbac.authorization import current_authorization
from je_auto_control.utils.rbac.policy import refused_commands

_BANNER_NAME = "PageBanner"


def page_of(owner: QWidget) -> QWidget:
    """The workspace page ``owner`` sits on, or ``owner`` itself when it is on no tab page."""
    current = owner
    while True:
        viewport = current.parentWidget()
        if viewport is None:
            return owner
        scroll = viewport.parentWidget()
        if isinstance(scroll, QScrollArea) and scroll.widget() is current:
            stack = scroll.parentWidget()
            if isinstance(stack, QStackedWidget) and isinstance(stack.parentWidget(), QTabWidget):
                return current
        current = viewport


class PageBanner(QFrame):
    """One message about the page as a whole; hidden while there is none."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName(_BANNER_NAME)
        self.setProperty("role", "banner")
        self.kind = ""
        self._key = ""
        self._values: dict[str, str] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        self.message = QLabel()
        self.message.setTextFormat(Qt.TextFormat.PlainText)    # error text is never markup
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.dismiss = QLabel()
        self.dismiss.setTextFormat(Qt.TextFormat.RichText)
        self.dismiss.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse
                                             | Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        self.dismiss.linkActivated.connect(self._dismissed)
        layout.addWidget(self.message, stretch=1)
        layout.addWidget(self.dismiss, alignment=Qt.AlignmentFlag.AlignTop)
        self.hide()

    def show_error(self, detail: str) -> None:
        """Say that the page's last run failed, and why."""
        self._show("error", "page_banner_error", detail=detail)

    def show_refusal(self, detail: str) -> None:
        """Say that the RBAC layer refused a run, and why."""
        self._show("permission", "page_banner_refused", detail=detail)

    def show_permission(self, role: str, commands: Iterable[str]) -> None:
        """Say which of the page's commands the active role cannot run."""
        self._show("permission", "page_banner_permission", role=role, commands=", ".join(commands))

    def clear(self, kind: str = "") -> None:
        """Hide the banner; with ``kind``, only when it is showing that kind."""
        if not kind or kind == self.kind:
            self.kind = ""
            self.hide()

    def retranslate(self) -> None:
        """Re-read the message and the link in the active language."""
        translate = language_wrapper.translate
        if self._key:
            self.message.setText(translate(self._key, self._key).format(**self._values))
        self.dismiss.setText(f'<a href="dismiss">{translate("page_banner_dismiss", "page_banner_dismiss")}</a>')

    def _show(self, kind: str, key: str, **values: str) -> None:
        self.kind, self._key, self._values = kind, key, values
        self.setProperty("kind", kind)
        self.style().unpolish(self)
        self.style().polish(self)
        self.retranslate()
        self.show()

    def _dismissed(self, _link: str) -> None:
        self.clear()


def add_page_banner(page: QWidget) -> Optional[PageBanner]:
    """Put a hidden :class:`PageBanner` under ``page``'s header; ``None`` when its layout cannot take one."""
    existing = page_banner(page)
    if existing is not None:
        return existing
    layout = page.layout()
    if not isinstance(layout, QBoxLayout) or layout.direction() != QBoxLayout.Direction.TopToBottom:
        return None
    header = page_header(page)
    after_header = header is not None and layout.indexOf(header) == 0
    banner = PageBanner(page)
    layout.insertWidget(1 if after_header else 0, banner)
    return banner


def page_banner(widget: QWidget) -> Optional[PageBanner]:
    """The banner of the page ``widget`` sits on, or ``None``."""
    found = page_of(widget).findChild(PageBanner, _BANNER_NAME, Qt.FindChildOption.FindDirectChildrenOnly)
    return found if isinstance(found, PageBanner) else None


def required_commands(page: QWidget) -> List[str]:
    """Every ``AC_*`` command the page and its panels declare in ``REQUIRED_COMMANDS``, once each."""
    seen: List[str] = []
    for widget in (page, *page.findChildren(QWidget)):
        for name in getattr(type(widget), "REQUIRED_COMMANDS", ()):
            if name not in seen:
                seen.append(name)
    return seen


def refresh_permission(page: QWidget) -> None:
    """Show or clear the page's permission banner for the active role."""
    banner = page_banner(page)
    if banner is None:
        return
    refused = refused_commands(required_commands(page))
    caller = current_authorization()
    if refused and caller is not None:
        banner.show_permission(caller.role, refused)
    else:
        banner.clear("permission")


__all__ = ["PageBanner", "add_page_banner", "page_banner", "page_of", "refresh_permission", "required_commands"]
