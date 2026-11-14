"""Data-only Qt owner for folder wiring tests; no desktop resources."""
from PySide6.QtCore import QObject
from je_auto_control.gui.remote_desktop.view_lifetime import ViewLifetime


class RemoteViewOwner(QObject):
    def __init__(self, **attributes):
        super().__init__()
        self.__dict__.update(attributes)
        self._view = ViewLifetime(self)
