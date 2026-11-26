"""Bring an error from outside the framework family into the executor's per-action containment.

The executor records a failed action and goes on (``raise_on_error=False``)
for the errors its boundary names: the ``AutoControlException`` family and a
handful of builtins. ``cv2.error``, ``sqlite3.Error`` and a plugin's own
exception class derive only from ``Exception``, so one of them aborted every
remaining action instead. :func:`call_contained` wraps such an error in
:class:`AutoControlForeignException` at the innermost action, so the executor,
``AC_try``, ``AC_retry`` and ``AC_parallel`` all treat it as that action's
failure. What must never be contained still passes through unchanged: assertion
failures (the framework's and a plugin's own ``assert``), loop signals, a stop,
cancellation, and ``KeyboardInterrupt`` / ``SystemExit`` (not ``Exception``).
"""
from typing import Any, Callable

from je_auto_control.utils.exception.control_signals import raise_if_run_interrupted
from je_auto_control.utils.exception.exceptions import AutoControlForeignException
from je_auto_control.utils.executor.flow_control import _TRY_CATCHABLE, LoopBreak, LoopContinue

#: Raised unchanged: already contained by the boundary, or never to be contained.
_PASS_THROUGH = _TRY_CATCHABLE + (AssertionError, LoopBreak, LoopContinue)


def call_contained(command: str, call: Callable[..., Any], *args: Any) -> Any:
    """``call(*args)``, with an error outside the contained family raised as a framework error."""
    try:
        return call(*args)
    except _PASS_THROUGH:
        raise
    except Exception as error:  # reason: wrapped and re-raised, never swallowed
        raise_if_run_interrupted(error)
        raise AutoControlForeignException(command, error) from error


__all__ = ["call_contained"]
