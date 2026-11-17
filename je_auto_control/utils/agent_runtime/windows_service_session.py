"""Own one retained service handle, serialized queries and non-replayed control attempts."""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
import math
import threading
import time
from typing import Callable, Iterator

from ..exception.control_signals import raise_if_run_interrupted
from ..executor.run_control import ExecutionStopped
from .errors import AgentEffectUnknown, AgentObservationStale, AgentTaskError
from .service_operations import ServiceAcceptance, ServiceOperation, _Ledger, _Request, request
from .service_status import ServiceFailure, ServiceQueryError, ServiceState, ServiceStatus
from . import windows_service_native as native
from .windows_service_native import ServiceApi


def _deadline(timeout: float, checkpoint: Callable[[], None], clock: Callable[[], float]) -> float:
    if type(timeout) not in (int, float) or not 0 < timeout <= 60 or not callable(checkpoint):
        raise ServiceQueryError(ServiceFailure.INVALID_REQUEST)
    deadline = clock() + timeout
    if not math.isfinite(deadline):
        raise ServiceQueryError(ServiceFailure.DEADLINE_EXCEEDED)
    return deadline


class _ServiceSession:
    """Lazy scoped service owner; retain this object until failed cleanup succeeds.

    Calls are serialized. Deadlines bound lock admission and reject late results,
    but cannot interrupt native calls or cleanup. A managed helper must bound those.
    """

    def __init__(self, name: str, *, allowed: frozenset[ServiceOperation], api: ServiceApi | None = None,
                 last_error: Callable[[], int] | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._name = native.service_name(name)
        if api is None:
            api, last_error = native.load()
        if last_error is None:
            raise ServiceQueryError(ServiceFailure.INVALID_REQUEST)
        native.bind(api)
        native.bind_controls(api, allowed)
        self._api, self._error, self._clock = api, last_error, clock
        self._handles: dict[str, int] = {}
        self._lock = threading.RLock()
        self._retired = threading.Event()
        self._publication = threading.Lock()
        self._reading = False
        self._allowed = allowed
        self._ledger = _Ledger()
        self._pending: ServiceOperation | None = None
        self._access = 4 | sum({ServiceOperation.START: 0x10, ServiceOperation.STOP: 0x20}[op] for op in allowed)

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
        if self._retired.is_set():
            raise ServiceQueryError(ServiceFailure.RETIRED)
        if not math.isfinite(now) or now >= deadline:
            raise ServiceQueryError(ServiceFailure.DEADLINE_EXCEEDED)

    @contextmanager
    def _publishing(self, deadline: float) -> Iterator[None]:
        now = self._clock()
        with self._publication:
            if self._retired.is_set():
                raise ServiceQueryError(ServiceFailure.RETIRED)
            if not math.isfinite(now) or now >= deadline:
                raise ServiceQueryError(ServiceFailure.DEADLINE_EXCEEDED)
            yield

    def _call(self, function: native._Function, *args: object) -> int:
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

    def _open(self, key: str, function: native._Function, *args: object) -> int:
        handle = self._call(function, *args)
        if type(handle) is not int or not 0 < handle < (1 << (ctypes.sizeof(ctypes.c_void_p) * 8)) - 1:
            raise ServiceQueryError(ServiceFailure.UNAVAILABLE)
        self._handles[key] = handle
        return handle

    def _read(self, deadline: float, checkpoint: Callable[[], None]) -> ServiceStatus:
        self._check(deadline, checkpoint)
        if "service" not in self._handles:
            manager = self._open("manager", self._api.OpenSCManagerW, None, None, 1)
            self._check(deadline, checkpoint)
            self._open("service", self._api.OpenServiceW, manager, self._name, self._access)
            self._check(deadline, checkpoint)
        raw, needed = native.ServiceStatusProcess(), ctypes.c_uint32()
        self._call(self._api.QueryServiceStatusEx, self._handles["service"], 0,
                   ctypes.byref(raw), ctypes.sizeof(raw), ctypes.byref(needed))
        self._check(deadline, checkpoint)
        result = native.status(raw)
        self._check(deadline, checkpoint)
        return result

    @contextmanager
    def _admitted(self, timeout: float, checkpoint: Callable[[], None]) -> Iterator[float]:
        deadline = _deadline(timeout, checkpoint, self._clock)
        remaining = deadline - self._clock()
        if not math.isfinite(remaining) or remaining <= 0 or not self._lock.acquire(timeout=min(remaining, 60)):
            raise ServiceQueryError(ServiceFailure.DEADLINE_EXCEEDED)
        if self._reading:
            self._lock.release()
            raise ServiceQueryError(ServiceFailure.BUSY)
        self._reading = True
        try:
            yield deadline
        finally:
            self._reading = False
            self._lock.release()

    def _retire_failed_read(self) -> None:
        try:
            self.close()
        except ServiceQueryError:
            pass  # Failed handles remain owned while the original failure propagates.

    def _read_checked(self, deadline: float, checkpoint: Callable[[], None]) -> ServiceStatus:
        try:
            return self._read(deadline, checkpoint)
        except BaseException:
            self._retire_failed_read()
            raise

    def read(self, *, timeout: float, checkpoint: Callable[[], None]) -> ServiceStatus:
        """Read independent status; only an accepted operation can clear its pending fence."""
        with self._admitted(timeout, checkpoint) as deadline:
            value = self._read_checked(deadline, checkpoint)
            desired = {ServiceOperation.START: ServiceState.RUNNING, ServiceOperation.STOP: ServiceState.STOPPED}
            try:
                with self._publishing(deadline):
                    if (self._pending is not None and not self._ledger.uncertain
                            and value.state is desired[self._pending]):
                        self._pending = None
                    return value
            except BaseException:
                self._retire_failed_read()
                raise

    def perform(self, operation: ServiceOperation, *, expected: ServiceStatus, operation_id: str,
                timeout: float, checkpoint: Callable[[], None]) -> ServiceAcceptance:
        """Dispatch once after a same-handle preflight; acceptance is not completion."""
        value = request(operation, expected, operation_id)
        if operation not in self._allowed:
            raise AgentTaskError("service operation is outside the host scope")
        with self._admitted(timeout, checkpoint) as deadline:
            self._check(deadline, checkpoint)
            cached = self._ledger.existing(value)
            if cached is not None:
                with self._publishing(deadline):
                    return cached
            if self._pending is not None:
                raise AgentTaskError("service operation awaits independent status readback")
            actual = self._read_checked(deadline, checkpoint)
            if actual != expected:
                raise AgentObservationStale("service status changed before dispatch")
            self._precondition(operation, actual)
            self._check(deadline, checkpoint)
            with self._publishing(deadline):
                self._ledger.begin(value)
                self._pending = operation
            return self._dispatch(value, deadline, checkpoint)

    @staticmethod
    def _precondition(operation: ServiceOperation, status: ServiceStatus) -> None:
        if operation is ServiceOperation.START:
            allowed = status.state is ServiceState.STOPPED
        else:
            allowed = status.state in (ServiceState.RUNNING, ServiceState.PAUSED) and bool(status.controls_accepted & 1)
        if not allowed:
            raise AgentTaskError("service status does not permit this operation")

    def _dispatch(self, value: _Request, deadline: float,
                  checkpoint: Callable[[], None]) -> ServiceAcceptance:
        try:
            result = native.control(self._api, self._handles["service"], value.operation)
        except BaseException as error:  # reason: preserve control signals and hide native failure details
            if not isinstance(error, Exception) or isinstance(error, ExecutionStopped):
                raise
            raise_if_run_interrupted(error)
            raise AgentEffectUnknown("service control outcome is unknown") from None
        if not result:
            raise AgentEffectUnknown("service control outcome is unknown")
        try:
            self._check(deadline, checkpoint)
            with self._publishing(deadline):
                return self._ledger.accept(value)
        except ServiceQueryError:
            raise AgentEffectUnknown("service acceptance was not confirmed before retirement or deadline") from None

    def close(self) -> None:
        """Retire before waiting; attempt every close and retain failures for retry."""
        with self._publication:
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
