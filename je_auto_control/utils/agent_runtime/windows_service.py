"""Retain local SCM query handles for one host-selected service until retirement."""
from __future__ import annotations

import ctypes
import math
import sys
import threading
import time
from typing import Callable, Protocol, cast

from .service_status import ServiceFailure, ServiceQueryError, ServiceState, ServiceStatus

_U32 = ctypes.c_uint32
_PTR = ctypes.c_void_p


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

    _fields_ = [(name, _U32) for name in (
        "service_type", "state", "controls", "win32_exit", "service_exit",
        "checkpoint", "wait_hint", "pid", "flags")]


def _bind(api: ServiceApi) -> None:
    signatures: tuple[tuple[_Function, list[object], object], ...] = (
        (api.OpenSCManagerW, [ctypes.c_wchar_p, ctypes.c_wchar_p, _U32], _PTR),
        (api.OpenServiceW, [_PTR, ctypes.c_wchar_p, _U32], _PTR),
        (api.QueryServiceStatusEx, [_PTR, ctypes.c_int32, _PTR, _U32, ctypes.POINTER(_U32)], ctypes.c_int32),
        (api.CloseServiceHandle, [_PTR], ctypes.c_int32),
    )
    for function, arguments, result in signatures:
        function.argtypes, function.restype = arguments, result


def _load() -> tuple[ServiceApi, Callable[[], int]]:
    if sys.platform != "win32":
        raise ServiceQueryError(ServiceFailure.UNSUPPORTED)
    try:
        api = cast(ServiceApi, ctypes.WinDLL("advapi32", use_last_error=True))
    except OSError:
        raise ServiceQueryError(ServiceFailure.UNAVAILABLE) from None
    return api, ctypes.get_last_error


def _name(value: str) -> str:
    if type(value) is not str or not value or any(char in value for char in ("\0", "/", "\\")):
        raise ServiceQueryError(ServiceFailure.INVALID_REQUEST)
    try:
        length = len(value.encode("utf-16-le")) // 2
    except UnicodeError:
        raise ServiceQueryError(ServiceFailure.INVALID_REQUEST) from None
    if length > 256:
        raise ServiceQueryError(ServiceFailure.INVALID_REQUEST)
    return value


def _status(raw: ServiceStatusProcess) -> ServiceStatus:
    try:
        state = ServiceState(raw.state)
    except ValueError:
        raise ServiceQueryError(ServiceFailure.INVALID_STATUS) from None
    if raw.service_type not in (0x10, 0x20, 0x110, 0x120):
        raise ServiceQueryError(ServiceFailure.UNSUPPORTED)
    pid = raw.pid if state.value >= 4 and raw.pid else None
    return ServiceStatus(state, raw.service_type, raw.controls, raw.win32_exit,
                         raw.service_exit, raw.checkpoint, raw.wait_hint, pid, raw.flags)


def _deadline(timeout: float, checkpoint: Callable[[], None], clock: Callable[[], float]) -> float:
    if type(timeout) not in (int, float) or not 0 < timeout <= 60 or not callable(checkpoint):
        raise ServiceQueryError(ServiceFailure.INVALID_REQUEST)
    deadline = clock() + timeout
    if not math.isfinite(deadline):
        raise ServiceQueryError(ServiceFailure.DEADLINE_EXCEEDED)
    return deadline


