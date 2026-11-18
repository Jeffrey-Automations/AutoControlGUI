"""Bound service requests and retain acceptance receipts without claiming completion."""
from dataclasses import dataclass
from enum import Enum
import re
from typing import Literal

from .errors import AgentEffectUnknown, AgentTaskError
from .service_status import ServiceStatus


class ServiceOperation(Enum):
    """The only service controls available to a reviewed internal controller."""

    START = "start"
    STOP = "stop"


@dataclass(frozen=True)
class ServiceAcceptance:
    """A confirmed native acceptance, never proof of the resulting service state."""

    operation_id: str
    operation: ServiceOperation
    comparison: Literal["non_atomic"] = "non_atomic"
    accepted: Literal[True] = True


@dataclass(frozen=True)
class _Request:
    operation_id: str
    operation: ServiceOperation
    expected: ServiceStatus


def request(operation: ServiceOperation, expected: ServiceStatus, operation_id: str) -> _Request:
    """Validate the complete immutable request before native acquisition or dispatch."""
    if type(operation) is not ServiceOperation or type(expected) is not ServiceStatus:
        raise AgentTaskError("service operation requires typed scope and status")
    if type(operation_id) is not str or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", operation_id) is None:
        raise AgentTaskError("service operation requires a bounded journal ID")
    expected.validate()
    return _Request(operation_id, operation, expected)


class _Ledger:
    """At most 64 non-evicting entries; an uncertain dispatch permanently blocks controls."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[_Request, ServiceAcceptance | None]] = {}

    @property
    def uncertain(self) -> bool:
        """Whether any entered syscall lacks a fully checked acceptance."""
        return any(receipt is None for _, receipt in self._entries.values())

    def existing(self, value: _Request) -> ServiceAcceptance | None:
        """Return only the original acceptance, refusing conflicts and unknown effects."""
        entry = self._entries.get(value.operation_id)
        if entry is not None:
            previous, receipt = entry
            if value != previous:
                raise AgentTaskError("service operation ID conflicts with its original request")
            if receipt is None:
                raise AgentEffectUnknown("service outcome requires independent reconciliation")
            return receipt
        if self.uncertain:
            raise AgentEffectUnknown("service outcome requires independent reconciliation")
        if len(self._entries) >= 64:
            raise AgentTaskError("service operation ledger is full")
        return None

    def begin(self, value: _Request) -> None:
        """Record uncertainty before entering the native control call."""
        self._entries[value.operation_id] = (value, None)

    def accept(self, value: _Request) -> ServiceAcceptance:
        """Store a checked acceptance without erasing its original request."""
        receipt = ServiceAcceptance(value.operation_id, value.operation)
        self._entries[value.operation_id] = (value, receipt)
        return receipt
