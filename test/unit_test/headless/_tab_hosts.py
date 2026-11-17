"""Standalone core panels used by focused GUI tests."""
from typing import Optional

from je_auto_control.gui._record_tab import RecordTab
from je_auto_control.gui._script_tab import ScriptTab


class ScriptHost(ScriptTab):
    """The Script tab alone."""


class RecordHost(RecordTab):
    """The Record tab seeded with a previous recording."""

    def __init__(self, record_data: Optional[list] = None) -> None:
        super().__init__()
        self._record_data = list(record_data or [])
