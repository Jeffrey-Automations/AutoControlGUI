"""Expose separate query-only and host-scoped control façades over retained service ownership."""
from __future__ import annotations

import time
from typing import Callable

from .errors import AgentTaskError
from .service_operations import ServiceAcceptance, ServiceOperation
from .service_status import ServiceStatus
from .windows_service_native import ServiceApi, ServiceStatusProcess
from .windows_service_session import _ServiceSession

__all__ = ["WindowsServiceStatusReader", "WindowsServiceController", "ServiceApi", "ServiceStatusProcess"]


class WindowsServiceStatusReader:
    """A query-only owner with no control method or control rights."""

    def __init__(self, service_name: str, *, api: ServiceApi | None = None,
                 last_error: Callable[[], int] | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._session = _ServiceSession(service_name, allowed=frozenset(), api=api,
                                        last_error=last_error, clock=clock)

    @property
    def pending_cleanup(self) -> bool:
        """Whether retirement still owns handles whose close has failed."""
        return self._session.pending_cleanup

    def read(self, *, timeout: float, checkpoint: Callable[[], None]) -> ServiceStatus:
        """Read one latest SCM report with bounded admission and late-result rejection."""
        return self._session.read(timeout=timeout, checkpoint=checkpoint)

    def close(self) -> None:
        """Retire permanently, retaining failed closes for retry."""
        self._session.close()


class WindowsServiceController:
    """Internal scoped controls; no managed profile or background effect review is implied.

    Starting a service can start its configured dependencies. Host policy must
    review those effects before using this controller. Reads are best-effort and
    controls compare non-atomically; neither grants atomic state authority.
    """

    def __init__(self, service_name: str, *, allowed: frozenset[ServiceOperation],
                 api: ServiceApi | None = None, last_error: Callable[[], int] | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if type(allowed) is not frozenset or not allowed or any(type(item) is not ServiceOperation for item in allowed):
            raise AgentTaskError("service controller requires a fixed nonempty host operation scope")
        self._session = _ServiceSession(service_name, allowed=allowed, api=api,
                                        last_error=last_error, clock=clock)

    @property
    def pending_cleanup(self) -> bool:
        """Whether retirement still owns handles whose close has failed."""
        return self._session.pending_cleanup

    def read(self, *, timeout: float, checkpoint: Callable[[], None]) -> ServiceStatus:
        """Read new status independently without reconciling any unknown control effect."""
        return self._session.read(timeout=timeout, checkpoint=checkpoint)

    def perform(self, operation: ServiceOperation, *, expected: ServiceStatus, operation_id: str,
                timeout: float, checkpoint: Callable[[], None]) -> ServiceAcceptance:
        """Return original acceptance on exact replay; never automatically repeat controls."""
        return self._session.perform(operation, expected=expected, operation_id=operation_id,
                                     timeout=timeout, checkpoint=checkpoint)

    def close(self) -> None:
        """Retire permanently, retaining failed closes for retry."""
        self._session.close()
