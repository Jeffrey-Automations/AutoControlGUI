"""Run accessibility walks and writes on one long-lived thread, so a stop ends the wait for a slow walk.

A UI Automation walk of a busy desktop can take seconds, and a stop used to wait it out. The
generic ``stoppable_call`` would start a thread per call, and the Windows backend keeps one COM
apartment and automation object per thread, so every call would create and strand another. This
module keeps one worker thread instead: each call runs there in turn, under the caller's context.
Outside a stoppable run or cancellation scope a call is a plain call on the caller's thread, as before.

A read whose caller stops is abandoned: the caller stops waiting while the read finishes in the
background and its result is discarded. A write (set value, invoke, toggle) is one job that finds
the control and then acts, and the act must not land for a caller that already gave up, so the
backend calls :func:`begin_act` between the two. A stop before that point ends the wait and the act
never happens; once the act has begun, a stopped caller waits up to ``_ACT_GRACE_SECONDS`` for it
and reports its result, or raises :class:`AccessibilityWriteOutcomeUnknown`. A backend that does not
declare ``gates_writes`` has no such point, so its whole call counts as the act. No COM object
crosses a thread: the find and the act run on the same worker.

A job that is still running when its caller gives up may be hung, so that worker is retired and
the next job starts a fresh one: one stuck walk strands one thread instead of blocking every later
call in the process. A job whose caller gave up before it started never runs.
"""
import contextvars
from dataclasses import dataclass, field
import queue
import threading
from typing import Any, Callable, Optional

from je_auto_control.utils.exception.cancellation import (
    CancellationToken, cancellation_checkpoint, current_cancellation_token,
)
from je_auto_control.utils.exception.exceptions import AutoControlException
from je_auto_control.utils.executor import run_control

_POLL_SECONDS = 0.1
#: How long a stopped caller waits for an act that had already begun.
_ACT_GRACE_SECONDS = 5.0


class AccessibilityWriteOutcomeUnknown(AutoControlException):
    """A stop arrived while an accessibility write was acting, and the act did not finish in time.

    The write may or may not have landed; read the control back before relying on either.
    """


@dataclass(frozen=True)
class _CallerStop:
    """The stop and cancellation a write's caller answers to, readable from the worker thread."""

    token: Optional[run_control.StopToken]
    shield: int
    cancel: Optional[CancellationToken]

    @classmethod
    def capture(cls) -> "_CallerStop":
        """What the calling thread answers to now (the stop token is bound to that thread)."""
        return cls(run_control.current_stop_token(), run_control.shield_depth(), current_cancellation_token())

    def raise_if_requested(self) -> None:
        """Raise what the caller's own checkpoints would raise, without blocking."""
        if self.cancel is not None:
            self.cancel.checkpoint()
        token = self.token
        if token is not None and token.stopped and (not self.shield or token.forced):
            raise run_control.ExecutionStopped(token.run_id, token.reason)


@dataclass(eq=False)
class _Job:
    """One call and its outcome; ``owner``, ``abandoned`` and ``acting`` are under the walker's lock.

    ``caller`` is set for a write only; ``acting`` records that its act has begun.
    """

    read: Callable[[], Any]
    caller: Optional[_CallerStop] = None
    done: threading.Event = field(default_factory=threading.Event)
    owner: Optional["_Worker"] = None
    abandoned: bool = False
    acting: bool = False
    value: Any = None
    error: Optional[BaseException] = None

    def outcome(self) -> Any:
        """The call's value, or raise its error."""
        if self.error is not None:
            raise self.error
        return self.value


#: The job the current worker thread is running.
_RUNNING = threading.local()


class _Worker:
    """One daemon thread draining its own queue until it is retired; ``_RUNNING.job`` is its current job."""

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
            _RUNNING.job = job
            try:
                job.value = job.read()
            except BaseException as error:  # NOSONAR python:S5754  # reason: the waiting caller raises it
                job.error = error
            finally:
                _RUNNING.job = None
                job.done.set()


