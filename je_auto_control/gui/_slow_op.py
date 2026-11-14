"""Slow starts and stops for a tab, off the GUI thread.

A Stop that joins a thread holds the GUI thread for as long as the join takes
(2-6 s for the servers and engines the tabs drive). Two helpers hand that call
to the :mod:`~je_auto_control.gui.tab_task_controller` and keep what the tabs need
around it.

:class:`SlowOp`, for a tab that drives one backend:

* **One at a time.** :meth:`SlowOp.run` returns ``False`` while an earlier call
  is still out, so a second click is ignored instead of starting a second stop
  beside the first.
* **A state to show.** :attr:`SlowOp.busy` is true from :meth:`~SlowOp.run`
  until the outcome has been delivered, and it is already false again when
  ``on_done`` / ``on_error`` run -- so they can simply re-read the backend and
  repaint. A tab paints its "stopping" text while ``busy`` is true.
* **Ordering.** What used to follow the blocking call on the next line (reading
  the registry, repainting the badge) goes in ``on_done``, which runs on the GUI
  thread after the work returned.

:class:`StopQueue`, for a panel that lets go of its session at once and may
open the next one straight away (the WebRTC panels).

The work must not hold a widget: read what it needs first and pass plain
values, as for any :class:`~je_auto_control.gui.tab_task_controller.TaskController`
work.

Callbacks are held weakly. ``on_done`` / ``on_error`` are normally methods of
the tab, and the task's handle is a grandchild of that tab: a connection that
kept the tab's wrapper alive released it from inside the handle's destructor,
which destroyed a parentless tab in the middle of destroying its own child and
aborted the process. A bound method is therefore kept as a weak reference plus
the leading arguments given in ``args`` (:mod:`je_auto_control.gui._weak_call`);
pass a method and ``args``, never a lambda that closes over the tab.
"""
import functools
from typing import Any, Callable, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal

from je_auto_control.gui._weak_call import Callback, WeakCall as _WeakCall, weak_slot
from je_auto_control.gui.tab_task_controller import (
    CancellationToken, TaskController, TaskUsageError, _widgets_reachable_from, task_controller,
)
from je_auto_control.gui._stop_custody import stop_custody
from je_auto_control.utils.exception.exceptions import AutoControlException
from je_auto_control.utils.logging.logging_instance import autocontrol_logger
from je_auto_control.utils.rbac.deferred import DeferredAuthorization


def _call(work: Callable[[], Any], _token: CancellationToken) -> Any:
    """Worker thread: run the work; a stop has nothing to poll a token for."""
    return work()


def _log_failure(error: object) -> None:
    """A failed stop with nobody to tell is still recorded."""
    autocontrol_logger.warning(f"GUI background operation failed: {error!r}")


class StopsFailed(AutoControlException, RuntimeError):
    """Some of :func:`stop_each`'s stops raised; ``failures`` pairs each with its error."""

    def __init__(self, failures: List[Tuple[Callable[[], Any], BaseException]]) -> None:
        super().__init__("; ".join(f"{type(error).__name__}: {error}" for _stop, error in failures))
        self.failures = failures


def hold_failed_stop(stop: Callable[[], Any], error: object,
                     authority: Optional[DeferredAuthorization] = None) -> None:
    """Hand a failed stop to the application's custody (each one of a :class:`StopsFailed` separately)."""
    if isinstance(error, StopsFailed):
        for inner, inner_error in error.failures:
            stop_custody().hold(inner, inner_error, authority=authority)
    else:
        stop_custody().hold(stop, error, authority=authority)


def _refuse_widgets(work: Callable[[], Any]) -> None:
    """Raise unless ``work`` is free of widgets (the controller only sees the wrapper around it)."""
    if _widgets_reachable_from(work):
        raise TaskUsageError(
            "background work must not hold a widget: read what it needs first and pass plain values")


