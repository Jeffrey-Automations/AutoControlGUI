"""Apply managed task authority to one host-selected retained service controller."""
from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
import threading
import time
from typing import Any, Callable, Iterator, Mapping, NoReturn, Protocol
import uuid

from .context import TaskOperation, authorization_key, current_operation
from .errors import AgentEffectUnknown, AgentObservationStale, AgentTaskError
from .models import AgentTaskSpec
from .policy import TaskPolicy
from .service_observation import SERVICE_TOOLS, ServiceBinding, ServiceObservation, ServiceReceipt
from .service_operations import ServiceAcceptance, ServiceOperation, request
from .service_status import ServiceStatus


class ServiceController(Protocol):
    """A retained host controller; the task supplies neither handles nor service names."""

    def read(self, *, timeout: float, checkpoint: Callable[[], None]) -> ServiceStatus:
        """Read status through the retained handle under the supplied live checkpoint."""

    def perform(self, operation: ServiceOperation, *, expected: ServiceStatus, operation_id: str,
                timeout: float, checkpoint: Callable[[], None]) -> ServiceAcceptance:
        """Compare status and issue one scoped control with an idempotency identity."""

    def close(self) -> None:
        """Retire the retained handle owner, keeping failed closes retryable."""


class ServiceTarget(ABC):
    """Explicit service dispatch contract, separate from revision-grounded semantic targets."""

    @property
    @abstractmethod
    def service_binding(self) -> ServiceBinding:
        """Return immutable retained-owner provenance without acquiring resources."""

    @abstractmethod
    def check_spec(self, spec: AgentTaskSpec) -> None:
        """Validate host scope without changing task or resource ownership."""

    @abstractmethod
    def observe(self) -> dict[str, Any]:
        """Return a fresh closed service report."""

    @abstractmethod
    def perform_observed(self, name: str, arguments: Mapping[str, Any], *,
                         observation: Mapping[str, Any], operation_id: str) -> ServiceReceipt:
        """Revalidate non-atomic state and return only the original acceptance."""

    @abstractmethod
    def cleanup(self) -> None:
        """Retire ownership, preserving failed cleanup for retry."""


@dataclass(frozen=True)
class _Scope:
    spec: AgentTaskSpec
    owner: tuple[str, str, str | None] | None