class WindowsServiceStatusReader:
    """Lazy, query-only owner; retain this object until failed cleanup succeeds.

    Calls are serialized. Deadlines bound lock admission and reject late results,
    but cannot interrupt native calls or cleanup. A managed helper must bound those.
    """

    def __init__(self, service_name: str, *, api: ServiceApi | None = None,
                 last_error: Callable[[], int] | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._name = _name(service_name)
        if api is None:
            api, last_error = _load()
        if last_error is None:
            raise ServiceQueryError(ServiceFailure.INVALID_REQUEST)
        _bind(api)
        self._api, self._error, self._clock = api, last_error, clock
        self._handles: dict[str, int] = {}
        self._lock = threading.RLock()
        self._retired = threading.Event()
        self._reading = False

    @property
    def pending_cleanup(self) -> bool:
        """Whether retirement still owns handles whose close has failed."""
        with self._lock:
            return self._retired.is_set() and bool(self._handles)

    def _check(self, deadline: float, checkpoint: Callable[[], None]) -> None:
        if self._retired.is_set():
            raise ServiceQueryError(ServiceFailure.RETIRED)
        checkpoint()
        if self._retired.is_set():
            raise ServiceQueryError(ServiceFailure.RETIRED)
        now = self._clock()
        if not math.isfinite(now) or now >= deadline:
            raise ServiceQueryError(ServiceFailure.DEADLINE_EXCEEDED)

    def _call(self, function: _Function, *args: object) -> int:
        try:
            result = function(*args)
            if result:
                return result
            code = self._error()
        except (OSError, ctypes.ArgumentError):
            raise ServiceQueryError(ServiceFailure.UNAVAILABLE) from None
        reason = {5: ServiceFailure.ACCESS_DENIED, 1060: ServiceFailure.NOT_FOUND,
                  50: ServiceFailure.UNSUPPORTED, 120: ServiceFailure.UNSUPPORTED}.get(
                      code, ServiceFailure.UNAVAILABLE)
        raise ServiceQueryError(reason)

    def _open(self, key: str, function: _Function, *args: object) -> int:
        handle = self._call(function, *args)
        if type(handle) is not int or not 0 < handle < (1 << (ctypes.sizeof(_PTR) * 8)) - 1:
            raise ServiceQueryError(ServiceFailure.UNAVAILABLE)
        self._handles[key] = handle
        return handle

    def _read(self, deadline: float, checkpoint: Callable[[], None]) -> ServiceStatus:
        self._check(deadline, checkpoint)
        if "service" not in self._handles:
            manager = self._open("manager", self._api.OpenSCManagerW, None, None, 1)
            self._check(deadline, checkpoint)
            self._open("service", self._api.OpenServiceW, manager, self._name, 4)
            self._check(deadline, checkpoint)
        raw, needed = ServiceStatusProcess(), _U32()
        self._call(self._api.QueryServiceStatusEx, self._handles["service"], 0,
                   ctypes.byref(raw), ctypes.sizeof(raw), ctypes.byref(needed))
        self._check(deadline, checkpoint)
        result = _status(raw)
        self._check(deadline, checkpoint)
        return result

    def read(self, *, timeout: float, checkpoint: Callable[[], None]) -> ServiceStatus:
        """Read one latest SCM report, permanently retiring on an admitted failure."""
        deadline = _deadline(timeout, checkpoint, self._clock)
        remaining = deadline - self._clock()
        if not math.isfinite(remaining) or remaining <= 0 or not self._lock.acquire(timeout=min(remaining, 60)):
            raise ServiceQueryError(ServiceFailure.DEADLINE_EXCEEDED)
        if self._reading:
            self._lock.release()
            raise ServiceQueryError(ServiceFailure.BUSY)
        self._reading = True
        try:
            return self._read(deadline, checkpoint)
        except BaseException:
            self._retired.set()
            try:
                self.close()
            except ServiceQueryError:
                pass  # Failed handles remain owned; preserve the primary cancellation or query failure.
            raise
        finally:
            self._reading = False
            self._lock.release()

    def close(self) -> None:
        """Retire before waiting; attempt every close and retain failures for retry."""
        self._retired.set()
        with self._lock:
            for key, handle in reversed(tuple(self._handles.items())):
                try:
                    self._call(self._api.CloseServiceHandle, handle)
                except ServiceQueryError:
                    continue
                del self._handles[key]
            if self._handles:
                raise ServiceQueryError(ServiceFailure.CLEANUP_FAILED)
