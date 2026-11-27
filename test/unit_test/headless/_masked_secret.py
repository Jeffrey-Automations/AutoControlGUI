"""Shared check: a credential field is masked, reveals only on request, and still copies (fake clipboard)."""
from types import SimpleNamespace

from PySide6.QtWidgets import QLineEdit


def assert_masked_secret(edit: QLineEdit, monkeypatch, value: str = "tok-123", *, copyable: bool = True) -> None:
    """``edit`` sits in a :class:`SecretField`: masked by default, Show toggles, Copy (when offered) copies it."""
    from je_auto_control.gui import _secret_field
    field = edit.parentWidget()
    assert isinstance(field, _secret_field.SecretField), f"{edit!r} is not wrapped in a SecretField"
    assert edit.echoMode() == QLineEdit.EchoMode.Password
    edit.setText(value)
    field.reveal.setChecked(True)
    assert edit.echoMode() == QLineEdit.EchoMode.Normal
    field.reveal.setChecked(False)
    assert edit.echoMode() == QLineEdit.EchoMode.Password
    assert field.copy.isVisibleTo(field) is copyable
    if not copyable:
        return
    copied: list = []
    monkeypatch.setattr(_secret_field.QGuiApplication, "clipboard",
                        lambda: SimpleNamespace(setText=copied.append))
    field.copy.click()
    assert copied == [value]
