"""Run read-only accessibility walks on one long-lived thread, so a stop ends the wait for a slow walk.

A UI Automation walk of a busy desktop can take seconds, and a stop used to wait it out. The
generic ``stoppable_call`` would start a thread per call, and the Windows backend keeps one COM
apartment and automation object per thread, so every call would create and strand another. This
module owns exactly one worker thread for the process: each read runs there in turn, under the
caller's context, and a stopped caller stops waiting while the read finishes in the background
and its result is discarded. Outside a stoppable run or cancellation scope a read is a plain call
on the caller's thread, as before. Writes (set value, invoke, toggle) never come here: a write the
caller gave up on must not still land.
"""
import contextvars
import queue
import threading
from typing import Any, Callable, Dict, Optional, Tuple

from je_auto_control.utils.exception.cancellation import cancellation_checkpoint, current_cancellation_token
from je_auto_control.utils.executor import run_control

_POLL_SECONDS = 0.1
_Job = Tuple[contextvars.Context, Callable[..., Any], Tuple[Any, ...], Dict[str, Any], Dict[str, Any],
             threading.Event]


class _Walker:
    """One daemon worker draining read jobs in order; it lives for the process."""

    def __init__(self) -> None:
        self._jobs: "queue.Queue[_Job]" = queue.Queue()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def _ensure(self) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="AccessibilityWalker", daemon=True)
                self._thread.start()

    @property
    def thread(self) -> Optional[threading.Thread]:
        """The worker, once started."""
        return self._thread

    def _run(self) -> None:
        while True:
            context, function, args, kwargs, outcome, done = self._jobs.get()
            try:
                outcome["value"] = context.run(function, *args, **kwargs)
            except BaseException as error:  # NOSONAR python:S5754  # reason: the waiting caller raises it
                outcome["error"] = error
            finally:
                done.set()

    def call(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run on the worker; wake and raise on a stop or cancellation while waiting."""
        cancellation_checkpoint()
        run_control.checkpoint()
        self._ensure()
        outcome: Dict[str, Any] = {}
        done = threading.Event()
        self._jobs.put((contextvars.copy_context(), function, args, kwargs, outcome, done))
        while not done.wait(_POLL_SECONDS):
            cancellation_checkpoint()
            run_control.checkpoint()
        if "error" in outcome:
            raise outcome["error"]
        return outcome["value"]


_WALKER = _Walker()


def stoppable_read(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Inside a stoppable run or cancellation scope, read on the walker; otherwise call directly."""
    if run_control.current_stop_token() is None and current_cancellation_token() is None:
        return function(*args, **kwargs)
    return _WALKER.call(function, *args, **kwargs)
