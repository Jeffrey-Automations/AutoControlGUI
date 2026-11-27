"""Query a specified HWND's current owner and child windows without activation or input."""
from __future__ import annotations

import ctypes
import sys
from typing import Any, Protocol, cast

from .models import FailureReason, MemoryObservationError
from .windows_native import NativeFunction, PTR, U32

_MAX_CHILDREN = 4096


class WindowApi(Protocol):
    """Only the documented window-owner and child-window queries are available to this binding."""

    GetWindowThreadProcessId: NativeFunction
    EnumChildWindows: NativeFunction


class WindowOwnerQuery:
    """Host-created query; injected functions allow verification without touching the desktop."""

    def __init__(self, api: WindowApi | None = None) -> None:
        if api is None:
            if sys.platform != "win32":
                raise MemoryObservationError(FailureReason.UNSUPPORTED)
            api = cast(WindowApi, ctypes.WinDLL("user32", use_last_error=True))
        self._api = api
        api.GetWindowThreadProcessId.argtypes = [PTR, ctypes.POINTER(U32)]
        api.GetWindowThreadProcessId.restype = U32

    def process_id(self, hwnd: int) -> int:
        """Return the current nonzero PID; a handle alone does not prove window lifetime."""
        if type(hwnd) is not int or not 0 < hwnd < 2 ** (ctypes.sizeof(PTR) * 8):
            raise MemoryObservationError(FailureReason.TARGET_CHANGED)
        pid = U32()
        thread = self._api.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not thread or not pid.value:
            raise MemoryObservationError(FailureReason.TARGET_CHANGED)
        return pid.value

    def children(self, hwnd: int) -> tuple[int, ...]:
        """Every descendant window of ``hwnd``, which must still be live; more than the limit refuses.

        Returned handles carry no authority: a caller checks each one's owner before using it.
        """
        self.process_id(hwnd)
        found: list[int] = []
        # WINFUNCTYPE exists only on Windows; injected queries elsewhere accept either convention.
        function = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(ctypes.c_int, PTR, PTR)

        def visit(child: Any, _value: Any) -> int:
            found.append(int(child or 0))
            return int(len(found) <= _MAX_CHILDREN)

        callback = function(visit)
        enumerate_children = self._api.EnumChildWindows
        enumerate_children.argtypes = [PTR, function, PTR]
        enumerate_children.restype = ctypes.c_int  # documented as unused: the count below decides
        enumerate_children(hwnd, callback, None)
        if len(found) > _MAX_CHILDREN:
            raise MemoryObservationError(FailureReason.BUDGET_EXCEEDED)
        self.process_id(hwnd)
        return tuple(found)
