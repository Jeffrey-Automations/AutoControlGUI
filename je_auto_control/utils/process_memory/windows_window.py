"""Query a specified HWND's current owner without enumeration, activation or input."""
from __future__ import annotations

import ctypes
import sys
from typing import Protocol, cast

from .models import FailureReason, MemoryObservationError
from .windows_native import NativeFunction, PTR, U32


class WindowApi(Protocol):
    """Only the documented window-owner query is available to this binding."""

    GetWindowThreadProcessId: NativeFunction


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
