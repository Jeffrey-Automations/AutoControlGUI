"""Stops that failed in the background, kept so they can be retried instead of only logged.

A panel lets go of a session, a recorder or a host at once and hands its
``stop`` to a :class:`~je_auto_control.gui._slow_op.StopQueue`. When that stop
raised, the queue used to log it and drop it: the resource might still be
running, and nothing owned it any more. :class:`StopCustody` keeps each failed
stop with the error it raised and the caller's authority captured when the stop
was queued, for the life of the application:

* :meth:`StopCustody.snapshot` describes what is held -- labels, errors,
  attempts -- without running anything or waiting on a native lock, so the
  Diagnostics tab can read it on the GUI thread.
* :meth:`StopCustody.retry` runs a held stop again on the calling thread (a
  worker), inside the authority it was queued under. A stop that succeeds is
  released; one that fails again stays, with its new error.
* :meth:`StopCustody.forget` lets go of one the operator has dealt with.

Holding a stop is not the same as its resource being released: a record stays
until a retry succeeds or the operator forgets it. This module has no Qt
import; the GUI reads it through the Diagnostics tab.
"""
from __future__ import annotations

import functools
import itertools
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from je_auto_control.utils.logging.logging_instance import autocontrol_logger
from je_auto_control.utils.logging.secret_scope import scrub_secret_text
from je_auto_control.utils.rbac.deferred import DeferredAuthorization

#: The most failed stops held at once; the oldest is let go (and logged) beyond it.
MAX_HELD = 200


@dataclass(frozen=True)
class FailedStop:
    """What one held stop looks like from outside: no callable, no resource."""

    stop_id: int
    label: str
    error: str
    failed_at: float
    attempts: int


@dataclass
class _Held:
    stop: Callable[[], Any]
    label: str
    error: str
    failed_at: float
    attempts: int
    authority: Optional[DeferredAuthorization]


def describe_stop(stop: Callable[[], Any]) -> str:
    """A short label for ``stop``: the function's name, with its owner's class for a bound method."""
    target: Any = stop
    while isinstance(target, functools.partial):
        target = target.func
    owner = getattr(target, "__self__", None)
    name = getattr(target, "__name__", type(target).__name__)
    return f"{type(owner).__name__}.{name}" if owner is not None else str(name)


class StopCustody:
    """Thread-safe holder of failed stops; one per application (:func:`stop_custody`)."""

    def __init__(self, max_held: int = MAX_HELD) -> None:
        self._lock = threading.Lock()
        self._held: Dict[int, _Held] = {}
        self._ids = itertools.count(1)
        self._max_held = max_held
        self._listeners: List[Callable[[], None]] = []

    def hold(self, stop: Callable[[], Any], error: object, *, label: str = "",
             authority: Optional[DeferredAuthorization] = None) -> int:
        """Keep ``stop``, which raised ``error``; return its id. Safe from any thread."""
        record = _Held(stop, label or describe_stop(stop), scrub_secret_text(_text(error)), time.time(), 1, authority)
        with self._lock:
            stop_id = next(self._ids)
            self._held[stop_id] = record
            dropped = self._trim()
        for old in dropped:
            autocontrol_logger.warning(f"failed stop let go (custody full): {old.label}: {old.error}")
        autocontrol_logger.warning(f"background stop failed and is held for retry: {record.label}: {record.error}")
        self._changed()
        return stop_id

    def snapshot(self) -> List[FailedStop]:
        """What is held, oldest first; runs no stop and never waits on anything but this lock."""
        with self._lock:
            return [FailedStop(stop_id, held.label, held.error, held.failed_at, held.attempts)
                    for stop_id, held in self._held.items()]

    def retry(self, stop_id: int) -> bool:
        """Run a held stop again, under its captured authority; ``True`` when it succeeded (it is then released).

        Blocks for as long as the stop does: call it on a worker. An unknown id is ``False``.
        """
        with self._lock:
            held = self._held.get(stop_id)
        if held is None:
            return False
        try:
            if held.authority is not None:
                with held.authority.scope():
                    held.stop()
            else:
                held.stop()
        except Exception as error:  # noqa: BLE001  # reason: recorded on the held stop, which stays for another retry
            with self._lock:
                if self._held.get(stop_id) is held:
                    held.error = scrub_secret_text(_text(error))
                    held.attempts += 1
                    held.failed_at = time.time()
            self._changed()
            return False
        with self._lock:
            if self._held.get(stop_id) is held:
                del self._held[stop_id]
        self._changed()
        return True

    def retry_all(self) -> tuple[int, int]:
        """Retry every held stop once, oldest first; return ``(released, still_failing)``."""
        released = failing = 0
        for record in self.snapshot():
            if self.retry(record.stop_id):
                released += 1
            else:
                failing += 1
        return released, failing

    def forget(self, stop_id: int) -> bool:
        """Let go of one held stop without running it; ``True`` when it was held."""
        with self._lock:
            found = self._held.pop(stop_id, None) is not None
        if found:
            self._changed()
        return found

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Call ``listener()`` after every change, on the thread that made it; return its removal."""
        with self._lock:
            self._listeners.append(listener)

        def remove() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)
        return remove

    def _trim(self) -> List[_Held]:
        dropped = []
        while len(self._held) > self._max_held:
            oldest = next(iter(self._held))
            dropped.append(self._held.pop(oldest))
        return dropped

    def _changed(self) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener()
            except Exception as error:  # noqa: BLE001  # reason: a listener must not undo the custody change
                autocontrol_logger.warning(f"stop custody listener failed: {error!r}")


def _text(error: object) -> str:
    return f"{type(error).__name__}: {error}" if isinstance(error, BaseException) else str(error)


_CUSTODY = StopCustody()


def stop_custody() -> StopCustody:
    """The application's custody of failed background stops."""
    return _CUSTODY


__all__ = ["FailedStop", "MAX_HELD", "StopCustody", "describe_stop", "stop_custody"]
