"""Bind the fixed SCM query and selected control functions without acquiring handles."""
from __future__ import annotations

import ctypes
import sys
from typing import Callable, Protocol, cast

from .service_status import ServiceFailure, ServiceQueryError, ServiceState, ServiceStatus
from .service_operations import ServiceOperation

_U32 = ctypes.c_uint32
_PTR = ctypes.c_void_p
_STATUS_FIELDS = [(name, _U32) for name in (
    "service_type", "state", "controls", "win32_exit", "service_exit", "checkpoint", "wait_hint")]


class _Function(Protocol):
    argtypes: list[object]
    restype: object

    def __call__(self, *args: object) -> int: ...


class ServiceApi(Protocol):
    """The four SCM functions needed for local status ownership."""

    OpenSCManagerW: _Function
    OpenServiceW: _Function
    QueryServiceStatusEx: _Function
    CloseServiceHandle: _Function


class ServiceStatusProcess(ctypes.Structure):
    """Nine DWORDs, independent of the caller's pointer width."""

    _fields_ = _STATUS_FIELDS + [("pid", _U32), ("flags", _U32)]


class ServiceControlApi(ServiceApi, Protocol):
    """Control functions are bound only when present in the host's allowed scope."""

    StartServiceW: _Function
    ControlService: _Function


class ServiceControlStatus(ctypes.Structure):
    """ControlService writes seven DWORDs, without process ID or service flags."""

    _fields_ = _STATUS_FIELDS


def bind_controls(api: ServiceApi, allowed: frozenset[ServiceOperation]) -> None:
    """Install only the native signatures granted by this controller's scope."""
    functions = cast(ServiceControlApi, api)
    if ServiceOperation.START in allowed:
        functions.StartServiceW.argtypes = [_PTR, _U32, ctypes.POINTER(ctypes.c_wchar_p)]
        functions.StartServiceW.restype = ctypes.c_int32
    if ServiceOperation.STOP in allowed:
        functions.ControlService.argtypes = [_PTR, _U32, ctypes.POINTER(ServiceControlStatus)]
        functions.ControlService.restype = ctypes.c_int32


def control(api: ServiceApi, handle: int, operation: ServiceOperation) -> int:
    """Dispatch one fixed control; the caller owns uncertain-outcome handling."""
    functions = cast(ServiceControlApi, api)
    if operation is ServiceOperation.START:
        return functions.StartServiceW(handle, 0, None)
    output = ServiceControlStatus()
    return functions.ControlService(handle, 1, ctypes.byref(output))


def bind(api: ServiceApi) -> None:
    """Install the four fixed local service query and ownership signatures."""
    signatures: tuple[tuple[_Function, list[object], object], ...] = (
        (api.OpenSCManagerW, [ctypes.c_wchar_p, ctypes.c_wchar_p, _U32], _PTR),
        (api.OpenServiceW, [_PTR, ctypes.c_wchar_p, _U32], _PTR),
        (api.QueryServiceStatusEx, [_PTR, ctypes.c_int32, _PTR, _U32, ctypes.POINTER(_U32)], ctypes.c_int32),
        (api.CloseServiceHandle, [_PTR], ctypes.c_int32),
    )
    for function, arguments, result in signatures:
        function.argtypes, function.restype = arguments, result


def load() -> tuple[ServiceApi, Callable[[], int]]:
    """Load the Windows SCM library only during explicit owner construction."""
    if sys.platform != "win32":
        raise ServiceQueryError(ServiceFailure.UNSUPPORTED)
    try:
        api = cast(ServiceApi, ctypes.WinDLL("advapi32", use_last_error=True))
    except OSError:
        raise ServiceQueryError(ServiceFailure.UNAVAILABLE) from None
    return api, ctypes.get_last_error


def service_name(value: str) -> str:
    """Validate a bounded service key name, preserving SCM's exact name spelling."""
    if type(value) is not str or not value or any(char in value for char in ("\0", "/", "\\")):
        raise ServiceQueryError(ServiceFailure.INVALID_REQUEST)
    try:
        length = len(value.encode("utf-16-le")) // 2
    except UnicodeError:
        raise ServiceQueryError(ServiceFailure.INVALID_REQUEST) from None
    if length > 256:
        raise ServiceQueryError(ServiceFailure.INVALID_REQUEST)
    return value


def status(raw: ServiceStatusProcess) -> ServiceStatus:
    """Decode supported Win32 service state with a diagnostic-only valid PID."""
    try:
        state = ServiceState(raw.state)
    except ValueError:
        raise ServiceQueryError(ServiceFailure.INVALID_STATUS) from None
    if raw.service_type not in (0x10, 0x20, 0x110, 0x120):
        raise ServiceQueryError(ServiceFailure.UNSUPPORTED)
    pid = raw.pid if state.value >= 4 and raw.pid else None
    return ServiceStatus(state, raw.service_type, raw.controls, raw.win32_exit,
                         raw.service_exit, raw.checkpoint, raw.wait_hint, pid, raw.flags)
