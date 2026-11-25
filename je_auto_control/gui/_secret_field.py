"""A credential field: masked by default, an explicit Show toggle, and a Copy that still works.

A masked :class:`~PySide6.QtWidgets.QLineEdit` refuses Ctrl+C, so a token the
user generated could only be shared by revealing it on screen. The row this
module builds keeps the field masked, adds a checkable Show button that
unmasks it only while it is pressed in, and a Copy button that puts the
field's text on the clipboard without showing it.
"""
from typing import Optional, Protocol, TypeVar

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QToolButton, QWidget

_W = TypeVar("_W", bound=QWidget)


class Translate(Protocol):
    """The owner's ``TranslatableMixin._tr``: set a widget's text from a key, now and on retranslate."""

    def __call__(self, widget: _W, key: str) -> _W:
        """Return ``widget`` with its text set from ``key``."""


class SecretField(QWidget):
    """``edit`` plus its Show toggle and Copy button, laid out in one row.

    ``tr`` is the owning widget's ``TranslatableMixin._tr``, so the two
    buttons follow the owner's language switches. ``copyable=False`` leaves
    the Copy button out, for a tab whose Actions menu already copies the value.
    """

    def __init__(self, edit: QLineEdit, tr: Translate, parent: Optional[QWidget] = None, *,
                 copyable: bool = True) -> None:
        super().__init__(parent)
        self.setProperty("role", "bare")
        self.edit = edit
        self._secret = True
        edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.reveal = tr(QToolButton(), "secret_field_show")
        self.reveal.setCheckable(True)
        self.reveal.toggled.connect(self._on_reveal)
        self.copy = tr(QToolButton(), "secret_field_copy")
        self.copy.clicked.connect(self._on_copy)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit, stretch=1)
        row.addWidget(self.reveal)
        row.addWidget(self.copy)
        self.copy.setVisible(copyable)

    @property
    def revealed(self) -> bool:
        """Whether the field currently shows its text."""
        return self.edit.echoMode() == QLineEdit.EchoMode.Normal

    def set_value(self, text: str, *, secret: bool = True) -> None:
        """Show ``text``; a value that is not a credential (a placeholder, a note) is shown in clear.

        For a read-only field that displays a credential the application
        holds: Show and Copy are offered only while it holds one.
        """
        self._secret = secret
        self.edit.setText(text)
        self.reveal.setEnabled(secret)
        self.copy.setEnabled(secret)
        self._on_reveal(self.reveal.isChecked())

    def _on_reveal(self, shown: bool) -> None:
        clear = shown or not self._secret
        self.edit.setEchoMode(QLineEdit.EchoMode.Normal if clear else QLineEdit.EchoMode.Password)

    def _on_copy(self) -> None:
        text = self.edit.text()
        if text and self._secret:
            QGuiApplication.clipboard().setText(text)


__all__ = ["SecretField"]
