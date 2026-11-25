"""Run read-only accessibility walks on one long-lived thread, so a stop ends the wait for a slow walk.

A UI Automation walk of a busy desktop can take seconds, and a stop used to wait it out. The
generic ``stoppable_call`` would start a thread per call, and the Windows backend keeps one COM
apartment and automation object per thread, so every call would create and strand another. This
module keeps one worker thread instead: each read runs there in turn, under the caller's context,
and a stopped caller stops waiting while the read finishes in the background and its result is
discarded. Outside a stoppable run or cancellation scope a read is a plain call on the caller's
thread, as before. Writes (set value, invoke, toggle) never come here: a write the caller gave up
on must not still land.

A read that is still running when its caller gives up may be hung, so that worker is retired and
the next read starts a fresh one: one stuck walk strands one thread instead of blocking every later
read in the process. A read whose caller gave up before it started never runs.
"""
import contextvars
from dataclasses import dataclass, field
import queue
import threading
from typing import Any, Callable, Optional

from je_auto_control.utils.exception.cancellation import cancellation_checkpoint, current_cancellation_token
from je_auto_control.utils.executor import run_control

_POLL_SECONDS = 0.1


@dataclass(eq=False)
class _Job:
    """One read and its outcome; ``owner`` (the worker running it) and ``abandoned`` are under the walker's lock."""

    read: Callable[[], Any]
    done: threading.Event = field(default_factory=threading.Event)
    owner: Optional["_Worker"] = None
    abandoned: bool = False
    value: Any = None
    error: Optional[BaseException] = None


class _Worker:
    """One daemon thread draining its own queue until it is retired."""

    def __init__(self, lock: threading.Lock) -> None:
        self._lock = lock
        self.jobs: "queue.Queue[Optional[_Job]]" = queue.Queue()
        self.thread = threading.Thread(target=self._run, name="AccessibilityWalker", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        while True:
            job = self.jobs.get()
            if job is None:
                return
            with self._lock:
                if job.abandoned:
                    continue
                job.owner = self
            try:
                job.value = job.read()
            except BaseException as error:  # NOSONAR python:S5754  # reason: the waiting caller raises it
                job.error = error
            finally:
                job.done.set()


class _Walker:
    """Hand reads to the current worker; replace it when one is abandoned mid-read."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._worker: Optional[_Worker] = None

    @property
    def thread(self) -> Optional[threading.Thread]:
        """The current worker thread, once started."""
        worker = self._worker
        return None if worker is None else worker.thread

    def _submit(self, job: _Job) -> None:
        with self._lock:
            if self._worker is None or not self._worker.thread.is_alive():
                self._worker = _Worker(self._lock)
            self._worker.jobs.put(job)

    def _abandon(self, job: _Job) -> None:
        with self._lock:
            job.abandoned = True
            worker = job.owner  # the worker it runs on, which a transfer may have changed
            if worker is None or job.done.is_set() or self._worker is not worker:
                return
            # Still reading, so possibly hung: later reads must not queue behind it. Reads already
            # queued move to a fresh worker; the old thread ends if its read ever returns.
            replacement = _Worker(self._lock)
            self._worker = replacement
            while True:
                try:
                    waiting = worker.jobs.get_nowait()
                except queue.Empty:
                    break
                replacement.jobs.put(waiting)
            worker.jobs.put(None)

    def call(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run on the worker; wake and raise on a stop or cancellation while waiting."""
        cancellation_checkpoint()
        run_control.checkpoint()
        context = contextvars.copy_context()
        job = _Job(lambda: context.run(function, *args, **kwargs))
        self._submit(job)
        try:
            while not job.done.wait(_POLL_SECONDS):
                cancellation_checkpoint()
                run_control.checkpoint()
        except BaseException:
            self._abandon(job)
            raise
        if job.error is not None:
            raise job.error
        return job.value


_WALKER = _Walker()
_ON_WALKER_NAME = "AccessibilityWalker"


def stoppable_read(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Inside a stoppable run or cancellation scope, read on the walker; otherwise call directly.

    A read made by a read is already on a walker thread and runs there directly: queueing it
    behind the one waiting for it would never finish.
    """
    nested = threading.current_thread().name == _ON_WALKER_NAME
    if nested or (run_control.current_stop_token() is None and current_cancellation_token() is None):
        return function(*args, **kwargs)
    return _WALKER.call(function, *args, **kwargs)