class ManagedServiceTarget(ServiceTarget):
    """One managed scope owns the injected controller before its first acquisition."""

    def __init__(self, target_id: str, config_digest: str, scope_id: str, controller: ServiceController, *,
                 allowed: frozenset[ServiceOperation]) -> None:
        if type(allowed) is not frozenset or any(type(item) is not ServiceOperation for item in allowed):
            raise AgentTaskError("service target requires immutable host operations")
        self._binding = ServiceBinding(target_id, config_digest, scope_id, uuid.uuid4().hex)
        self._controller, self._allowed = controller, allowed
        self._scope: _Scope | None = None
        self._terminal = threading.Event()
        self._work = threading.RLock()
        self._publication = threading.Lock()
        self._active = False
        self._receipts: dict[str, tuple[dict[str, Any], ServiceReceipt]] = {}

    @property
    def service_binding(self) -> ServiceBinding:
        """Expose the fixed owner binding without reading a service."""
        return self._binding

    @contextmanager
    def _admitted(self) -> Iterator[None]:
        with self._work:
            if self._active:
                raise AgentTaskError("service target does not permit reentrant operations")
            self._active = True
            try:
                yield
            finally:
                self._active = False

    def _validate(self, operation: TaskOperation) -> None:
        if (self._terminal.is_set() or current_operation() is not operation
                or self._scope != _Scope(operation.spec, authorization_key(operation.owner))):
            raise AgentTaskError("service target is outside its original live managed scope")

    def _checkpoint(self, operation: TaskOperation) -> None:
        self._validate(operation)
        operation.checkpoint()
        self._validate(operation)

    def _operation(self) -> TaskOperation:
        operation = current_operation()
        if operation is None:
            raise AgentTaskError("service target requires managed dispatch")
        self._checkpoint(operation)
        return operation

    def ready(self, spec: AgentTaskSpec) -> tuple[bool, str]:
        """Pin the original task and authority without acquiring native resources."""
        with self._admitted():
            operation = current_operation()
            self.check_spec(spec)
            if operation is None or operation.spec != spec:
                raise AgentTaskError("service target requires its host-selected external scope")
            scope = _Scope(spec, authorization_key(operation.owner))
            if self._scope is not None and self._scope != scope:
                raise AgentTaskError("service target already belongs to another managed scope")
            with self._publication:
                if self._terminal.is_set():
                    raise AgentTaskError("service target is retired")
                self._scope = scope
            self._checkpoint(operation)
            return True, ""

    def check_spec(self, spec: AgentTaskSpec) -> None:
        """Validate the fixed external tool scope before worker configuration changes."""
        tools = {name for name, action in SERVICE_TOOLS.items() if action in self._allowed}
        if (spec.target != self._binding.target_id or spec.mode != "external" or spec.roots or spec.apps
                or not set(spec.allowed_tools) <= tools):
            raise AgentTaskError("service target requires its host-selected external scope")

    def observe(self) -> dict[str, Any]:
        """Capture current SCM diagnostic status under the original live authority."""
        with self._admitted():
            operation = self._operation()
            started = time.perf_counter()
            status = self._controller.read(timeout=1.0, checkpoint=lambda: self._checkpoint(operation))
            self._checkpoint(operation)
            value = ServiceObservation(self._binding, status, uuid.uuid4().hex, started, time.perf_counter())
            with self._publication:
                self._validate(operation)
                return value.to_dict()

    def perform_observed(self, name: str, arguments: Mapping[str, Any], *,
                         observation: Mapping[str, Any], operation_id: str) -> ServiceReceipt:
        """Retain accepted-at timestamps on replay and never promote them into completion."""
        with self._admitted():
            operation = self._operation()
            TaskPolicy(operation.spec).check(name, arguments)
            if name not in SERVICE_TOOLS or arguments or SERVICE_TOOLS[name] not in self._allowed:
                raise AgentTaskError("service command requires a reviewed tool and empty arguments")
            expected = ServiceObservation.from_dict(observation)
            if expected.binding != self._binding:
                raise AgentObservationStale("service observation belongs to another retained owner")
            action = SERVICE_TOOLS[name]
            request(action, expected.status, operation_id)
            previous = self._receipts.get(operation_id)
            self._check_replay(previous, expected, action)
            if previous is None and len(self._receipts) >= 64:
                raise AgentTaskError("service receipt capacity is exhausted")
            self._checkpoint(operation)
            accepted = self._controller.perform(action, expected=expected.status, operation_id=operation_id,
                                                timeout=1.0, checkpoint=lambda: self._checkpoint(operation))
            self._confirm(accepted, action, operation_id)
            receipt = previous[1] if previous is not None else ServiceReceipt(
                self._binding, operation_id, action, time.perf_counter())
            self._receipts[operation_id] = (expected.grounding(), receipt)
            self._checkpoint(operation)
            with self._publication:
                self._validate(operation)
                return receipt

    @staticmethod
    def _check_replay(previous: tuple[dict[str, Any], ServiceReceipt] | None,
                      expected: ServiceObservation, action: ServiceOperation) -> None:
        if previous is not None and (previous[0] != expected.grounding() or previous[1].operation is not action):
            raise AgentTaskError("service operation ID conflicts with its original request")

    @staticmethod
    def _confirm(accepted: ServiceAcceptance, action: ServiceOperation, operation_id: str) -> None:
        if (type(accepted) is not ServiceAcceptance or accepted.operation is not action
                or accepted.operation_id != operation_id or accepted.accepted is not True
                or accepted.comparison != "non_atomic"):
            raise AgentEffectUnknown("service command acceptance was not confirmed")

    def perform(self, _name: str, _arguments: Mapping[str, Any]) -> NoReturn:
        """Refuse unobserved service control through a generic target call."""
        raise AgentTaskError("service control requires its observed dispatch contract")

    def cleanup(self) -> None:
        """Retire before waiting for the controller, retaining failed close ownership."""
        with self._publication:
            self._terminal.set()
        self._controller.close()