class _Walker:
    """Hand jobs to the current worker; replace it when one is abandoned mid-job."""

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

    def _retire(self, worker: Optional[_Worker]) -> None:
        """Replace ``worker`` if it is still current; call with the lock held."""
        if worker is None or self._worker is not worker:
            return
        # Possibly hung: later jobs must not queue behind it. Jobs already queued move to a
        # fresh worker; the old thread ends if its job ever returns.
        replacement = _Worker(self._lock)
        self._worker = replacement
        while True:
            try:
                waiting = worker.jobs.get_nowait()
            except queue.Empty:
                break
            replacement.jobs.put(waiting)
        worker.jobs.put(None)

    def _abandon(self, job: _Job) -> bool:
        """Give up on ``job`` unless its act has begun; return whether the caller must wait for that act."""
        with self._lock:
            if job.acting:
                return True
            job.abandoned = True
            if not job.done.is_set():
                self._retire(job.owner)  # the worker it runs on, which a transfer may have changed
            return False

    def begin_act(self, job: _Job) -> None:
        """Mark the act begun, or raise when the caller stopped or gave up first."""
        caller = job.caller
        if caller is None:
            return
        with self._lock:
            if job.abandoned:
                run_id = caller.token.run_id if caller.token is not None else ""
                raise run_control.ExecutionStopped(run_id, "the caller stopped waiting before the act")
            caller.raise_if_requested()
            job.acting = True

    def _await_act(self, job: _Job, stop: BaseException) -> None:
        """A stop arrived after the act began: wait for that act, bounded."""
        if job.done.wait(_ACT_GRACE_SECONDS):
            return
        with self._lock:
            job.abandoned = True
            self._retire(job.owner)
        raise AccessibilityWriteOutcomeUnknown(
            f"stopped while an accessibility write was acting; it did not finish within "
            f"{_ACT_GRACE_SECONDS:g} s, so whether it landed is unknown") from stop

    def _wait(self, job: _Job) -> None:
        while not job.done.wait(_POLL_SECONDS):
            cancellation_checkpoint()
            run_control.checkpoint()

    def call(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run on the worker; wake and raise on a stop or cancellation while waiting."""
        cancellation_checkpoint()
        run_control.checkpoint()
        context = contextvars.copy_context()
        job = _Job(lambda: context.run(function, *args, **kwargs))
        self._submit(job)
        try:
            self._wait(job)
        except BaseException:
            self._abandon(job)
            raise
        return job.outcome()

    def write(self, gated: bool, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run a find-then-act job on the worker; a stop prevents the act, or waits for one begun."""
        cancellation_checkpoint()
        run_control.checkpoint()
        context = contextvars.copy_context()

        def run() -> Any:
            if not gated:
                begin_act()  # no gate inside the call: all of it is the act
            return context.run(function, *args, **kwargs)
        job = _Job(run, caller=_CallerStop.capture())
        self._submit(job)
        try:
            self._wait(job)
        except BaseException as stop:
            if not self._abandon(job):
                raise
            self._await_act(job, stop)
            if not isinstance(stop, Exception):
                raise  # an interrupt still propagates once the act is over
        return job.outcome()


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


def stoppable_write(function: Callable[..., Any], *args: Any, gated: bool = False, **kwargs: Any) -> Any:
    """Inside a stoppable run or cancellation scope, write on the walker; otherwise call directly.

    ``gated`` says that ``function`` calls :func:`begin_act` between finding its control and acting
    on it; without it a stop that arrives once the call has started waits for the whole call.
    """
    nested = threading.current_thread().name == _ON_WALKER_NAME
    if nested or (run_control.current_stop_token() is None and current_cancellation_token() is None):
        return function(*args, **kwargs)
    return _WALKER.write(gated, function, *args, **kwargs)


def begin_act() -> None:
    """Called by a backend after finding a control and before acting: the last point a stop prevents the act.

    Raises ``ExecutionStopped`` (or the cancellation) when the write's caller stopped first. A no-op
    anywhere but inside a write on the walker, so a backend can call it unconditionally.
    """
    job = getattr(_RUNNING, "job", None)
    if job is not None:
        _WALKER.begin_act(job)
