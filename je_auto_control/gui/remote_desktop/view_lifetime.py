"""Retirable weak delivery from surviving transports to one Qt view."""
from __future__ import annotations

import functools
import threading
import weakref
from typing import Callable, Generic, TypeVar

from PySide6.QtCore import QObject, Qt, Signal, Slot

_Owner = TypeVar("_Owner", bound=QObject)
_Value = TypeVar("_Value")


class _Relay(QObject):
    delivered = Signal(str, object)

    def __init__(self, owner: QObject, deliver: Callable[[str, tuple[object, ...]], None]) -> None:
        super().__init__(owner)
        self._deliver = deliver
        self.delivered.connect(self._dispatch, Qt.ConnectionType.QueuedConnection)

    @Slot(str, object)
    def _dispatch(self, method: str, arguments: tuple[object, ...]) -> None:
        self._deliver(method, arguments)


class ViewLifetime(Generic[_Owner]):
    """A backend-held delivery lease that never owns the page or its Qt relay.

    Retirement and producer emission serialize only the short signal emission.
    Widget methods run on Qt's thread outside the lock and recheck retirement.
    Parent destruction retires the lease before Qt destroys the child relay.
    """

    def __init__(self, owner: _Owner) -> None:
        self._owner = weakref.ref(owner)
        self._lock = threading.RLock()
        self._retired = False
        relay = _Relay(owner, self._deliver)
        self._relay = weakref.ref(relay)
        owner.destroyed.connect(self.retire)

    @property
    def retired(self) -> bool:
        with self._lock:
            return self._retired

    def retire(self) -> None:
        """Permanently reject producers and events already queued for this view."""
        with self._lock:
            self._retired = True

    def callback(self, method: str) -> Callable[..., None]:
        """Create a producer callback containing no bound widget or Qt signal."""
        return functools.partial(self.post, method)

    def error_callback(self, method: str) -> Callable[[Exception], None]:
        def error(exc: Exception) -> None:
            self.post(method, str(exc))
        return error

    def tagged(self, method: str, tag: object) -> Callable[..., None]:
        """Like :meth:`callback`, delivering ``method(tag, *arguments)``: the tag says which session sent it."""
        return functools.partial(self.post, method, tag)

    def tagged_error(self, method: str, tag: object) -> Callable[[Exception], None]:
        """Like :meth:`error_callback`, delivering ``method(tag, message)``."""
        def error(exc: Exception) -> None:
            self.post(method, tag, str(exc))
        return error

    def post(self, method: str, *arguments: object) -> None:
        with self._lock:
            relay = self._relay()
            if self._retired or relay is None:
                return
            try:
                relay.delivered.emit(method, arguments)
            except RuntimeError:  # reason: the relay may be explicitly deleted without its parent
                self._retired = True

    def _deliver(self, method: str, arguments: tuple[object, ...]) -> None:
        with self._lock:
            owner = None if self._retired else self._owner()
        if owner is not None:
            getattr(owner, method)(*arguments)

    def getter(self, read: Callable[[_Owner], _Value], default: _Value) -> Callable[[], _Value]:
        """Read plain backend state weakly; never use this to query a Qt widget."""
        def get() -> _Value:
            with self._lock:
                owner = None if self._retired else self._owner()
                return default if owner is None else read(owner)
        return get
