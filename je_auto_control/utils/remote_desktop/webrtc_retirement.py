"""Serialize peer generations and retain unfinished software stop attempts.

Completion here acknowledges the stop coroutine, not native device retirement.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import Future, TimeoutError
from contextlib import asynccontextmanager
import threading
from typing import AsyncIterator, Callable, Coroutine, Any, Protocol, TypeVar

from je_auto_control.utils.exception.exceptions import AutoControlException
from je_auto_control.utils.exception.control_signals import raise_caused_run_interruption


_STOP_TIMEOUT_S = 3.0


class PeerLifecycleError(AutoControlException, RuntimeError):
    """A peer ownership transition could not be completed."""


class PeerStopPending(PeerLifecycleError):
    """The original stop attempt is still running; its owner must be retained."""


class PeerStopFailed(PeerLifecycleError):
    """A stop attempt failed; the remaining resources still need explicit retry."""


class Stoppable(Protocol):
    def stop(self) -> None: ...


Resource = TypeVar("Resource", bound=Stoppable)


class CleanupAttempt:
    """Attempt independent cleanup steps and retain each unsuccessful resource."""

    def __init__(self) -> None:
        self.failed: list[str] = []
        self.pending: list[str] = []
        self._errors: list[BaseException] = []

    def run(self, action: Callable[[], None], label: str) -> bool:
        try:
            action()
        except PeerStopPending:
            self.pending.append(label)
            return False
        except BaseException as error:  # reason: finish independent cleanup before preserving controls
            self._errors.append(error)
            self.failed.append(label)
            return False
        return True

    async def wait(self, action: Callable[[], Coroutine[Any, Any, None]], label: str) -> bool:
        try:
            await action()
        except PeerStopPending:
            self.pending.append(label)
            return False
        except BaseException as error:  # reason: retain failures until independent asynchronous cleanup has run
            self._errors.append(error)
            self.failed.append(label)
            return False
        return True

    def stop(self, resource: Resource | None, label: str) -> Resource | None:
        if resource is not None and not self.run(resource.stop, label):
            return resource
        return None

    def finish(self) -> None:
        for error in self._errors:
            raise_caused_run_interruption(error)
        if self.failed:
            raise PeerStopFailed("unfinished cleanup: " + ", ".join(self.failed))
        if self.pending:
            raise PeerStopPending("pending cleanup: " + ", ".join(self.pending))


def stop_resource(resource: Stoppable | None, label: str) -> None:
    """Return only after the resource's stop call succeeds; preserve its error."""
    if resource is not None:
        resource.stop()


class PeerRetirement:
    """One stop future per attempt, with exclusive async generation changes."""

    def __init__(self) -> None:
        self._mutex = threading.Lock()
        self._serial = asyncio.Lock()
        self._future: Future[None] | None = None
        self.unsettled = False
        self._failed = False

    def require_startable(self) -> None:
        if self._failed:
            raise PeerStopFailed("retry the previous peer stop before restarting")
        with self._mutex:
            future = self._future
        if future is not None:
            if not future.done():
                raise PeerStopPending("previous peer stop is still running")
            if future.exception() is not None:
                raise PeerStopFailed("retry the previous peer stop before restarting")

    def admit_start(self) -> None:
        """Own a queued startup before handing its coroutine to the bridge."""
        self.require_startable()
        self.unsettled = True

    @asynccontextmanager
    async def starting(self) -> AsyncIterator[None]:
        self.require_startable()
        async with self._serial:
            self.require_startable()
            self.unsettled = True
            try:
                yield
            except BaseException:  # reason: Mark failed ownership even when startup is explicitly interrupted.
                self._failed = True
                raise

    async def retire(self, expected: object, current: Callable[[], object],
                     operation: Callable[[], Coroutine[Any, Any, None]]) -> None:
        async with self._serial:
            if current() is not expected:
                return
            self.unsettled = True
            self._failed = True
            await operation()
            self._failed = False
            self.unsettled = False

    def stop(self, submit: Callable[[Coroutine[Any, Any, None]], Future[None]],
             operation: Callable[[], Coroutine[Any, Any, None]],
             timeout: float | None = None) -> None:
        with self._mutex:
            if self._future is None or self._future.done():
                launch = True
                future = Future[None]()
                self._future = future
            else:
                launch = False
                future = self._future
        try:
            if launch:
                self._submit(submit, operation, future)
            future.result(timeout=_STOP_TIMEOUT_S if timeout is None else timeout)
        except TimeoutError as error:
            raise_caused_run_interruption(error)
            if not future.done():
                raise PeerStopPending("peer stop is still running") from error
            raise PeerStopFailed("peer stop failed") from error
        except Exception as error:  # reason: Normalize transport failures without converting cancellation to success.
            raise_caused_run_interruption(error)
            raise PeerStopFailed("peer stop failed") from error

    @staticmethod
    def _submit(submit: Callable[[Coroutine[Any, Any, None]], Future[None]],
                operation: Callable[[], Coroutine[Any, Any, None]],
                retained: Future[None]) -> None:
        coroutine = None
        try:
            coroutine = operation()
            actual = submit(coroutine)
        except BaseException as error:  # reason: Publish submission failure to every waiter, preserving its identity.
            if coroutine is not None:
                coroutine.close()
            retained.set_exception(error)
            raise

        def completed(result: Future[None]) -> None:
            try:
                result.result()
            except BaseException as error:  # reason: Relay every terminal outcome to the retained future.
                retained.set_exception(error)
            else:
                retained.set_result(None)

        actual.add_done_callback(completed)
