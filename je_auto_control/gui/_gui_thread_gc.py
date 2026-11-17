"""Run the cyclic garbage collector on the GUI thread only, while the window is up.

PySide6 6.12 does not delete a Python-owned Qt object that a non-GUI thread's
collection reaches: it queues the delete and runs it later on the GUI thread
(``Shiboken::BindingManager::runDeletionInMainThread``). On Windows one such
deferred delete of a top-level widget aborted the interpreter inside
``QObject::~QObject`` (``docs/upstream/pyside6-6.12-deferred-deletion-abort.md``).
Automatic collection runs on whichever thread happens to allocate when it is
due, and the GUI's workers run Python, so :class:`GuiThreadCollector` switches
it off and collects from a timer on the GUI thread instead.

It keeps the interpreter's own thresholds: a young collection once
allocations pass ``threshold[0]``, an older one every ``threshold[1]`` young
ones and a full one every ``threshold[1] * threshold[2]``. A first threshold of
0 (collection switched off by the application) is respected. An explicit
``gc.collect()`` anywhere still works, and :meth:`GuiThreadCollector.stop`
gives automatic collection back as it was found.
"""
import gc
from typing import Optional

from PySide6.QtCore import QObject, QTimer

_INTERVAL_MS = 500


class GuiThreadCollector(QObject):
    """Collect garbage from a GUI-thread timer while automatic collection is off."""

    def __init__(self, parent: Optional[QObject] = None, interval_ms: int = _INTERVAL_MS) -> None:
        super().__init__(parent)
        self._was_enabled = gc.isenabled()
        self._young = 0
        self._stopped = False
        self.collections = [0, 0, 0]
        gc.disable()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check)
        self._timer.start(interval_ms)

    def check(self) -> Optional[int]:
        """Collect the generation the allocation count calls for; the generation, or None if none was due."""
        first, middle, oldest = gc.get_threshold()
        if first <= 0 or gc.get_count()[0] <= first:
            return None
        self._young += 1
        generation = 0
        if self._young % (max(1, middle) * max(1, oldest)) == 0:
            generation = 2
        elif self._young % max(1, middle) == 0:
            generation = 1
        gc.collect(generation)
        self.collections[generation] += 1
        return generation

    def stop(self) -> None:
        """Stop collecting here and switch automatic collection back on if it was on; idempotent."""
        if self._stopped:
            return
        self._stopped = True
        self._timer.stop()
        if self._was_enabled:
            gc.enable()


__all__ = ["GuiThreadCollector"]
