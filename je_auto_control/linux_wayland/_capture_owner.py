"""Bind one Wayland capture to the managed operation that asked for it.

A portal capture can wait on a consent dialog for half a minute, and any tier can be slow. By the
time the image arrives its task may have been stopped, replaced, or lost its authority. Inside a
managed operation the same operation must still be current, and its own live checkpoint (which
re-reads cancellation, deadline and the owner's authority) must pass before and after the capture;
otherwise the image is dropped here and never reaches a caller. Outside one nothing changes.
"""
from __future__ import annotations

import sys
from typing import Any, Callable, TypeVar

from je_auto_control.utils.exception.exceptions import AutoControlScreenException

_CONTEXT = "je_auto_control.utils.agent_runtime.context"
_T = TypeVar("_T")


def _current() -> Any:
    # Looked up, not imported: a managed operation exists only once its module is loaded, and the
    # runtime package must be able to import this backend without a cycle.
    context = sys.modules.get(_CONTEXT)
    return None if context is None else context.current_operation()


def owned_capture(capture: Callable[[], _T]) -> _T:
    """Return ``capture()`` only while the operation that requested it is still current and allowed."""
    operation = _current()
    if operation is None:
        return capture()
    operation.checkpoint()
    result = capture()
    if _current() is not operation:
        raise AutoControlScreenException("the operation that requested this capture is no longer current")
    operation.checkpoint()
    return result


__all__ = ["owned_capture"]
