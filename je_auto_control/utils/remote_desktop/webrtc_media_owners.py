"""Original media owners retained across peer constructor and cleanup failures."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import partial
import threading
from typing import Callable, Coroutine, Protocol, TypeVar, runtime_checkable

from je_auto_control.utils.exception.control_signals import raise_caused_run_interruption
from je_auto_control.utils.logging.logging_instance import autocontrol_logger
from je_auto_control.utils.remote_desktop.media_retirement import (
    Completion, MediaRetirementError, RetirementOwner, RetirementStatus, interrupted_retirement_owners,
)
from je_auto_control.utils.remote_desktop.webrtc_retirement import (
    CleanupAttempt, PeerStopFailed, PeerStopPending, Stoppable,
)


@runtime_checkable
class AsyncMediaStop(Protocol):
    async def stop_confirmed(self) -> None: ...


async def stop_media(resource: Stoppable) -> None:
    """Observe actual asynchronous completion when the producer provides it."""
    if isinstance(resource, AsyncMediaStop):
        await resource.stop_confirmed()
    else:
        resource.stop()


@dataclass(frozen=True)
class MediaFailure:
    slot: str
    status: RetirementStatus | None


Media = TypeVar("Media", bound=Stoppable)


class PeerMediaOwners:
    """Keep field failures and constructor orphans without replacing typed fields."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._operation_locks: dict[str, threading.RLock] = {}
        self._active: set[str] = set()
        self._failed: dict[str, RetirementStatus | None] = {}
        self._orphans: list[tuple[str, RetirementOwner]] = []
        self._snapshots: dict[int, RetirementStatus] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def operation_lock(self, slot: str) -> threading.RLock:
        with self._lock:
            if slot not in self._operation_locks:
                self._operation_locks[slot] = threading.RLock()
            return self._operation_locks[slot]

    @property
    def unsettled(self) -> bool:
        with self._lock:
            return bool(self._active or self._failed or self._orphans or self._tasks)

    @property
    def failures(self) -> tuple[MediaFailure, ...]:
        with self._lock:
            fields = tuple(MediaFailure(slot, status) for slot, status in self._failed.items())
            orphans = tuple(MediaFailure(slot, self._snapshots[id(owner)])
                            for slot, owner in self._orphans)
            pending = tuple(MediaFailure(slot, self._task_status(task))
                            for slot, task in self._tasks.items()
                            if not task.done() and slot not in self._failed)
            return fields + orphans + pending

    @staticmethod
    def _task_status(task: asyncio.Task[None]) -> RetirementStatus:
        closed = task.get_loop().is_closed()
        return RetirementStatus(True, Completion.UNCERTAIN if closed else Completion.PENDING,
                                Completion.CONFIRMED, not closed, ("media.task_pending",))

    def require_available(self, slot: str | None = None) -> None:
        with self._lock:
            failed = set(self._failed) | {name for name, _ in self._orphans} | set(self._tasks)
            blocked = bool(failed) if slot is None else slot in failed
            if blocked:
                raise PeerStopFailed("original media cleanup remains unresolved")

    def create(self, slot: str, factory: Callable[[], Media], *, optional: bool = True) -> Media | None:
        self.require_available(slot)
        with self._lock:
            self._active.add(slot)
        try:
            resource = factory()
        except BaseException as error:  # reason: adopt constructor owners before preserving controls
            with self._lock:
                self.adopt(slot, error)
                self._active.discard(slot)
            raise_caused_run_interruption(error)
            if not optional or not isinstance(error, (RuntimeError, OSError)):
                raise
            autocontrol_logger.warning("%s initialization failed", slot)
            return None
        return resource

    def activate(self, slot: str, action: Callable[[], None], resource: Stoppable,
                 *, admitted: Callable[[], bool] | None = None) -> None:
        try:
            if admitted is not None and not admitted():
                raise PeerStopPending("peer stopped during media startup")
            action()
            if admitted is not None and not admitted():
                raise PeerStopPending("peer stopped during media startup")
        except BaseException as error:  # reason: preserve assigned ownership before propagating startup failure
            self.failed(slot, error, resource)
            raise_caused_run_interruption(error)
            raise

    def schedule(self, slot: str, operation: Callable[[], Coroutine[object, object, None]]) -> None:
        with self._lock:
            previous = self._tasks.get(slot)
            if previous is not None and not previous.done():
                return
            if previous is not None:
                self._tasks.pop(slot)
                try:
                    previous.result()
                except BaseException as error:  # reason: explicit retry preserves controls and the cached failure
                    raise_caused_run_interruption(error)
            coroutine = operation()
            try:
                task = asyncio.create_task(coroutine)
            except BaseException:  # reason: dispose of an unsubmitted coroutine without losing its retained field
                coroutine.close()
                raise
            self._tasks[slot] = task
        task.add_done_callback(partial(self._completed, slot))

    def _completed(self, slot: str, task: asyncio.Task[None]) -> None:
        failed = task.cancelled() or task.exception() is not None
        with self._lock:
            if self._tasks.get(slot) is not task:
                return
            if failed:
                self._failed.setdefault(slot, None)
            else:
                self._tasks.pop(slot)

    async def retire_slot(self, slot: str, attempt: CleanupAttempt) -> None:
        with self._lock:
            task = self._tasks.get(slot)
        if task is None:
            return
        await attempt.wait(partial(self._observe_task, task), slot)
        if task.done():
            with self._lock:
                if self._tasks.get(slot) is task:
                    self._tasks.pop(slot)
                    if self._failed.get(slot) is None:
                        self._failed.pop(slot, None)

    @staticmethod
    async def _observe_task(task: asyncio.Task[None]) -> None:
        if not task.done():
            if task.get_loop().is_closed():
                raise PeerStopFailed("media task loop closed before completion")
            await asyncio.wait({task})
        task.result()

    def pending(self, slot: str) -> None:
        with self._lock:
            self._failed.setdefault(slot, RetirementStatus(
                True, Completion.PENDING, Completion.PENDING, True, ("media.operation_pending",)))

    def failed(self, slot: str, error: BaseException, resource: Stoppable | None = None) -> None:
        with self._lock:
            status = error.status if isinstance(error, MediaRetirementError) else None
            observed = getattr(resource, "retirement_status", None)
            if status is None and isinstance(observed, RetirementStatus):
                status = observed
            self._failed[slot] = status if status is not None else self._failed.get(slot)

    def settled(self, slot: str) -> None:
        with self._lock:
            self._active.discard(slot)
            self._failed.pop(slot, None)

    def adopt(self, slot: str, error: BaseException) -> None:
        current: BaseException | None = error
        seen: set[int] = set()
        while current is not None and id(current) not in seen and len(seen) < 64:
            seen.add(id(current))
            owners = interrupted_retirement_owners(current)
            if isinstance(current, MediaRetirementError):
                owners += (current.owner,)
            self._retain(slot, owners)
            current = current.__cause__

    def _retain(self, slot: str, owners: tuple[RetirementOwner, ...]) -> None:
        with self._lock:
            for owner in owners:
                if not any(item is owner for _, item in self._orphans):
                    self._orphans.append((slot, owner))
                self._snapshots[id(owner)] = owner.retirement_status

    def stop_field(self, slot: str, resource: Stoppable | None) -> None:
        if resource is None:
            return None
        try:
            resource.stop()
        except BaseException as error:  # reason: retain the field and failure before propagating its original signal
            self.failed(slot, error, resource)
            raise
        self.settled(slot)
        return None

    async def stop_field_async(self, slot: str, resource: Stoppable | None) -> None:
        if resource is None:
            return None
        try:
            await stop_media(resource)
        except BaseException as error:  # reason: retain the field until actual asynchronous completion is acknowledged
            self.failed(slot, error, resource)
            raise
        self.settled(slot)
        return None

    async def retire_orphans(self, attempt: CleanupAttempt) -> None:
        with self._lock:
            orphans = tuple(self._orphans)
        for slot, owner in orphans:
            if await attempt.wait(partial(self._stop_orphan, owner), slot):
                with self._lock:
                    self._orphans = [(name, item) for name, item in self._orphans if item is not owner]
                    self._snapshots.pop(id(owner), None)

    async def _stop_orphan(self, owner: RetirementOwner) -> None:
        try:
            await stop_media(owner)
        except BaseException:  # reason: refresh the retained outcome before the cleanup aggregator handles failure
            with self._lock:
                self._snapshots[id(owner)] = owner.retirement_status
            raise
