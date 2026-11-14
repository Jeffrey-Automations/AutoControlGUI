"""Cancellable journal inspection with captured context and refreshed authority."""
from __future__ import annotations

from asyncio import CancelledError as AsyncCancelledError
from concurrent.futures import CancelledError
from contextvars import copy_context
from dataclasses import dataclass, field
from threading import Event
from typing import Callable, Literal, Optional

from je_auto_control.utils.action_journal.inspection import inspect_journal
from je_auto_control.utils.exception.exceptions import AutoControlException
from je_auto_control.utils.logging.secret_scope import scrub_secret_text
from je_auto_control.utils.rbac.deferred import DeferredAuthorization


@dataclass(frozen=True)
class JournalReadRequest:
    """One immutable target; its ID distinguishes late results from a new selection."""

    request_id: int
    path: str
    run_id: Optional[str]
    limit: int
    step_id: Optional[str] = None


@dataclass(frozen=True)
class JournalReadOutcome:
    """A terminal read outcome; cancellation never supplies partial snapshots."""

    request_id: int
    status: Literal["ok", "cancelled", "error"]
    events: list[dict[str, object]] = field(default_factory=list)
    scanned: int = 0
    error: str = ""


def _no_report(_value: object) -> None:
    """Progress sink for a worker run without one."""


class JournalReadWorker:
    """Read off the GUI thread; reports carry only IDs, counts and sanitized data.

    Built on the GUI thread, which captures the caller's context and authority,
    and called on a worker thread with the stop event and a progress report;
    each report is ``(request_id, scanned)`` every hundred records.
    """

    def __init__(self, request: JournalReadRequest) -> None:
        self._request = request
        self._stop = Event()
        self._report: Callable[[object], None] = _no_report
        self._context = copy_context()
        self._authority = DeferredAuthorization.capture()
        self._scanned = 0

    def request_stop(self) -> None:
        """Request cancellation without blocking the GUI or closing another thread's handle."""
        self._stop.set()

    def __call__(self, stop_event: Event, report: Callable[[object], None] = _no_report) -> JournalReadOutcome:
        """Return exactly one terminal result for ordinary errors or cooperative cancellation."""
        self._stop, self._report = stop_event, report
        return self._context.run(self._inspect)

    def _checkpoint(self, count: int) -> None:
        if self._stop.is_set():
            raise CancelledError()
        self._scanned = count
        if count % 100 == 0:
            self._report((self._request.request_id, count))

    def _inspect(self) -> JournalReadOutcome:
        request = self._request
        try:
            self._checkpoint(0)
            with self._authority.scope():
                events = inspect_journal(request.path, run_id=request.run_id, limit=request.limit,
                                         observer=self._checkpoint, step_id=request.step_id)
            self._checkpoint(self._scanned)
        except (CancelledError, AsyncCancelledError):
            return JournalReadOutcome(request.request_id, "cancelled", scanned=self._scanned)
        except (AutoControlException, OSError, ValueError, TypeError, RuntimeError) as error:
            detail = scrub_secret_text(f"{type(error).__name__}: {error}")
            return JournalReadOutcome(request.request_id, "error", scanned=self._scanned, error=detail)
        return JournalReadOutcome(request.request_id, "ok", events=events, scanned=self._scanned)
