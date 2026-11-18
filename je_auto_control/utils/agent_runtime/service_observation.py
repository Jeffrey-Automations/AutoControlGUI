"""Bind best-effort service reports and acceptance receipts to one retained owner."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import sys
from typing import Any, Mapping

from .capture_metadata import _identifier
from .errors import AgentTaskError
from .service_operations import ServiceOperation
from .service_status import ServiceStatus

SERVICE_TOOLS = {"AC_service_start": ServiceOperation.START, "AC_service_stop": ServiceOperation.STOP}
_BINDING = frozenset({"target_id", "config_digest", "scope_id", "binding_id"})


def timestamp(value: float) -> None:
    """Require finite same-host monotonic time without accepting booleans."""
    if type(value) not in (int, float) or not 0 <= value <= sys.float_info.max:
        raise AgentTaskError("service evidence has an invalid time")


@dataclass(frozen=True)
class ServiceBinding:
    """Host provenance and retained-owner continuity, not a Windows incarnation proof."""

    target_id: str
    config_digest: str
    scope_id: str
    binding_id: str

    def __post_init__(self) -> None:
        for value in (self.target_id, self.scope_id, self.binding_id):
            _identifier(value)
        if type(self.config_digest) is not str or re.fullmatch(r"[0-9a-f]{64}", self.config_digest) is None:
            raise AgentTaskError("service evidence requires a fixed configuration digest")

    def to_dict(self) -> dict[str, str]:
        """Return fixed provenance fields without native service identifiers."""
        return asdict(self)


@dataclass(frozen=True)
class ServiceObservation:
    """One complete latest-SCM report with explicit non-atomic consistency."""

    binding: ServiceBinding
    status: ServiceStatus
    observation_id: str
    started: float
    finished: float

    def __post_init__(self) -> None:
        if type(self.binding) is not ServiceBinding or type(self.status) is not ServiceStatus:
            raise AgentTaskError("service observation requires typed evidence")
        self.status.validate()
        _identifier(self.observation_id)
        timestamp(self.started)
        timestamp(self.finished)
        if self.started > self.finished:
            raise AgentTaskError("service observation has a reversed capture interval")

    def to_dict(self) -> dict[str, Any]:
        """Serialize a closed version-one report without a fictitious revision."""
        return {"service_version": 1, **self.binding.to_dict(), "status": self.status.to_dict(),
                "observation_id": self.observation_id, "started": self.started, "finished": self.finished,
                "consistency": "best_effort"}

    def grounding(self) -> dict[str, Any]:
        """Retain status and provenance while excluding capture-specific metadata."""
        return {key: value for key, value in self.to_dict().items()
                if key not in {"observation_id", "started", "finished"}}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ServiceObservation:
        """Reject missing, extra and incorrectly typed source fields."""
        keys = _BINDING | {"service_version", "status", "observation_id", "started", "finished", "consistency"}
        if not isinstance(value, Mapping) or set(value) != keys:
            raise AgentTaskError("service observation has an unknown schema")
        if type(value["service_version"]) is not int or value["service_version"] != 1:
            raise AgentTaskError("service observation has an unsupported version")
        if value["consistency"] != "best_effort":
            raise AgentTaskError("service observation cannot claim atomic consistency")
        return cls(ServiceBinding(**{key: value[key] for key in _BINDING}),
                   ServiceStatus.from_dict(value["status"]), value["observation_id"],
                   value["started"], value["finished"])


@dataclass(frozen=True)
class ServiceReceipt:
    """Original checked acceptance time and scope, never a service completion claim."""

    binding: ServiceBinding
    operation_id: str
    operation: ServiceOperation
    accepted_at: float

    def __post_init__(self) -> None:
        if type(self.binding) is not ServiceBinding or type(self.operation) is not ServiceOperation:
            raise AgentTaskError("service receipt requires typed scope and operation")
        _identifier(self.operation_id)
        timestamp(self.accepted_at)

    def to_dict(self) -> dict[str, Any]:
        """Publish only a non-atomic acceptance linked to its journal operation."""
        return {**self.binding.to_dict(), "operation_id": self.operation_id, "operation": self.operation.value,
                "accepted_at": self.accepted_at, "comparison": "non_atomic", "accepted": True}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ServiceReceipt:
        """Parse an exact confirmed acceptance envelope."""
        keys = _BINDING | {"operation_id", "operation", "accepted_at", "comparison", "accepted"}
        if not isinstance(value, Mapping) or set(value) != keys:
            raise AgentTaskError("service receipt has an unknown schema")
        if value["comparison"] != "non_atomic" or value["accepted"] is not True:
            raise AgentTaskError("service receipt did not confirm non-atomic acceptance")
        if type(value["operation"]) is not str or value["operation"] not in {"start", "stop"}:
            raise AgentTaskError("service receipt has an unknown operation")
        return cls(ServiceBinding(**{key: value[key] for key in _BINDING}), value["operation_id"],
                   ServiceOperation(value["operation"]), value["accepted_at"])
