"""Immutable execution snapshots and a passive, scrollable workspace detail view."""
from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QLabel, QProgressBar, QScrollArea, QVBoxLayout, QWidget

from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper


ExecutionPhase = Literal['idle', 'running', 'stopping', 'succeeded', 'cancelled', 'error', 'unavailable']


@dataclass(frozen=True)
class ExecutionDetails:
    """Display data only; the producing page retains task and cancellation ownership."""

    phase: ExecutionPhase = 'idle'
    summary: str = ''
    completed: int = 0
    total: int = 0


class ExecutionDetailsSource(QObject):
    """A page-owned snapshot publisher updated on the GUI thread."""

    changed = Signal(object)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._snapshot = ExecutionDetails()

    @property
    def snapshot(self) -> ExecutionDetails:
        """Return the latest immutable snapshot without starting work."""
        return self._snapshot

    def publish(self, snapshot: ExecutionDetails) -> None:
        """Replace the cached display state and notify the active view."""
        self._snapshot = snapshot
        self.changed.emit(snapshot)


class ExecutionDetailsPane(QScrollArea):
    """Render one snapshot without retaining a page, task, exception or result."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setMinimumWidth(0)
        content = QWidget()
        layout = QVBoxLayout(content)
        self.title = QLabel()
        self.state = QLabel()
        self.summary = QLabel()
        for label in (self.title, self.state, self.summary):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(label)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        layout.addStretch()
        self.setWidget(content)
        self._snapshot: ExecutionDetails | None = None
        self._selected = False
        self.retranslate()

    @property
    def snapshot(self) -> ExecutionDetails | None:
        """Return the data currently displayed, or None for an empty/unpublished page."""
        return self._snapshot

    def display(self, snapshot: ExecutionDetails | None, *, selected: bool) -> None:
        """Show a snapshot, or the distinct no-page/no-publisher state."""
        self._snapshot, self._selected = snapshot, selected
        self.retranslate()

    def retranslate(self) -> None:
        """Refresh display labels while preserving the current execution data."""
        translate = language_wrapper.translate
        self.title.setText(translate('workspace_details_title', 'Execution details'))
        snapshot = self._snapshot
        if snapshot is None:
            key = 'workspace_details_unavailable' if self._selected else 'workspace_details_empty'
            self.state.setText(translate(key, key))
            self.summary.clear()
            self.progress.hide()
            return
        key = 'workspace_phase_' + snapshot.phase
        self.state.setText(translate(key, key))
        self.summary.setText(snapshot.summary)
        self.progress.setVisible(snapshot.total > 0)
        self.progress.setRange(0, max(0, snapshot.total))
        self.progress.setValue(max(0, min(snapshot.completed, snapshot.total)))