class SlowOp(QObject):
    """Runs one blocking call at a time for its parent widget; see the module docstring."""

    #: Emitted with the new value whenever :attr:`busy` changes.
    busy_changed = Signal(bool)

    def __init__(self, owner: QObject, controller: Optional[TaskController] = None) -> None:
        super().__init__(owner)
        self._controller = controller
        self._busy = False
        self._on_done = _WeakCall(None)
        self._on_error = _WeakCall(None)

    @property
    def busy(self) -> bool:
        """Whether a call handed to :meth:`run` has not reported yet."""
        return self._busy

    def run(self, work: Callable[[], Any], *,   # noqa: PLR0913  # reason: keyword-only options of one call
            on_done: Callback = None, on_error: Callback = None, args: Tuple[Any, ...] = (),
            discard: Optional[Callable[[Any], object]] = None,
            timeout_s: Optional[float] = None, retain_failure: bool = False) -> bool:
        """Run ``work()`` off the GUI thread; return ``False`` (and do nothing) while busy.

        ``on_done(*args, result)`` or ``on_error(*args, exception)`` runs on
        the GUI thread once the work returned, after :attr:`busy` went back to
        false. Neither runs when the owner was destroyed meanwhile; the work
        itself still runs to its end, and what it returned then goes to
        ``discard`` (stop the server nobody is left to show). An error nobody
        handles is logged. With ``retain_failure`` -- for a stop, never a start
        -- a failure is also kept by the stop custody, under the authority
        captured now, so it can be retried from the Diagnostics tab.
        """
        if self._busy:
            return False
        _refuse_widgets(work)
        controller = self._controller if self._controller is not None else task_controller()
        handle = controller.submit(functools.partial(_call, work), owner=self, timeout_s=timeout_s,
                                   discard=discard)
        self._busy = True
        self._on_done = _WeakCall(on_done, args)
        self._on_error = _WeakCall(on_error, args)
        handle.result.connect(self._deliver_result)
        handle.error.connect(self._deliver_error)
        if retain_failure:
            handle.error.connect(functools.partial(hold_failed_stop, work,
                                                   authority=DeferredAuthorization.capture()))
        handle.finished.connect(self._settle)
        self.busy_changed.emit(True)
        return True

    def _deliver_result(self, value: object) -> None:
        on_done = self._on_done
        self._settle()
        on_done(value)

    def _deliver_error(self, error: object) -> None:
        on_error = self._on_error
        self._settle()
        if not on_error(error):
            _log_failure(error)

    def _settle(self) -> None:
        """GUI thread: the call reported (or was cancelled); accept the next one."""
        if not self._busy:
            return
        self._busy = False
        self._on_done = self._on_error = _WeakCall(None)
        self.busy_changed.emit(False)


class StopQueue(QObject):
    """Blocking shutdowns of things a panel has already let go of.

    The panel clears its own reference on the GUI thread, then hands the
    object's ``stop`` here. Any number may be out together; :attr:`pending`
    counts them and :attr:`drained` is emitted when the last one has reported,
    which is when a "stopping" text can go.
    """

    #: Emitted on the GUI thread when no shutdown is out any more.
    drained = Signal()

    def __init__(self, owner: QObject, controller: Optional[TaskController] = None) -> None:
        super().__init__(owner)
        self._controller = controller
        self._pending = 0

    @property
    def pending(self) -> int:
        """How many shutdowns have not reported yet."""
        return self._pending

    def retire(self, stop: Callable[[], Any], *, on_done: Callback = None,
               on_error: Callback = None, args: Tuple[Any, ...] = ()) -> None:
        """Run ``stop()`` off the GUI thread; ``on_done(*args, result)`` follows on the GUI thread.

        ``on_error(*args, exception)`` follows instead when it raised, for a
        panel that shows a state until its stop reports (both are held weakly).

        A shutdown that raises is kept by :func:`~je_auto_control.gui._stop_custody.stop_custody`,
        with the caller's authority captured now, so it can be retried from
        the Diagnostics tab: the object is out of the panel's hands, but its
        resource may still be held.
        """
        _refuse_widgets(stop)
        controller = self._controller if self._controller is not None else task_controller()
        handle = controller.submit(functools.partial(_call, stop), owner=self)
        self._pending += 1
        handle.error.connect(functools.partial(hold_failed_stop, stop, authority=DeferredAuthorization.capture()))
        if on_done is not None:
            handle.result.connect(weak_slot(on_done, *args))     # a weak call, never the panel
        if on_error is not None:
            handle.error.connect(weak_slot(on_error, *args))
        handle.finished.connect(self._one_reported)

    def _one_reported(self) -> None:
        self._pending = max(0, self._pending - 1)
        if self._pending == 0:
            self.drained.emit()


def stop_each(*stops: Callable[[], Any]) -> None:
    """Worker thread: call every ``stop`` in order; one that fails does not keep the rest from running.

    Raises :class:`StopsFailed` afterwards when any did, naming each failed
    stop, so a :class:`StopQueue` keeps every one of them for a retry.
    """
    failures: List[Tuple[Callable[[], Any], BaseException]] = []
    for stop in stops:
        try:
            stop()
        except Exception as error:  # noqa: BLE001  # reason: collected and raised below; the remaining shutdowns must still run
            failures.append((stop, error))
    if failures:
        raise StopsFailed(failures)


__all__ = ["SlowOp", "StopQueue", "StopsFailed", "hold_failed_stop", "stop_each"]
